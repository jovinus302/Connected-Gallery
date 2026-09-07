import asyncio
import base64
import io
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_anthropic import ChatAnthropic
from PIL import Image
from pydantic import ValidationError

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.context import (
    ContextTools, PhotoContextAgent as ProductionPhotoContextAgent, tool_validation_diagnostic,
)
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.application.service import RunService
from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.demo import DemoSession
from connected_gallery.domain.context import PhotoContext, capture_metadata, CONTEXT_WORDING_MODEL, context_wording_fields
from connected_gallery.domain.models import Box, PhotoAsset, ResultGroup, RunRequest
from test_contracts import asset, store


def context(ids=("b", "c"), complete=True):
    return {"summary": "원본과 주변 사진에 보이는 색을 비교할 수 있어요.", "complete": complete,
        "groups": [{"id": "g", "title": "빨간 장면", "reason": "각 사진에서 빨간색이 보입니다.",
                    "photo_ids": list(ids)}] if ids else []}


def request():
    return RunRequest(role="context", photo_ids=["a"])


def test_initial_time_neighborhood_is_only_candidate_acquisition_not_grouping_or_inspection(store):
    from datetime import datetime, timedelta, timezone
    source_time = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    for index in range(60):
        store.upsert(PhotoAsset(id=f"early-{index:02}",device_id="d",version="v1",width=1,height=1,
            captured_at=source_time-timedelta(days=100+index),time_source="media_store"))
    for pid, offset in [("a",0),("b",60),("c",120)]:
        value=store.photo(pid).model_copy(update={"version":"dated", "captured_at":source_time+timedelta(seconds=offset), "time_source":"media_store"})
        store.upsert(value)
    tools=ContextTools(store,None,request(),"neighborhood-prior")
    page=tools.initial_catalog()
    assert [p["photo_id"] for p in page["photos"][:3]]==["a","b","c"]
    assert len(page["photos"])==40 and len(tools.catalog_seen)==40
    assert {"b","c"}.issubset(tools.acquired)
    assert not tools.full_seen and tools.result is None and tools.plan is None
    assert not store.rows("SELECT * FROM events WHERE kind IN ('context_result','context_proposal')")


def observation_plan(ids=("b", "c")):
    return {"source_observation": "원본 전체에서 빨간색이 보입니다.", "investigations": [
        {"question": "다른 사진에서 이 색이 어떤 모습으로 보이는가?", "evidence_needed": "후보 전체 이미지를 확인한다.",
         "candidate_photo_ids": list(ids)}]}


class WordingGateway:
    def __init__(self, mode="supported"):
        self.mode, self.calls = mode, 0
        self.checked_images = []

    async def invoke(self, messages, schemas):
        self.calls += 1
        assert [s["name"] for s in schemas] == ["submit_context_wording_review"]
        content = messages[1].content
        self.checked_images.append(sum(block["type"] == "image" for block in content))
        assert "observation_plan" not in encoded(content) and "context_scope_reason" not in encoded(content)
        fields = json.loads(content[-1]["text"])["final_fields_to_check"]
        schema = schemas[0]["input_schema"]
        assert schema["$defs"]["ContextWordingCheck"]["properties"]["path"]["enum"] == [field["path"] for field in fields]
        assert schema["properties"]["checks"]["minItems"] == schema["properties"]["checks"]["maxItems"] == len(fields)
        checks = [{"path":field["path"], "readable": True, "claims_supported": True,
                   "reason":"사진과 정확한 문구 범위를 확인했습니다.", "problematic_excerpts": []} for field in fields]
        if self.mode in ("readability", "claim"):
            checks[0]["readable" if self.mode == "readability" else "claims_supported"] = False
            checks[0]["problematic_excerpts"] = [fields[0]["text"]]
        if self.mode == "missing":
            checks.pop()
        if self.mode == "duplicate":
            checks[-1] = checks[0]
        if self.mode == "foreign":
            checks[0]["path"] = "/private/unknown"
        if self.mode == "wrong_excerpt":
            checks[0]["problematic_excerpts"] = ["This does not occur in this field"]
        if self.mode == "missing_excerpt":
            checks[0]["readable"] = False
        if self.mode == "invalid_schema":
            del checks[0]["reason"]
        if self.mode == "no_tool":
            return AIMessage(content="untrusted provider text that must not enter diagnostics")
        return AIMessage(content="", tool_calls=[{"id":f"wording-{self.calls}", "type":"tool_call",
            "name":"private_unknown_tool" if self.mode == "wrong_tool" else "submit_context_wording_review", "args":{"checks":checks}}],
            response_metadata={"model_name":CONTEXT_WORDING_MODEL})


class PhotoContextAgent(ProductionPhotoContextAgent):
    """Tests inject both gateways explicitly; no external model is ever called."""
    def __init__(self, store, models, gateway, *, wording_gateway=None):
        super().__init__(store, models, gateway, wording_gateway=wording_gateway or WordingGateway())


class ImageGateway:
    """A fixture judge reads image pixels, never trusts proposed membership wording."""
    def __init__(self, ids=("b", "c"), *, invalid_review=None, empty=False, mutation=None):
        self.ids, self.invalid_review, self.empty, self.mutation = ids, invalid_review, empty, mutation
        self.turns = self.reviews = self.calls = 0
        self.review_images = []

    async def invoke(self, messages, schemas):
        self.calls += 1
        if schemas[0]["name"] == "submit_context_review":
            self.reviews += 1
            content = messages[1].content
            assert "analysis" not in encoded(content)
            images = [b for b in content if b.get("type") == "image"]
            self.review_images.append(len(images))
            pixels = []
            for block in images:
                with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as picture:
                    pixels.append(picture.getpixel((20, 20)))
            proposal = json.loads(content[-1]["text"])["proposed_context"]
            members = [dict(group_id=g["id"], photo_id=pid,
                verdict="supported" if pixels[1 + sorted(self.ids).index(pid)][0] > 200 else "rejected",
                reason="실제 사진의 색을 확인했습니다.") for g in proposal["groups"] for pid in g["photo_ids"]]
            if self.invalid_review == "missing" and members:
                members.pop()
            if self.invalid_review == "foreign" and members:
                members[0]["photo_id"] = "foreign"
            args = dict(summary_supported=self.invalid_review != "summary", summary_reason="원본을 확인했습니다.",
                        summary_problematic_excerpts=[proposal["summary"]] if self.invalid_review == "summary" else [],
                        members=members, empty_supported=self.empty,
                        context_scope_supported=self.invalid_review != "scope", context_scope_reason="계획과 전체 관찰을 확인했습니다.")
            name = "submit_context_review"
            if self.mutation:
                self.mutation()
                self.mutation = None
        else:
            self.turns += 1
            if self.turns == 1:
                assert "explicit_initial_catalog" in encoded([m.content for m in messages])
                return AIMessage(content="", tool_calls=[
                    {"name": "plan_photo_context", "id": f"plan-{self.calls}", "type": "tool_call", "args": observation_plan(self.ids)}])
            else:
                args, name = context(() if self.empty else self.ids), "submit_photo_context"
        return AIMessage(content="", tool_calls=[{"id": str(self.calls), "type": "tool_call", "name": name, "args": args}])


