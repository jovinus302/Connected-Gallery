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
