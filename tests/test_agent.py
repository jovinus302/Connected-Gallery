import pytest
from langchain_core.messages import AIMessage
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import *
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store


class ScriptedGateway:
    def __init__(self):
        self.n = 0

    async def invoke(self, messages, tools):
        self.n += 1
        if self.n == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "inspect_photos",
                        "args": {"photo_ids": ["a", "b"]},
                        "id": "inspect",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_exploration_result",
                    "args": {
                        "label": "과거의 와인",
                        "items": [{"photo_id": "b", "reason": "이미지 확인"}],
                        "complete": True,
                    },
                    "id": "submit",
                    "type": "tool_call",
                }
            ],
        )


@pytest.mark.asyncio
async def test_real_graph_with_scripted_gateway(store):
    request = RunRequest(
        role="explorer",
        explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"), year=2015),
    )
    runner = GraphAgentRunner(store, None, ScriptedGateway())
    result = await runner.execute("graph-test", request)
    assert result["items"][0]["photo_id"] == "b"
    assert len(store.rows("SELECT * FROM events WHERE kind='results'")) == 1


def test_cancelled_tool_cannot_submit(store):
    request = RunRequest(role="analyst", photo_ids=["a"])
    store.write(
        "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
        ("r", "k", request.model_dump_json(), "cancelled", None, None, 0),
    )
    tools = GalleryTools(store, None, request, "r")
    tools.seen = {"a"}
    with pytest.raises(ValueError):
        tools.submit_photo_analysis(PhotoAnalysis(photo_id="a", description="late"))
    assert store.analysis("a") is None


@pytest.mark.asyncio
async def test_analyst_receives_image_and_reserves_final_turn(store):
    from langchain_anthropic.chat_models import _format_messages

    class BudgetGateway:
        def __init__(self):
            self.n = 0

        async def invoke(self, messages, schemas):
            self.n += 1
            # Exercise the SDK formatter too: budget hints must remain consecutive
            # with the system prompt, not break Anthropic message ordering.
            _format_messages(messages)
            assert any(b.get("type") == "image" for b in messages[2].content)
            names = {s["name"] for s in schemas}
            assert "list_photos" not in names
            if self.n < 4:
                name, args = "inspect_region", {"photo_id": "a"}
            else:
                assert names == {"submit_photo_analysis"}
                name, args = "submit_photo_analysis", {"photo_id": "a", "description": "검증한 사진"}
            return AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": str(self.n), "type": "tool_call",
            }])

    gateway = BudgetGateway()
    result = await GraphAgentRunner(store, None, gateway).execute(
        "budget-test", RunRequest(role="analyst", photo_ids=["a"])
    )
    assert gateway.n == 4
    assert result["photo_id"] == "a"
    assert store.analysis("a")["description"] == "검증한 사진"


def test_inference_does_not_lock_store_and_cancel_prevents_commit(store):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()

    class BlockingModels:
        visual_space = "visual-test"
        text_space = "test"

        def image(self, image):
            return self.visual_space, [1, 0]

        def text(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)
            return "test", [1, 0]

    request = RunRequest(role="analyst", photo_ids=["a"])
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "blocked", "blocked", request.model_dump_json(), "running", None, None, 0,
    ))
    toolkit = GalleryTools(store, BlockingModels(), request, "blocked")
    toolkit.seen = {"a"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        submit = pool.submit(toolkit.invoke, "submit_photo_analysis", {
            "photo_id": "a", "description": "must not survive cancellation",
        })
        try:
            assert entered.wait(1)
            # This operation would time out if submission still held the store lock.
            pool.submit(store.write, "UPDATE runs SET status='cancelled' WHERE id='blocked'").result(timeout=1)
        finally:
            release.set()
        with pytest.raises(ValueError, match="no longer active"):
            submit.result(timeout=2)
    assert store.analysis("a") is None
    assert not store.rows("SELECT * FROM vectors WHERE photo_id='a'")


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_valid", [True, False])
async def test_final_submission_validation_gets_exactly_one_repair(store, repair_valid):
    import json

    class InvalidSubmissionGateway:
        def __init__(self):
            self.n = 0

        async def invoke(self, messages, schemas):
            self.n += 1
            if self.n <= 3:
                name, args = "inspect_region", {"photo_id": "a"}
            else:
                assert {s["name"] for s in schemas} == {"submit_photo_analysis"}
                if self.n == 5:
                    error = json.loads(messages[-1].content)
                    assert error["issues"][0]["path"] == ["regions", 0, "box", "width"]
                    assert "input" not in error["issues"][0]
                name = "submit_photo_analysis"
                args = {"photo_id": "a", "description": "observed photo", "regions": [{
                    "photo_id": "a", "kind": "object", "label": "대상", "evidence": "시각 관찰",
                    "box": {"x": 0, "y": 0, "width": 0.5 if self.n == 5 and repair_valid else 2, "height": 0.5},
                }]}
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(self.n), "type": "tool_call"}])

    gateway = InvalidSubmissionGateway()
    runner = GraphAgentRunner(store, None, gateway)
    request = RunRequest(role="analyst", photo_ids=["a"])
    if repair_valid:
        result = await runner.execute("repair", request)
        assert result["regions"][0]["box"]["width"] == 0.5
    else:
        with pytest.raises(RuntimeError, match="repair exhausted"):
            await runner.execute("repair", request)
        assert store.analysis("a") is None
    assert gateway.n == 5