@pytest.mark.asyncio
async def test_context_uses_outside_connect_candidates_and_independent_images(store):
    store.write("INSERT INTO spaces VALUES(?,?)", ("historical", encoded({"id": "historical", "items": []})))
    before = store.spaces()
    gateway = ImageGateway()
    result = await GraphAgentRunner(store, None, gateway,
        context_agent=PhotoContextAgent(store, None, gateway)).execute("context-test", request())
    assert {k:v for k,v in result.items() if k != "evidence"} == context() and gateway.review_images == [3]
    assert result["evidence"]["inspected_photo_ids"] == ["a", "b", "c"]
    assert store.spaces() == before
    assert not store.rows("SELECT * FROM events WHERE kind IN ('results','space_candidate_proposal')")
    evidence = json.loads(store.rows("SELECT data FROM events WHERE kind='context_acquisition'")[-1]["data"])
    assert set(evidence["inspected"]) == {"a", "b", "c"}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "incomplete", "rejected"])
async def test_incomplete_seventh_response_uses_reserved_repair_without_bypassing_review(store, outcome):
    class IncompleteUntilRepair(ImageGateway):
        planning_calls = 0

        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                return await super().invoke(messages, schemas)
            self.planning_calls += 1
            progress = json.loads(messages[-2].content)["observation_progress"]
            assert progress["source_photo_id_not_allowed_as_member"] == "a"
            if self.planning_calls == 1:
                assert progress["fully_inspected_other_photo_ids"] == []
                return await super().invoke(messages, schemas)
            assert progress["fully_inspected_other_photo_ids"] == ["b", "c"]
            assert progress["planned_photo_ids_still_needing_full_inspection"] == []
            if self.planning_calls < 7:
                return AIMessage(content="검토 중")
            assert not progress["observation_tools_available"]
            if self.planning_calls == 8:
                assert "incomplete proposal has not been published" in encoded([m.content for m in messages])
            return AIMessage(content="", tool_calls=[{"id": f"submit-{self.planning_calls}",
                "type": "tool_call", "name": "submit_photo_context",
                "args": context(complete=self.planning_calls == 8 and outcome != "incomplete")}])

    gateway = IncompleteUntilRepair(invalid_review="summary" if outcome == "rejected" else None)
    wording = WordingGateway()
    agent = PhotoContextAgent(store, None, gateway, wording_gateway=wording)
    if outcome == "rejected":
        with pytest.raises(RuntimeError, match="within budget"):
            await agent.execute("incomplete-repair", request())
    else:
        result = await agent.execute("incomplete-repair", request())
        assert result["complete"] == (outcome == "complete")
        assert ("evidence" in result) == (outcome == "complete")
    assert gateway.planning_calls == 8
    assert gateway.reviews == wording.calls == (0 if outcome == "incomplete" else 1)
    assert len(store.rows("SELECT * FROM events WHERE kind='context_incomplete_repair'")) == 1
    assert len(store.rows("SELECT * FROM events WHERE kind='context_result'")) == (outcome == "complete")


@pytest.mark.asyncio
async def test_membership_failure_returns_exact_observed_ids_without_silently_editing_proposal(store):
    class RecoveringGateway(ImageGateway):
        async def invoke(self, messages, schemas):
            response = await super().invoke(messages, schemas)
            if schemas[0]["name"] != "submit_context_review":
                if self.turns == 2:
                    return AIMessage(content="", tool_calls=[{"id": "invalid-source", "type": "tool_call",
                        "name": "submit_photo_context", "args": context(("a",))}])
                if self.turns == 3:
                    diagnostic = next(json.loads(m.content) for m in messages
                        if getattr(m, "tool_call_id", None) == "invalid-source")
                    assert diagnostic["validation_error"] == "member_is_source"
                    assert diagnostic["source_photo_id"] == "a"
                    assert diagnostic["allowed_submission_photo_ids"] == ["b", "c"]
                    assert diagnostic["unresolved_planned_photo_ids"] == []
            return response
    gateway = RecoveringGateway()
    result = await PhotoContextAgent(store, None, gateway).execute("exact-membership-repair", request())
    assert result["groups"] == context()["groups"]
    assert gateway.reviews == 1
    proposals = store.rows("SELECT data FROM events WHERE run_id='exact-membership-repair' AND kind='context_proposal'")
    assert len(proposals) == 1 and json.loads(proposals[0]["data"])["groups"] == context()["groups"]


@pytest.mark.asyncio
async def test_progress_reflects_images_observed_by_the_declared_plan_before_submission(store):
    class PlanThenSubmit(ImageGateway):
        planning_calls = 0

        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                return await super().invoke(messages, schemas)
            self.planning_calls += 1
            progress = json.loads(messages[-2].content)["observation_progress"]
            if self.planning_calls == 1:
                name, args = "plan_photo_context", observation_plan()
            else:
                assert self.planning_calls == 2
                assert progress["planned_photo_ids_still_needing_full_inspection"] == []
                assert progress["fully_inspected_other_photo_ids"] == ["b", "c"]
                plan_output = next(m.content for m in messages if getattr(m, "tool_call_id", None) == "1")
                assert sum(block["type"] == "image" for block in plan_output) == 2
                assert json.loads(plan_output[0]["text"])["newly_observed_photo_ids"] == ["b", "c"]
                name, args = "submit_photo_context", context()
            return AIMessage(content="", tool_calls=[{"id": str(self.planning_calls), "type": "tool_call",
                "name": name, "args": args}])
    gateway = PlanThenSubmit()
    result = await PhotoContextAgent(store, None, gateway).execute("progress", request())
    assert result["complete"] and gateway.planning_calls == 2 and gateway.reviews == 1


@pytest.mark.asyncio
async def test_one_red_member_cannot_substantiate_a_group_containing_blue(store):
    payload = io.BytesIO()
    Image.new("RGB", (100, 100), "blue").save(payload, "JPEG")
    store.put_image("c", payload.getvalue())
    gateway = ImageGateway()
    with pytest.raises(RuntimeError, match="failed independent review"):
        await PhotoContextAgent(store, None, gateway).execute("false-universal", request())
    assert gateway.reviews == 2 and gateway.review_images == [3, 3]
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "foreign", "summary", "scope"])
async def test_bad_member_coverage_and_unsupported_summary_cannot_be_ready(store, mode):
    with pytest.raises(RuntimeError):
        await PhotoContextAgent(store, None, ImageGateway(invalid_review=mode)).execute("bad-review", request())
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


@pytest.mark.asyncio
async def test_valid_empty_requires_full_image_inspection_and_independent_review(store):
    gateway = ImageGateway(empty=True)
    result = await PhotoContextAgent(store, None, gateway).execute("empty", request())
    assert {k:v for k,v in result.items() if k != "evidence"} == context(()) and gateway.review_images == [3]
    tools = ContextTools(store, None, request(), "missing-images")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan(("b",)))
    with pytest.raises(ValueError, match="every planned candidate|every candidate"):
        tools.submit_photo_context(PhotoContext.model_validate(context(())))


def test_context_rejects_unacquired_uninspected_source_and_foreign_members(store):
    tools = ContextTools(store, None, request(), "authorization")
    with pytest.raises(ValueError, match="Acquire"):
        tools.image_block("b")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan(()))
    for ids in [("b",), ("a",), ("foreign",)]:
        with pytest.raises(ValueError):
            tools.submit_photo_context(PhotoContext.model_validate(context(ids)))
    assert "read_spaces" not in tools.definitions and "submit_space_proposal" not in tools.definitions


@pytest.mark.asyncio
async def test_gallery_mutation_during_review_invalidates_context(store):
    gateway = ImageGateway(mutation=store.bump)
    with pytest.raises(ValueError, match="Gallery changed"):
        await PhotoContextAgent(store, None, gateway).execute("mutated", request())
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