@pytest.mark.asyncio
async def test_analysis_deduplicates_different_request_keys_and_recovers_once(store):
    import asyncio
    from connected_gallery.application.service import RunService

    class WaitingRunner:
        async def execute(self, rid, request):
            await asyncio.Event().wait()

    service = RunService(store, WaitingRunner())
    one = RunRequest(role="analyst", photo_ids=["a"], idempotency_key="android")
    two = RunRequest(role="analyst", photo_ids=["a"], idempotency_key="recovery")
    first = service.start(one)
    assert service.start(two)["id"] == first["id"]
    assert len(service.tasks) == 1
    service.cancel_analysis_for_photo("a")
    assert service.get(first["id"])["status"] == "cancelled"
    await service.stop()

    for n in range(2):
        req = RunRequest(role="analyst", photo_ids=["b"], idempotency_key=f"legacy-{n}")
        store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
            f"legacy-{n}", req.idempotency_key, req.model_dump_json(), "queued", None, None, n,
        ))
    await service.recover()
    assert len(service.tasks) == 1
    assert service.get("legacy-1")["status"] == "cancelled"
    await service.stop()


@pytest.mark.asyncio
async def test_checkpoint_cleanup_failure_preserves_committed_analysis(store, monkeypatch):
    import asyncio
    import sqlite3
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    class SubmitGateway:
        async def invoke(self, messages, tools):
            return AIMessage(content="", tool_calls=[{
                "name": "submit_photo_analysis", "args": {"photo_id": "a", "description": "observed"},
                "id": "submit", "type": "tool_call",
            }])

    async def fail_cleanup(self, thread_id):
        raise sqlite3.OperationalError("private SQL must not enter diagnostics")

    monkeypatch.setattr(AsyncSqliteSaver, "adelete_thread", fail_cleanup)
    service = RunService(store, GraphAgentRunner(store, None, SubmitGateway()))
    service.auto_enabled = False
    run = service.start(RunRequest(role="analyst", photo_ids=["a"]))
    await asyncio.wait_for(service.tasks[run["id"]], 5)
    final = service.get(run["id"])
    assert final["status"] == "completed"
    assert final["result"] == store.analysis("a")
    assert final["error"] is None
    diagnostics = store.rows("SELECT data FROM events WHERE kind='execution_error'")
    assert len(diagnostics) == 1
    assert "OperationalError" in diagnostics[0]["data"]
    assert "private SQL" not in diagnostics[0]["data"]


def test_cancelled_run_rolls_back_evidence_indexes_and_revision(store):
    request = RunRequest(role="analyst", photo_ids=["a"])
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "cancelled", "cancelled", request.model_dump_json(), "cancelled", None, None, 0,
    ))
    revision = store.revision
    with pytest.raises(ValueError, match="no longer active"):
        store.save_analysis(PhotoAnalysis(photo_id="a", description="not committed"),
                            vectors=[("new", "a", "test", [1, 0])], run_id="cancelled")
    assert store.analysis("a") is None
    assert not store.has_vector("new")
    assert store.revision == revision


@pytest.mark.asyncio
async def test_concurrent_graphs_share_checkpoint_db_without_serializing_models(store):
    import asyncio
    waiting = 0
    all_models_entered = asyncio.Event()

    class ConcurrentGateway:
        async def invoke(self, messages, schemas):
            nonlocal waiting
            waiting += 1
            if waiting == 3:
                all_models_entered.set()
            await asyncio.wait_for(all_models_entered.wait(), 3)
            # Empty message ends each run without inventing an accepted result.
            return AIMessage(content="")

    runner = GraphAgentRunner(store, None, ConcurrentGateway())
    results = await asyncio.gather(*[
        runner.execute("parallel-" + pid, RunRequest(role="analyst", photo_ids=[pid]))
        for pid in ("a", "b", "c")
    ], return_exceptions=True)
    assert waiting == 3
    assert all(isinstance(r, RuntimeError) and "without a valid" in str(r) for r in results)