class ContextRunner:
    def __init__(self, result=None, fail=False, mutate=None, store=None):
        self.calls, self.fail, self.mutate = 0, fail, mutate
        self.result = context() if result is None else result
        self.store = store

    async def execute(self, rid, req):
        self.calls += 1
        await asyncio.sleep(.01)
        if self.mutate:
            self.mutate()
        if self.fail:
            raise RuntimeError("controlled context failure")
        if not self.store or not self.result["complete"]:
            return self.result
        ids = [p.id for p in self.store.photos()]
        return {**self.result, "evidence": {"gallery_revision": self.store.revision,
            "source_version": self.store.photo(req.photo_ids[0]).version, "inspected_photo_ids": ids,
            "photo_versions": {p.id:p.version for p in self.store.photos()}, "summary_reviewed": True,
            "reviewed_members": [{"group_id":g["id"], "photo_id":pid} for g in self.result["groups"] for pid in g["photo_ids"]],
            "planned_photo_ids": [pid for pid in ids if pid != req.photo_ids[0]],
            "wording_review_model": CONTEXT_WORDING_MODEL, "wording_reviewed": True,
            "wording_checked_paths": [field["path"] for field in context_wording_fields(self.result)]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("ids,expected", [(("b", "c"), "ready"), ((), "empty")])
async def test_durable_context_preparation_deduplicates_and_reads_without_work(store, ids, expected):
    runner = ContextRunner(context(ids), store=store)
    service = RunService(store, runner)
    assert service.context_ready("a")["state"] == "pending"
    first = service.prepare_context("a")
    assert first["state"] == "running"
    assert service.prepare_context("a")["run_id"] == first["run_id"]
    await service.tasks[first["run_id"]]
    before = store.db.total_changes
    for _ in range(10):
        result = service.context_ready("a")
        assert result["state"] == expected and "complete" not in result["context"]
    assert store.db.total_changes == before and runner.calls == 1
    before_runs = len(store.rows("SELECT id FROM runs"))
    assert service.prepare_context("a")["run_id"] is None
    assert len(store.rows("SELECT id FROM runs")) == before_runs


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failure", "incomplete", "mutation", "foreign"])
async def test_failures_are_not_empty_or_cached(store, mode):
    runner = ContextRunner(context(complete=False) if mode == "incomplete" else
        context(("foreign",)) if mode == "foreign" else None,
        fail=mode == "failure", mutate=store.bump if mode == "mutation" else None)
    service = RunService(store, runner)
    run = service.start(request())
    await service.tasks[run["id"]]
    status = service.context_ready("a")
    assert status["state"] == ("pending" if mode == "mutation" else "failed")
    assert status["context"] is None and not store.rows("SELECT * FROM cache")
    assert service.get(run["id"])["status"] in ("failed", "incomplete")


@pytest.mark.asyncio
async def test_context_model_revision_and_deleted_member_invalidate_readiness(store, monkeypatch):
    service = RunService(store, ContextRunner(store=store))
    run = service.start(request())
    await service.tasks[run["id"]]
    assert service.context_ready("a")["state"] == "ready"
    old_model = __import__("os").environ.get("CG_MODEL")
    monkeypatch.setenv("CG_MODEL", "another-model")
    assert service.context_ready("a")["state"] == "pending"
    if old_model is None:
        monkeypatch.delenv("CG_MODEL")
    else:
        monkeypatch.setenv("CG_MODEL", old_model)
    store.delete("b")
    assert service.context_ready("a")["state"] == "pending"


@pytest.mark.asyncio
async def test_restart_recovers_current_context_and_cancels_stale_snapshot(store):
    service = RunService(store, ContextRunner(store=store))
    run = service.start(request())
    await service.stop(preserve_pending=True)
    # stop before coroutine begins retains a durable queued row.
    resumed = RunService(store, ContextRunner(store=store))
    await resumed.recover()
    await asyncio.gather(*list(resumed.tasks.values()))
    assert resumed.context_ready("a")["state"] == "ready"
    store.bump()
    store.write("UPDATE runs SET status='queued' WHERE id=?", (run["id"],))
    await resumed.recover()
    assert resumed.get(run["id"])["status"] == "cancelled" and not resumed.tasks


def test_fixture_capture_provenance_and_calendar_boundaries():
    value = dict(id="a", device_id="synthetic-demo", version="1", width=10, height=10,
                 time_source="demo_fixture", captured_at="2026-09-01T18:00:00+00:00")
    fixture = PhotoAsset(**value)
    assert capture_metadata(fixture)["date"] == "2026-09-02"
    assert capture_metadata(fixture)["source"] == "demo_fixture"
    for change in ({"device_id": "real-phone"}, {"captured_at": None}, {"captured_at": "2026-09-01T12:00:00"}):
        with pytest.raises(ValidationError):
            PhotoAsset(**{**value, **change})
    assert capture_metadata(asset(source="modified")) is None


@pytest.mark.parametrize("live", [True, False])
def test_context_endpoint_session_scope_readonly_and_prepare_boundary(tmp_path, monkeypatch, live):
    monkeypatch.delenv("CG_SERVER_TOKEN", raising=False)
    demo = DemoSession(secrets.token_urlsafe(32), live_enabled=live)
    key = demo.launch_key
    runner = ContextRunner(context(()))
    app = create_app(tmp_path, lambda s: runner, demo=demo, recover_runs=False)
    app.state.store.upsert(asset())
    with TestClient(app, base_url=demo.origin) as client:
        assert client.get("/assets/a/context").status_code == 401
        client.post("/demo/session", json={"key": key}, headers={"Origin": demo.origin})
        before = app.state.store.db.total_changes
        assert client.get("/assets/a/context").json()["state"] == "pending"
        assert before == app.state.store.db.total_changes and runner.calls == 0
        response = client.post("/assets/a/context/prepare", headers={"Origin": demo.origin})
        assert response.status_code == (200 if live else 403)
        assert client.post("/assets/a/context/prepare", headers={"Origin": "https://external.invalid"}).status_code == 403
        assert client.get("/spaces").status_code == 401
        assert client.get("/assets/foreign/context").status_code == 400


def test_context_schema_rejects_duplicate_ids_and_excess_members():
    for value in [context(("b", "b")), context(tuple(str(i) for i in range(25))),
                  {**context(), "groups": [*context()["groups"], *context()["groups"]]}]:
        with pytest.raises(ValidationError):
            PhotoContext.model_validate(value)


def test_candidate_crop_does_not_count_as_full_photo_inspection(store):
    tools = ContextTools(store, None, request(), "crop-only")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan(()))
    tools.image_block("b", Box(x=0, y=0, width=.1, height=.1))
    assert "b" in tools.seen and "b" not in tools.full_seen
    with pytest.raises(ValueError) as error:
        tools.submit_photo_context(PhotoContext.model_validate(context(("b",))))
    assert tool_validation_diagnostic(error.value)["code"] == "member_not_fully_inspected"
    tools.image_block("b")
    tools.submit_photo_context(PhotoContext.model_validate(context(("b",))))


@pytest.mark.parametrize("channel", ["search_visual", "search_text", "search_faces", "search_time", "search_location"])
def test_explicit_search_acquires_candidates_outside_initial_catalog(store, monkeypatch, channel):
    tools = ContextTools(store, None, request(), "search-acquisition")
    tools.image_block("a")
    payloads = {
        "search_visual": ({"query": "observed"}, {"candidates": [{"photo_id": "b"}]}),
        "search_text": ({"query": "observed"}, {"literal": [{"photo_id": "b"}], "semantic": [{"photo_id": "c"}]}),
        "search_faces": ({"photo_id": "a"}, {"candidates": [{"photo_id": "b"}]}),
        "search_time": ({"start": "2010-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
                        {"candidates": [{"photo_id": "b"}]}),
        "search_location": ({"latitude": 0, "longitude": 0, "radius_km": 10}, {"candidates": [{"photo_id": "b"}]}),
    }
    args, found = payloads[channel]
    monkeypatch.setattr(tools, channel, lambda args: found)
    assert "b" not in tools.acquired
    tools.invoke(channel, args)
    tools.invoke("plan_photo_context", observation_plan(("b",)))
    tools.image_block("b")
    tools.submit_photo_context(PhotoContext.model_validate(context(("b",))))
    assert tools.result["groups"][0]["photo_ids"] == ["b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["uninspected", "missing_review", "duplicate_review", "foreign_inspected", "version", "revision", "summary"])
async def test_context_cache_provenance_is_required_after_run_history_is_removed(store, tamper):
    service = RunService(store, ContextRunner(store=store))
    run = service.start(request())
    await service.tasks[run["id"]]
    key = service.cache_key(request())
    cached = store.cache_get(key)
    if tamper == "uninspected":
        cached["evidence"]["inspected_photo_ids"].remove("b")
        del cached["evidence"]["photo_versions"]["b"]
    elif tamper == "missing_review":
        cached["evidence"]["reviewed_members"].pop()
    elif tamper == "duplicate_review":
        cached["evidence"]["reviewed_members"][1] = cached["evidence"]["reviewed_members"][0]
    elif tamper == "foreign_inspected":
        cached["evidence"]["inspected_photo_ids"].append("foreign")
        cached["evidence"]["photo_versions"]["foreign"] = "1"
    elif tamper == "version":
        cached["evidence"]["photo_versions"]["b"] = "obsolete"
    elif tamper == "revision":
        cached["evidence"]["gallery_revision"] -= 1
    else:
        cached["evidence"]["summary_reviewed"] = False
    store.cache_put(key, cached)
    store.write("DELETE FROM runs")
    store.write("DELETE FROM events")
    before = store.db.total_changes
    assert service.context_ready("a")["state"] == "pending"
    assert before == store.db.total_changes


@pytest.mark.asyncio
async def test_unproven_completed_result_is_failed_before_persisting_completed_status(store):
    service = RunService(store, ContextRunner())  # Deliberately no actual inspection/review provenance.
    run = service.start(request())
    await service.tasks[run["id"]]
    assert service.get(run["id"])["status"] == "failed"
    assert service.context_ready("a")["state"] == "failed"
    assert not store.rows("SELECT * FROM cache")


def test_fixture_time_is_searchable_without_being_a_real_capture_claim(store):
    fixture = PhotoAsset(id="fixture", device_id="synthetic-demo", version="1", width=10, height=10,
                         time_source="demo_fixture", captured_at="2026-09-01T18:00:00Z")
    store.upsert(fixture)
    tools = ContextTools(store, None, request(), "fixture-search")
    result = tools.invoke("search_time", {"start": "2026-09-02T00:00:00+09:00", "end": "2026-09-02T23:59:59+09:00"})
    assert [r["photo_id"] for r in result["candidates"]] == ["fixture"]
    assert result["candidates"][0]["time_source"] == "demo_fixture"
    assert "fixture" in tools.acquired


@pytest.mark.asyncio
async def test_context_messages_serialize_through_real_anthropic_sdk_without_network(store):
    class SerializingGateway(ImageGateway):
        async def invoke(self, messages, schemas):
            transport = ChatAnthropic(model="serialization-fixture", api_key="test-only-key")
            payload = transport._get_request_payload(messages)
            assert payload["messages"] and payload.get("system")
            transport.bind_tools(schemas)  # Also validate actual tool-schema conversion.
            return await super().invoke(messages, schemas)
    gateway = SerializingGateway()
    result = await PhotoContextAgent(store, None, gateway).execute("sdk-serialization", request())
    assert result["complete"] is True and gateway.reviews == 1


@pytest.mark.asyncio
async def test_context_model_error_persists_only_controlled_classifier(store):
    class Failure:
        async def invoke(self, messages, schemas):
            raise RuntimeError("Model unavailable (ValueError)")
    with pytest.raises(RuntimeError, match="Context model unavailable"):
        await PhotoContextAgent(store, None, Failure()).execute("transport-failure", request())
    event = json.loads(store.rows("SELECT data FROM events WHERE kind='context_model_error'")[0]["data"])
    assert event == {"stage": "context_plan", "error_type": "RuntimeError", "upstream_error_type": "ValueError"}


@pytest.mark.parametrize("corrupt", [42, ["bad"], "bad", {"kind": "photo_context"}])
def test_corrupt_cache_container_is_pending_without_server_error_or_mutation(store, corrupt):
    service = RunService(store, ContextRunner())
    store.cache_put(service.cache_key(request()), corrupt)
    before = store.db.total_changes
    assert service.context_ready("a")["state"] == "pending"
    assert store.db.total_changes == before


@pytest.mark.asyncio
async def test_final_submission_format_repair_preserves_inspected_candidates_and_review(store):
    class PlainUntilRepair(ImageGateway):
        planning_calls = 0

        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                return await super().invoke(messages, schemas)
            self.planning_calls += 1
            if self.planning_calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"id": "plan", "type": "tool_call", "name": "plan_photo_context", "args": observation_plan()},
                    {"id": "inspect", "type": "tool_call", "name": "inspect_photos", "args": {"photo_ids": ["b", "c"]}}])
            if self.planning_calls < 8:
                return AIMessage(content="작성한 맥락을 제출할 예정입니다.")
            assert [s["name"] for s in schemas] == ["submit_photo_context"]
            assert "fully_inspected_other_photo_ids" in encoded([m.content for m in messages])
            return AIMessage(content="", tool_calls=[{"id": "submit", "type": "tool_call",
                "name": "submit_photo_context", "args": context()}])
    gateway = PlainUntilRepair()
    result = await PhotoContextAgent(store, None, gateway).execute("final-format-repair", request())
    assert result["complete"] and gateway.planning_calls == 8 and gateway.reviews == 1
    shapes = [json.loads(r["data"]) for r in store.rows("SELECT data FROM events WHERE kind='context_response_shape'")]
    assert len(shapes) == 8 and shapes[-1]["final_repair"]