def test_old_cache_cannot_return_anchor(store):
    import hashlib
    import os
    from connected_gallery.adapters.store import encoded
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    value = request.explore.model_dump()
    value.pop("request_revision", None)
    old_key = hashlib.sha256(encoded(["agent-spec-v5", os.getenv("CG_MODEL", "gpt-5.4-mini"), value]).encode()).hexdigest()
    store.cache_put(old_key, {"items": [{"photo_id": "a", "reason": "legacy"}]})
    service = RunService(store, None)
    assert store.cache_get(service.cache_key(request)) is None


@pytest.mark.asyncio
async def test_explorer_receives_selected_crop_before_first_model_turn(store):
    class CropGateway:
        async def invoke(self, messages, schemas):
            assert any(b.get("type") == "image" for b in messages[2].content)
            # The fixture crop is 25x50 rather than the 100x100 full image.
            import base64, io
            from PIL import Image
            block = next(b for b in messages[2].content if b.get("type") == "image")
            with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as im:
                assert im.size == (25, 50)
            return AIMessage(content="", tool_calls=[{
                "name": "submit_exploration_result", "args": {"label": "partial", "items": [], "complete": False},
                "id": "partial", "type": "tool_call",
            }])

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(
        photo_id="a", box=Box(x=0, y=0, width=.25, height=.5))))
    runner = GraphAgentRunner(store, None, CropGateway())
    with pytest.raises(RuntimeError, match="budget exceeded"):
        await runner.execute("initial-crop", request)


@pytest.mark.asyncio
async def test_configured_background_limit_bounds_running_jobs(store, monkeypatch):
    import asyncio
    monkeypatch.setenv("CG_ANALYSIS_CONCURRENCY", "2")
    reached = asyncio.Event()
    running = 0

    class WaitingRunner:
        async def execute(self, rid, request):
            nonlocal running
            running += 1
            if running == 2:
                reached.set()
            try:
                await asyncio.Event().wait()
            finally:
                running -= 1

    service = RunService(store, WaitingRunner())
    for pid in ("a", "b", "c"):
        service.start(RunRequest(role="analyst", photo_ids=[pid]))
    await asyncio.wait_for(reached.wait(), 1)
    assert running == 2
    assert len(store.rows("SELECT id FROM runs WHERE status='queued'")) == 1
    await service.stop()


@pytest.mark.asyncio
async def test_pause_and_delete_recovers_unrelated_analysis(store):
    import asyncio

    class WaitingRunner:
        async def execute(self, rid, request):
            await asyncio.Event().wait()

    service = RunService(store, WaitingRunner())
    runs = [service.start(RunRequest(role="analyst", photo_ids=[pid])) for pid in ("a", "b", "c")]
    await asyncio.sleep(0)
    await service.stop(preserve_pending=True)
    assert all(service.get(r["id"])["status"] == "queued" for r in runs)
    store.delete("a")
    await service.recover()
    assert set(service.tasks) == {r["id"] for r in runs[1:]}
    await service.stop()


def test_configured_deadline_is_shared_by_service_and_tools(store, monkeypatch):
    import time
    monkeypatch.setenv("CG_EXPLORE_TIMEOUT_SECONDS", "120")
    service = RunService(store, None)
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    tools = GalleryTools(store, None, request, "deadline")
    assert service.explore_timeout == 120
    assert 119 < tools.deadline - time.monotonic() <= 120
    # Tools remain authorized past the old, hard-coded 45-second boundary.
    tools.deadline -= 46
    tools.authorize("a")


@pytest.mark.asyncio
async def test_candidate_images_do_not_replace_latest_anchor_reference(store):
    import json
    from langchain_core.messages import HumanMessage
    from langchain_anthropic.chat_models import _format_messages

    class AnchorGateway:
        original_image = None
        n = 0

        async def invoke(self, messages, schemas):
            self.n += 1
            _format_messages(messages)
            if self.n == 1:
                self.original_image = next(b for b in messages[2].content if b.get("type") == "image")
                name, args = "inspect_photos", {"photo_ids": ["b"]}
            else:
                assert isinstance(messages[-1], HumanMessage)
                reminder = json.loads(messages[-1].content[0]["text"])
                assert reminder["immutable_selected_anchor"]["anchor"]["photo_id"] == "a"
                assert reminder["immutable_selected_anchor"]["year"] == 2015
                assert messages[-1].content[-1] == self.original_image
                name, args = "submit_exploration_result", {"label": "verified", "items": [{"photo_id": "b", "reason": "observed"}]}
            return AIMessage(content="", tool_calls=[{"name":name,"args":args,"id":str(self.n),"type":"tool_call"}])

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"), year=2015))
    result = await GraphAgentRunner(store, None, AnchorGateway()).execute("anchor-reminder", request)
    assert result["items"][0]["photo_id"] == "b"