@pytest.mark.asyncio
async def test_unavailable_final_tool_and_invalid_arguments_have_safe_diagnostics(store):
    class InvalidGateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls < 8:
                return AIMessage(content="", tool_calls=[{"id": str(self.calls), "type": "tool_call",
                    "name": "submit_photo_context", "args": {"summary": "summary", "groups": {"secret-id": []}}}])
            assert [s["name"] for s in schemas] == ["submit_photo_context"]
            return AIMessage(content="", tool_calls=[{"id": "unavailable", "type": "tool_call",
                "name": "inspect_photos", "args": {"photo_ids": ["secret-id"]}}])
    with pytest.raises(RuntimeError, match="within budget"):
        await PhotoContextAgent(store, None, InvalidGateway()).execute("invalid-submission", request())
    events = [json.loads(r["data"]) for r in store.rows("SELECT data FROM events WHERE kind='context_tool_validation'")]
    assert len(events) == 8
    assert events[0]["code"] == "invalid_schema" and "missing" in events[0]["issue_types"]
    assert events[-1]["code"] == "tool_not_available"
    assert "secret-id" not in encoded(events)
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


def test_context_v2_length_limits_do_not_change_connect_group_contract():
    group = context()["groups"][0]
    assert ResultGroup.model_validate({**group, "reason": "x" * 500})
    for value in [{**context(), "summary": "x" * 251},
                  {**context(), "groups": [{**group, "reason": "x" * 241}]},
                  {**context(), "groups": [{**group, "title": "x" * 81}]}]:
        with pytest.raises(ValidationError):
            PhotoContext.model_validate(value)


def test_context_plan_requires_source_observation_and_acquired_candidate_ids(store):
    tools = ContextTools(store, None, request(), "plan-required")
    with pytest.raises(ValueError, match="full source"):
        tools.invoke("plan_photo_context", observation_plan())
    tools.image_block("a")
    with pytest.raises(ValueError, match="explicitly acquired"):
        tools.invoke("plan_photo_context", observation_plan())
    tools.invoke("list_photos", {})
    tools.invoke("inspect_photos", {"photo_ids": ["b", "c"]})
    with pytest.raises(ValueError, match="observation plan"):
        tools.submit_photo_context(PhotoContext.model_validate(context()))
    tools.invoke("plan_photo_context", observation_plan())
    tools.submit_photo_context(PhotoContext.model_validate(context()))
    assert len(store.rows("SELECT * FROM events WHERE kind='context_observation_plan'")) == 1


def test_context_choice_schemas_follow_acquisition_full_inspection_and_current_scope(store):
    tools = ContextTools(store, None, request(), "schema-choices")
    tools.image_block("a")

    def fields():
        schemas = {tool["name"]: tool["input_schema"] for tool in tools.schemas()}
        return (schemas["plan_photo_context"]["$defs"]["ContextInvestigation"]["properties"]["candidate_photo_ids"],
                schemas["submit_photo_context"]["$defs"]["ContextGroup"]["properties"]["photo_ids"], schemas)

    initial_plan, initial_submit, initial_schemas = fields()
    assert initial_plan["maxItems"] == initial_submit["maxItems"] == 0
    assert "enum" not in initial_plan["items"]
    assert initial_schemas["submit_photo_context"]["properties"]["groups"]["maxItems"] == 0
    tools.invoke("list_photos", {"offset": 1, "limit": 1})
    plan, submit, _ = fields()
    assert plan["items"]["enum"] == ["b"] and submit["maxItems"] == 0
    tools.image_block("b", Box(x=0, y=0, width=.2, height=.2))
    assert fields()[1]["maxItems"] == 0  # A crop is never whole-photo context evidence.
    tools.image_block("b")
    plan, submit, schemas = fields()
    assert submit["items"]["enum"] == ["b"]
    assert schemas["submit_photo_context"]["properties"]["groups"]["maxItems"] == 8
    assert initial_plan["maxItems"] == 0 and "enum" not in initial_plan["items"]  # No schema object reuse.
    tools.allowed = lambda: {"a", "c"}
    assert fields()[0]["maxItems"] == fields()[1]["maxItems"] == 0
    assert tools.validation_feedback({"code": "unknown_photo"})["allowed_submission_photo_ids"] == []


def test_context_schema_hints_do_not_replace_runtime_source_and_acquisition_guards(store):
    tools = ContextTools(store, None, request(), "schema-enforcement")
    tools.image_block("a")
    with pytest.raises(ValueError) as error:
        tools.invoke("plan_photo_context", observation_plan(("a",)))
    assert tool_validation_diagnostic(error.value)["code"] == "planned_candidate_is_source"
    with pytest.raises(ValueError) as error:
        tools.invoke("plan_photo_context", observation_plan(("b",)))
    assert tool_validation_diagnostic(error.value)["code"] == "planned_candidate_not_acquired"
    tools.invoke("plan_photo_context", observation_plan(()))
    for pid, code in [("a", "member_is_source"), ("b", "member_not_acquired"), ("unknown", "unknown_photo")]:
        with pytest.raises(ValueError) as error:
            tools.invoke("submit_photo_context", context((pid,)))
        assert tool_validation_diagnostic(error.value)["code"] == code
    tools.invoke("list_photos", {})
    with pytest.raises(ValueError) as error:
        tools.invoke("submit_photo_context", context(("b",)))
    assert tool_validation_diagnostic(error.value)["code"] == "member_not_fully_inspected"


def test_known_schema_validator_codes_and_unknown_errors_do_not_include_payloads(store):
    tools = ContextTools(store, None, request(), "safe-errors")
    for tool, args, expected in [
        ("search_time", {"start": "2026-01-01", "end": "2026-01-02"}, "time_timezone_missing"),
        ("search_time", {"start": "2026-01-02T00:00:00Z", "end": "2026-01-01T00:00:00Z"}, "time_window_reversed"),
        ("submit_photo_context", {**context(), "summary": " "}, "summary_blank"),
        ("submit_photo_context", {**context(), "groups": [context()["groups"][0], context()["groups"][0]]}, "duplicate_context_group_ids"),
        ("submit_photo_context", context(("b", "b")), "duplicate_context_member"),
    ]:
        with pytest.raises(ValidationError) as error:
            tools.invoke(tool, args)
        detail = tool_validation_diagnostic(error.value)
        assert detail["code"] == expected and detail["validation_codes"] == [expected]
        assert "input_value" not in encoded(detail) and "Value error" not in encoded(detail)
    detail = tool_validation_diagnostic(ValueError("provider secret body must not be logged"))
    assert detail["code"] == "unclassified_tool_validation" and "secret" not in encoded(detail)


@pytest.mark.asyncio
async def test_source_in_plan_and_missing_plan_receive_distinct_actionable_feedback(store):
    class PlanRepairGateway(ImageGateway):
        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                return await super().invoke(messages, schemas)
            self.turns += 1
            feedback = [json.loads(message.content) for message in messages if message.type == "tool"
                        and isinstance(message.content, str) and '"validation_error"' in message.content]
            if self.turns == 1:
                calls = [("plan_photo_context", observation_plan(("a", "b", "c"))),
                         ("inspect_photos", {"photo_ids": ["b", "c"]})]
            elif self.turns == 2:
                assert feedback[-1]["code"] == "planned_candidate_is_source"
                assert feedback[-1]["allowed_plan_candidate_photo_ids"] == ["b", "c"]
                assert feedback[-1]["observation_plan_recorded"] is False
                calls = [("submit_photo_context", context())]
            else:
                assert self.turns == 3 and feedback[-1]["code"] == "observation_plan_missing"
                assert feedback[-1]["allowed_submission_photo_ids"] == ["b", "c"]
                calls = [("plan_photo_context", observation_plan()), ("submit_photo_context", context())]
            return AIMessage(content="", tool_calls=[{"id": f"{self.turns}-{index}", "type": "tool_call",
                "name": name, "args": args} for index, (name, args) in enumerate(calls)])

    gateway = PlanRepairGateway()
    result = await PhotoContextAgent(store, None, gateway).execute("plan-feedback", request())
    assert result["complete"] and gateway.turns == 3 and gateway.reviews == 1
    assert result["evidence"]["planned_photo_ids"] == ["b", "c"]
    diagnostics = [json.loads(row["data"]) for row in store.rows("SELECT data FROM events WHERE kind='context_tool_validation'")]
    assert [row["code"] for row in diagnostics] == ["planned_candidate_is_source", "observation_plan_missing"]


def test_dynamic_context_id_schemas_serialize_in_actual_sdk_without_network(store):
    from langchain_core.messages import HumanMessage, SystemMessage
    tools = ContextTools(store, None, request(), "id-schema-sdk")
    tools.image_block("a")
    transport = ChatAnthropic(model=CONTEXT_WORDING_MODEL, api_key="test-only-key")
    for observed in (False, True):
        if observed:
            tools.invoke("list_photos", {})
            tools.image_block("b")
        bound = transport.bind_tools(tools.schemas())
        payload = transport._get_request_payload([SystemMessage(content="test"), HumanMessage(content="test")], **bound.kwargs)
        schemas = {tool["name"]: tool["input_schema"] for tool in payload["tools"]}
        if observed:
            assert '"enum": ["b", "c"]' in json.dumps(schemas["plan_photo_context"])
            assert '"enum": ["b"]' in json.dumps(schemas["submit_photo_context"])
        else:
            assert schemas["submit_photo_context"]["properties"]["groups"]["maxItems"] == 0


@pytest.mark.asyncio
async def test_scope_review_can_trigger_agent_chosen_additional_inspection(store):
    class ScopeGateway(ImageGateway):
        planning_calls = 0
        scope_calls = 0

        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                self.scope_calls += 1
                self.ids = ("b",) if self.scope_calls == 1 else ("b", "c")
                response = await super().invoke(messages, schemas)
                if self.scope_calls == 1:
                    response.tool_calls[0]["args"]["context_scope_supported"] = False
                    response.tool_calls[0]["args"]["context_scope_reason"] = "계획의 추가 질문을 답하려면 c의 전체 사진 관찰이 필요합니다."
                return response
            self.planning_calls += 1
            if self.planning_calls in (1, 3):
                ids = ["b"] if self.planning_calls == 1 else ["c"]
                if self.planning_calls == 3:
                    assert "independent_context_review" in encoded([m.content for m in messages])
                return AIMessage(content="", tool_calls=[
                    {"id": f"plan-{self.planning_calls}", "type": "tool_call", "name": "plan_photo_context",
                     "args": observation_plan(ids)},
                    {"id": f"inspect-{self.planning_calls}", "type": "tool_call", "name": "inspect_photos",
                     "args": {"photo_ids": ids}}])
            return AIMessage(content="", tool_calls=[{"id": f"submit-{self.planning_calls}", "type": "tool_call",
                "name": "submit_photo_context", "args": context(("b",) if self.planning_calls == 2 else ("b", "c"))}])
    gateway = ScopeGateway()
    result = await PhotoContextAgent(store, None, gateway).execute("scope-expansion", request())
    assert result["groups"][0]["photo_ids"] == ["b", "c"]
    assert gateway.planning_calls == 4 and gateway.scope_calls == 2
    assert result["evidence"]["inspected_photo_ids"] == ["a", "b", "c"]


def test_submit_schema_offers_only_fully_inspected_other_photos(store):
    tools = ContextTools(store, None, request(), "inspected-enum")
    tools.initial_catalog()
    tools.image_block("a")
    tools.image_block("b")
    tools.image_block("c", Box(x=0, y=0, width=0.5, height=0.5))
    def offered():
        schema = next(s for s in tools.schemas() if s["name"] == "submit_photo_context")
        return schema["input_schema"]["$defs"]["ContextGroup"]["properties"]["photo_ids"]["items"]["enum"]
    assert offered() == ["b"]
    tools.image_block("c")
    assert offered() == ["b", "c"]
    assert tools.result is None  # Structural eligibility does not create a semantic group.


@pytest.mark.asyncio
@pytest.mark.parametrize("excerpts", [["빨간 장면"], [], [" "]])
async def test_summary_review_cannot_reject_without_own_exact_evidence(store, excerpts):
    class CrossFieldReview(ImageGateway):
        async def invoke(self, messages, schemas):
            response = await super().invoke(messages, schemas)
            if schemas[0]["name"] == "submit_context_review":
                response.tool_calls[0]["args"].update(summary_supported=False,
                    summary_problematic_excerpts=excerpts)
            return response
    gateway = CrossFieldReview()
    with pytest.raises(RuntimeError, match="complete structured evidence"):
        await PhotoContextAgent(store, None, gateway).execute("cross-field-summary", request())
    assert gateway.reviews == 2
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


def test_declared_observations_must_be_completed_or_explicitly_revised(store, monkeypatch):
    tools = ContextTools(store, None, request(), "plan-obligations")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    read = store.read_image
    def fail_c(pid, box=None):
        if pid == "c":
            raise FileNotFoundError("private file location must not be returned")
        return read(pid, box)
    monkeypatch.setattr(store, "read_image", fail_c)
    returned = tools.invoke("plan_photo_context", observation_plan())
    assert sum(block["type"] == "image" for block in returned) == 1
    detail = json.loads(returned[0]["text"])
    assert detail["status"] == "partial" and detail["unresolved_planned_photo_ids"] == ["c"]
    assert "private file" not in encoded(detail)
    with pytest.raises(ValueError, match="every planned candidate"):
        tools.submit_photo_context(PhotoContext.model_validate(context(("b",))))
    with pytest.raises(ValueError, match="Explain explicitly"):
        tools.invoke("plan_photo_context", observation_plan(("b",)))
    revised = {**observation_plan(("b",)), "revision_reason": "질문을 b의 관찰로 확인할 수 있는 범위로 명시적으로 좁힙니다."}
    tools.invoke("plan_photo_context", revised)
    tools.submit_photo_context(PhotoContext.model_validate(context(("b",))))
    assert tools.planned_ids() == {"b"}
    # This checks declared work; it does not mechanically label c irrelevant.
    assert "c" not in tools.full_seen and "c" in tools.acquired


def test_plan_returns_only_new_model_selected_full_images_and_preserves_repeated_observations(store, monkeypatch):
    tools = ContextTools(store, None, request(), "plan-images")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    reads, read = [], store.read_image
    def track(pid, box=None):
        reads.append((pid, box))
        return read(pid, box)
    monkeypatch.setattr(store, "read_image", track)
    first = tools.invoke("plan_photo_context", observation_plan(("b",)))
    metadata = json.loads(first[0]["text"])
    assert metadata["newly_observed_photo_ids"] == ["b"] and metadata["unresolved_planned_photo_ids"] == []
    assert json.loads(first[1]["text"])["photo_id"] == "b"
    with Image.open(io.BytesIO(base64.b64decode(first[2]["source"]["data"]))) as image:
        assert image.getpixel((20, 20))[0] > 200
    assert reads == [("b", None)] and tools.full_seen == {"a", "b"}
    repeated = tools.invoke("plan_photo_context", observation_plan(("b",)))
    assert repeated["status"] == "already_observed" and repeated["newly_observed_photo_ids"] == []
    assert reads == [("b", None)]
    expanded = tools.invoke("plan_photo_context", observation_plan(("b", "c")))
    assert json.loads(expanded[0]["text"])["newly_observed_photo_ids"] == ["c"]
    assert reads == [("b", None), ("c", None)] and tools.full_seen == {"a", "b", "c"}


@pytest.mark.parametrize("mutation,code", [("revision", "gallery_revision_changed"), ("deadline", "run_deadline_exceeded")])
def test_plan_does_not_count_an_image_whose_metadata_or_budget_changed_during_read(store, monkeypatch, mutation, code):
    tools = ContextTools(store, None, request(), "plan-image-mutation")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    read = store.read_image
    def change_during_read(pid, box=None):
        value = read(pid, box)
        if mutation == "revision":
            store.bump()
        else:
            tools.deadline = 0
        return value
    monkeypatch.setattr(store, "read_image", change_during_read)
    result = tools.invoke("plan_photo_context", observation_plan(("b",)))
    assert isinstance(result, dict) and result["status"] == "partial"
    assert result["observation_error"]["code"] == code
    assert result["unresolved_planned_photo_ids"] == ["b"]
    assert tools.full_seen == tools.seen == {"a"} and tools.planned_ids() == {"b"}
    with pytest.raises(ValueError):
        tools.invoke("submit_photo_context", context(("b",)))


def test_plan_preflights_entire_image_budget_before_replacing_plan_or_reading(store, monkeypatch):
    for index in range(23):
        store.upsert(asset(f"extra-{index:02}"))
    tools = ContextTools(store, None, request(), "plan-image-budget")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan(()))
    original = tools.plan.copy()
    candidates = sorted(tools.candidate_ids())
    assert len(candidates) == 25
    plan = observation_plan(candidates[:24])
    plan["investigations"].append({**plan["investigations"][0], "candidate_photo_ids": candidates[24:]})
    def unexpected_read(*args):
        raise AssertionError("Over-budget plans must not read an image")
    monkeypatch.setattr(store, "read_image", unexpected_read)
    with pytest.raises(ValueError, match="inspection budget"):
        tools.invoke("plan_photo_context", plan)
    assert tools.plan == original and tools.full_seen == {"a"}
    assert len(store.rows("SELECT * FROM events WHERE kind='context_observation_plan'")) == 1


@pytest.mark.asyncio
async def test_model_reads_partial_plan_images_then_retries_only_unresolved_observations(store, monkeypatch):
    read, failed = store.read_image, False
    def unavailable_once(pid, box=None):
        nonlocal failed
        if pid == "c" and not failed:
            failed = True
            raise FileNotFoundError("private path")
        return read(pid, box)
    monkeypatch.setattr(store, "read_image", unavailable_once)
    class RetryingPlanGateway(ImageGateway):
        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_context_review":
                return await super().invoke(messages, schemas)
            self.turns += 1
            if self.turns > 1:
                outputs = [m.content for m in messages if m.type == "tool" and isinstance(m.content, list)]
                current = outputs[-1]
                metadata = json.loads(current[0]["text"])
                assert metadata["newly_observed_photo_ids"] == (["b"] if self.turns == 2 else ["c"])
                assert metadata["status"] == ("partial" if self.turns == 2 else "observed")
                actual_images = [block for block in current if block["type"] == "image"]
                assert len(actual_images) == 1
                with Image.open(io.BytesIO(base64.b64decode(actual_images[0]["source"]["data"]))) as image:
                    assert image.getpixel((20, 20))[0] > 200
            name, args = ("plan_photo_context", observation_plan()) if self.turns < 3 else ("submit_photo_context", context())
            assert self.turns <= 3
            return AIMessage(content="", tool_calls=[{"id": f"retry-plan-{self.turns}", "type": "tool_call",
                "name": name, "args": args}])
    gateway = RetryingPlanGateway()
    result = await PhotoContextAgent(store, None, gateway).execute("plan-image-repair", request())
    assert gateway.turns == 3 and gateway.reviews == 1
    assert result["evidence"]["planned_photo_ids"] == ["b", "c"]
    assert result["evidence"]["inspected_photo_ids"] == ["a", "b", "c"]
    observations = [json.loads(row["data"]) for row in store.rows("SELECT data FROM events WHERE kind='context_plan_observation'")]
    assert [row["newly_observed_photo_ids"] for row in observations] == [["b"], ["c"]]
    assert "private path" not in encoded(observations)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("missing", {"code": "path_coverage_mismatch", "missing_path_count": 1, "duplicate_path_count": 0, "foreign_path_count": 0}),
    ("duplicate", {"code": "path_coverage_mismatch", "missing_path_count": 1, "duplicate_path_count": 1, "foreign_path_count": 0}),
    ("foreign", {"code": "path_coverage_mismatch", "missing_path_count": 1, "duplicate_path_count": 0, "foreign_path_count": 1}),
    ("wrong_excerpt", {"code": "excerpt_not_in_field", "excerpt_mismatch_count": 1, "failed_without_excerpt_count": 0}),
    ("invalid_schema", {"code": "invalid_schema", "schema_issue_count": 1, "issue_types": ["missing"]}),
    ("no_tool", {"code": "tool_call_count", "actual_tool_call_count": 0}),
    ("wrong_tool", {"code": "unexpected_tool"}),
])
async def test_copy_gate_requires_exactly_every_final_text_path_and_its_own_excerpt(store, mode, expected):
    wording = WordingGateway(mode)
    with pytest.raises(RuntimeError, match="exact-field evidence"):
        await PhotoContextAgent(store, None, ImageGateway(), wording_gateway=wording).execute("copy-contract", request())
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")
    rows = store.rows("SELECT * FROM events WHERE kind='context_wording_invalid'")
    assert len(rows) == wording.calls == 1
    detail = json.loads(rows[0]["data"])
    assert all(detail[key] == value for key, value in expected.items())
    assert detail["expected_field_count"] == 3
    for sensitive in ("private/unknown", "private_unknown_tool", "This does not occur", "untrusted provider text"):
        assert sensitive not in encoded(detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["readability", "claim", "missing_excerpt"])
async def test_supported_visual_members_do_not_bypass_final_wording_failure(store, mode):
    wording = WordingGateway(mode)
    gateway = ImageGateway()
    with pytest.raises(RuntimeError, match="failed independent review"):
        await PhotoContextAgent(store, None, gateway, wording_gateway=wording).execute("copy-failed", request())
    assert wording.calls == gateway.reviews == 2
    assert not store.rows("SELECT * FROM events WHERE kind='context_result'")


@pytest.mark.asyncio
@pytest.mark.parametrize("negative_flag", ["readable", "claims_supported"])
async def test_missing_excerpt_quotes_exact_whole_field_with_adapter_provenance_and_keeps_negative(store, negative_flag):
    class NegativeWithoutQuote(WordingGateway):
        async def invoke(self, messages, schemas):
            response = await super().invoke(messages, schemas)
            response.tool_calls[0]["args"]["checks"][0][negative_flag] = False
            self.original_response = response
            return response
    gateway = NegativeWithoutQuote()
    tools = ContextTools(store, None, request(), "quote-normalization")
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan())
    supported, feedback = await PhotoContextAgent(store, None, ImageGateway(), wording_gateway=gateway)._wording_review(tools, context(), 1)
    assert supported is False and feedback["checks"][0][negative_flag] is False
    assert feedback["checks"][0]["problematic_excerpts"] == [context()["summary"]]
    assert gateway.original_response.tool_calls[0]["args"]["checks"][0]["problematic_excerpts"] == []
    assert feedback["adapter_quote_provenance"] == {"normalization": "full_field_fallback", "paths": ["/summary"], "count": 1}
    rows = store.rows("SELECT data FROM events WHERE kind='context_wording_normalized'")
    assert len(rows) == gateway.calls == 1
    assert json.loads(rows[0]["data"]) == {"attempt": 1, **feedback["adapter_quote_provenance"]}
    assert not store.rows("SELECT * FROM events WHERE kind IN ('context_wording_invalid','context_result')")


@pytest.mark.asyncio
async def test_wrong_provided_excerpt_still_fails_before_any_missing_excerpt_normalization(store):
    class MixedInvalid(WordingGateway):
        async def invoke(self, messages, schemas):
            response = await super().invoke(messages, schemas)
            checks = response.tool_calls[0]["args"]["checks"]
            checks[0]["readable"] = False  # Missing excerpt could otherwise be normalized.
            checks[1]["problematic_excerpts"] = ["A quote absent from this title"]
            return response
    with pytest.raises(RuntimeError, match="exact-field evidence"):
        await PhotoContextAgent(store, None, ImageGateway(), wording_gateway=MixedInvalid()).execute("mixed-invalid", request())
    assert not store.rows("SELECT * FROM events WHERE kind IN ('context_wording_normalized','context_result')")
    detail = json.loads(store.rows("SELECT data FROM events WHERE kind='context_wording_invalid'")[0]["data"])
    assert detail["code"] == "excerpt_not_in_field" and detail["failed_without_excerpt_count"] == 1


@pytest.mark.asyncio
async def test_full_field_adapter_quote_reaches_the_existing_semantic_repair_without_extra_calls(store):
    class OnceMissingQuote(WordingGateway):
        async def invoke(self, messages, schemas):
            self.mode = "missing_excerpt" if self.calls == 0 else "supported"
            return await super().invoke(messages, schemas)
    class RevisingPlanner(ImageGateway):
        async def invoke(self, messages, schemas):
            if self.turns >= 2 and schemas[0]["name"] != "submit_context_review":
                reviews = [json.loads(m.content)["independent_context_review"] for m in messages
                           if m.type == "human" and isinstance(m.content, str) and '"independent_context_review"' in m.content]
                feedback = reviews[-1]["wording_review"]
                assert feedback["checks"][0]["readable"] is False
                assert feedback["checks"][0]["problematic_excerpts"] == [context()["summary"]]
                assert feedback["adapter_quote_provenance"]["normalization"] == "full_field_fallback"
                response = await super().invoke(messages, schemas)
                response.tool_calls[0]["args"]["summary"] = "여러 사진에 반복되는 색을 함께 살펴볼 수 있어요."
                return response
            return await super().invoke(messages, schemas)
    planner, wording = RevisingPlanner(), OnceMissingQuote()
    result = await PhotoContextAgent(store, None, planner, wording_gateway=wording).execute("quote-repair", request())
    assert result["complete"] and result["summary"] != context()["summary"]
    assert planner.turns == 3 and planner.reviews == wording.calls == 2
    assert len(store.rows("SELECT * FROM events WHERE kind='context_wording_normalized'")) == 1


@pytest.mark.asyncio
async def test_combined_feedback_repairs_wording_within_the_same_two_review_rounds(store):
    class OnceFailingWording(WordingGateway):
        async def invoke(self, messages, schemas):
            self.mode = "readability" if self.calls == 0 else "supported"
            return await super().invoke(messages, schemas)

    class RepairingPlanner(ImageGateway):
        async def invoke(self, messages, schemas):
            if self.turns >= 2 and schemas[0]["name"] != "submit_context_review":
                feedback = encoded([m.content for m in messages])
                assert "visual_review" in feedback and "wording_review" in feedback
            return await super().invoke(messages, schemas)

    wording = OnceFailingWording()
    planner = RepairingPlanner()
    result = await PhotoContextAgent(store, None, planner, wording_gateway=wording).execute("copy-repair", request())
    assert wording.calls == planner.reviews == 2
    assert result["evidence"]["wording_review_model"] == CONTEXT_WORDING_MODEL
    assert result["evidence"]["wording_checked_paths"] == ["/summary", "/groups/0/title", "/groups/0/reason"]


@pytest.mark.asyncio
async def test_copy_gate_messages_and_schema_serialize_in_actual_sdk_without_network(store):
    class SerializingWording(WordingGateway):
        async def invoke(self, messages, schemas):
            transport = ChatAnthropic(model=CONTEXT_WORDING_MODEL, api_key="test-only-key")
            payload = transport._get_request_payload(messages)
            assert payload.get("system") and payload["messages"]
            bound = transport.bind_tools(schemas, tool_choice="submit_context_wording_review")
            payload = transport._get_request_payload(messages, **bound.kwargs)
            sdk_schema = payload["tools"][0]["input_schema"]
            assert sdk_schema["properties"]["checks"]["minItems"] == sdk_schema["properties"]["checks"]["maxItems"] == 3
            assert '"enum": ["/summary", "/groups/0/title", "/groups/0/reason"]' in json.dumps(sdk_schema)
            return await super().invoke(messages, schemas)
    wording = SerializingWording()
    await PhotoContextAgent(store, None, ImageGateway(), wording_gateway=wording).execute("copy-sdk", request())
    assert wording.checked_images == [3]


@pytest.mark.asyncio
async def test_empty_context_copy_check_also_gets_full_inspected_corpus(store):
    wording = WordingGateway()
    result = await PhotoContextAgent(store, None, ImageGateway(empty=True), wording_gateway=wording).execute("empty-copy", request())
    assert result["groups"] == [] and wording.checked_images == [3]
    assert result["evidence"]["wording_checked_paths"] == ["/summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["plan", "copy_model", "copy_missing", "copy_duplicate", "copy_not_reviewed"])
async def test_v3_ready_requires_plan_and_copy_review_provenance(store, tamper):
    service = RunService(store, ContextRunner(store=store))
    run = service.start(request())
    await service.tasks[run["id"]]
    key = service.cache_key(request())
    cached = store.cache_get(key)
    if tamper == "plan":
        cached["evidence"]["planned_photo_ids"] = ["uninspected"]
    elif tamper == "copy_model":
        cached["evidence"]["wording_review_model"] = "another-model"
    elif tamper == "copy_missing":
        cached["evidence"]["wording_checked_paths"].pop()
    elif tamper == "copy_duplicate":
        cached["evidence"]["wording_checked_paths"][-1] = "/summary"
    else:
        cached["evidence"]["wording_reviewed"] = False
    store.cache_put(key, cached)
    store.write("DELETE FROM runs")
    assert service.context_ready("a")["state"] == "pending"


@pytest.mark.parametrize("previous_spec,previous_policy", [
    (3, "photo-context-v3-plan-and-wording-review"),
    (5, "photo-context-v5-source-neighborhood-prior"),
])
def test_previous_context_policy_cannot_be_reused_under_the_merged_key(store, previous_spec, previous_policy):
    """Both merge parents' prepared views require preparation under the new policy."""
    service = RunService(store, ContextRunner(store=store))
    raw = context()
    raw["evidence"] = {
        "gallery_revision": store.revision,
        "source_version": store.photo("a").version,
        "inspected_photo_ids": ["a", "b", "c"],
        "photo_versions": {pid: store.photo(pid).version for pid in ("a", "b", "c")},
        "summary_reviewed": True,
        "reviewed_members": [{"group_id": "g", "photo_id": pid} for pid in ("b", "c")],
        "planned_photo_ids": ["b", "c"],
        "wording_review_model": CONTEXT_WORDING_MODEL,
        "wording_reviewed": True,
        "wording_checked_paths": [field["path"] for field in context_wording_fields(raw)],
    }
    cached = service.contexts.cache_value("a", raw)
    assert cached["context_spec"] != previous_spec
    cached.update(context_spec=previous_spec, context_policy=previous_policy)
    current_key = service.contexts.key("a")
    store.cache_put(current_key, cached)
    before = store.db.total_changes
    assert service.context_ready("a")["state"] == "pending"
    assert store.db.total_changes == before
    assert store.cache_get(current_key) == cached
    assert not service.tasks and not store.rows("SELECT * FROM runs")
