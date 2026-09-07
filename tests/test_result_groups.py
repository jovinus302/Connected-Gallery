import asyncio
import base64
import io
import json
import time

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from PIL import Image

from connected_gallery.adapters.store import Store
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import (
    Box, ExplorationResult, ExploreInput, PhotoAnalysis, Region, RunRequest, SemanticAnchor,
)
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import asset, store
from test_reviewer import RetrievalGateway
from empty_proof_fixture import negative_proof


def accepted(ids=("b", "c")):
    return {"label": "선택 대상", "complete": True,
            "items": [{"photo_id": pid, "reason": "verified candidate evidence"} for pid in ids]}


def group(ids=("b", "c"), gid="g"):
    return {"id": gid, "title": "확인한 시각적 관계", "reason": "사진에서 확인한 공통 특징",
            "photo_ids": list(ids)}


def prepared(ids=("b", "c")):
    return {**accepted(ids), "groups": [group(ids)] if ids else [], "grouping_status": "ready"}


@pytest.mark.parametrize("groups", [
    [group(("b",))], [group(("b", "c", "foreign"))],
    [group(("b", "b", "c"))], [group(("b",), "g"), group(("c",), "g")],
    [group(())], [group(("b", "c"), "")], [group(("b", "c"), "   ")],
    [group(("b", ""))], [{**group(), "title": " "}],
])
def test_groups_are_an_exact_partition_of_accepted_photos(groups):
    with pytest.raises(ValidationError):
        ExplorationResult.model_validate({**accepted(), "groups": groups, "grouping_status": "ready"})


def test_legacy_flat_results_are_readable_but_cannot_smuggle_groups():
    assert ExplorationResult.model_validate(accepted()).grouping_status == "legacy"
    for status in ("legacy", "failed"):
        with pytest.raises(ValidationError):
            ExplorationResult.model_validate({**prepared(), "grouping_status": status})
    with pytest.raises(ValidationError):
        ExplorationResult.model_validate(prepared(()))


class GroupGateway:
    def __init__(self, ids=("b", "c"), mode="supported", mutation=None):
        self.ids, self.mode, self.mutation, self.calls = ids, mode, mutation, 0

    async def invoke(self, messages, schemas):
        self.calls += 1
        name = schemas[0]["name"]
        content = json.dumps([m.content for m in messages])
        if name in ("submit_result_groups", "submit_result_revision"):
            assert "independently_verified_candidate_evidence" in content
            members = self.ids
            if self.mode == "foreign":
                members = (*self.ids, "foreign")
            if self.mode == "self":
                members = (*self.ids, "a")
            args = {"groups": [group(members)]}
            if name == "submit_result_revision":
                args.update(items=accepted(self.ids)["items"], omitted=[])
        else:
            assert name == "submit_group_member_review"
            assert "independently_verified_candidate_evidence" not in content
            assert json.loads(messages[1].content[-1]["text"])["proposed_item_reason"] == "verified candidate evidence"
            assert len([b for b in messages[1].content if b.get("type") == "image"]) == 2
            if self.mutation:
                mutation, self.mutation = self.mutation, None
                mutation()
            args = {"anchor_supported": True, "anchor_reason": "선택한 대상이 원본에서 보임",
                "verdict": "uncertain" if self.mode == "unsupported_claim" else "supported",
                "reason": "독립 이미지 비교",
            }
            if self.mode == "missing_anchor_reason":
                del args["anchor_reason"]
        return AIMessage(content="", tool_calls=[{"name": name, "id": str(self.calls),
                                                  "args": args, "type": "tool_call"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["supported", "foreign", "self", "unsupported_claim", "missing_anchor_reason"])
async def test_group_failure_keeps_only_reviewed_flat_items(store, mode):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    toolkit = GalleryTools(store, None, request, "group-test")
    gateway = GroupGateway(mode=mode)
    result = await ResultOrganizer(gateway).organize(toolkit, request, accepted())
    assert result["items"] == accepted()["items"]
    assert result["grouping_status"] == ("ready" if mode == "supported" else "failed")
    assert result["groups"] == ([group()] if mode == "supported" else [])
    assert gateway.calls <= 6
    assert not store.rows("SELECT * FROM events WHERE kind='results'")


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved", [True, False])
async def test_one_evidence_based_regroup_requires_fresh_independent_support(store, resolved):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    toolkit = GalleryTools(store, None, request, "regroup")

    class Gateway:
        calls = 0
        proposals = 0
        reviews = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            name = schemas[0]["name"]
            content = json.dumps([m.content for m in messages])
            if name in ("submit_result_groups", "submit_result_revision"):
                self.proposals += 1
                if self.proposals == 2:
                    assert "independent_group_feedback" in content
                    assert "Identity is not established" in content
                args = {"groups": [{**group(), "title": "동일 제품" if self.proposals == 1 else "외형이 비슷한 사진"}]}
                if name == "submit_result_revision":
                    args.update(items=accepted()["items"], omitted=[])
            else:
                self.reviews += 1
                assert name == "submit_group_member_review"
                assert "independent_group_feedback" not in content
                assert "Identity is not established" not in content
                assert len([b for b in messages[1].content if b.get("type") == "image"]) == 2
                args = {"anchor_supported": True, "anchor_reason": "Source subject is clearly visible",
                    "verdict": "supported" if resolved and self.proposals == 2 else "rejected",
                    "reason": "Visible resemblance" if resolved and self.proposals == 2 else "Identity is not established",
                }
            return AIMessage(content="", tool_calls=[{"name": name, "id": str(self.calls), "args": args, "type": "tool_call"}])

    gateway = Gateway()
    result = await ResultOrganizer(gateway).organize(toolkit, request, accepted())
    assert gateway.calls == 6 and gateway.proposals == 2 and gateway.reviews == 4
    assert result["grouping_status"] == ("ready" if resolved else "failed")
    assert result["items"] == accepted()["items"]
    if resolved:
        assert result["groups"][0]["title"] == "외형이 비슷한 사진"
    else:
        assert result["groups"] == []
    proposals = store.rows("SELECT data FROM events WHERE kind='group_proposal' ORDER BY seq")
    reviews = [json.loads(row["data"]) for row in store.rows("SELECT data FROM events WHERE kind='group_evidence_review' ORDER BY seq")]
    assert len(proposals) == len(reviews) == 2
    assert [review["supported"] for review in reviews] == [False, resolved]
    assert reviews[0]["anchor_supported"] is True
    assert reviews[0]["member_reviews"][0]["reason"] == "Identity is not established"
    assert all({r["photo_id"] for r in review["member_reviews"]} == {"b", "c"} for review in reviews)
    failures = store.rows("SELECT data FROM events WHERE kind='grouping_failed'")
    assert bool(failures) is not resolved
    if failures:
        assert json.loads(failures[0]["data"])["code"] == "unsupported_group_claims"


@pytest.mark.asyncio
async def test_one_supported_member_cannot_validate_a_false_universal_group_claim(store):
    # This test's fake judge reads each actual test image independently. The
    # first matching image cannot supply a feature absent from the second one.
    payload = io.BytesIO()
    Image.new("RGB", (100, 100), "blue").save(payload, "JPEG")
    store.put_image("c", payload.getvalue())
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class ImageJudge:
        proposals = 0
        compared = []

        async def invoke(self, messages, schemas):
            name = schemas[0]["name"]
            if name in ("submit_result_groups", "submit_result_revision"):
                self.proposals += 1
                args = {"groups": [{**group(), "title": "모두 빨간 사진", "reason": "모든 사진이 원본처럼 빨갛다"}]}
                if name == "submit_result_revision":
                    args.update(items=accepted()["items"], omitted=[])
            else:
                assert name == "submit_group_member_review"
                content = messages[1].content
                images = [b for b in content if b.get("type") == "image"]
                assert len(images) == 2
                metadata = json.loads(content[-1]["text"])
                assert set(metadata) == {"source_hint", "proposed_group", "proposed_item_reason"}
                assert "Untrusted hint" in metadata["source_hint"]["trust"]
                assert "photo_ids" not in metadata["proposed_group"]
                pixels = []
                for block in images:
                    with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as picture:
                        pixels.append(picture.getpixel((50, 50)))
                assert pixels[0][0] > 200  # Original source is always first.
                matches = pixels[1][0] > 200
                self.compared.append(matches)
                args = {"anchor_supported": True, "anchor_reason": "원본의 빨간 대상이 선명하다",
                        "verdict": "supported" if matches else "rejected",
                        "reason": "이 사진도 빨갛다" if matches else "이 사진은 파랗기 때문에 모두 빨갛다는 주장은 틀리다"}
            return AIMessage(content="", tool_calls=[{"name": name, "id": "judgment", "args": args, "type": "tool_call"}])

    gateway = ImageJudge()
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "universal-claim"), request, accepted())
    assert result["grouping_status"] == "failed" and result["groups"] == []
    assert result["items"] == accepted()["items"]
    assert gateway.proposals == 2 and sorted(gateway.compared) == [False, False, True, True]
    reviews = [json.loads(r["data"]) for r in store.rows("SELECT data FROM events WHERE kind='group_evidence_review'")]
    assert len(reviews) == 2 and not any(r["supported"] for r in reviews)
    assert all({m["photo_id"] for m in r["member_reviews"] if m["verdict"] == "rejected"} == {"c"} for r in reviews)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["missing", "duplicate", "foreign", "wrong_group"])
async def test_group_cannot_be_ready_with_missing_duplicate_or_foreign_member_review(store, tamper):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class IncompleteReview(ResultOrganizer):
        async def _review_members(self, *args):
            rows = [{"group_index": 0, "group_id": "g", "photo_id": pid, "anchor_supported": True,
                     "anchor_reason": "source is visible", "verdict": "supported", "reason": "visible evidence"}
                    for pid in ("b", "c")]
            if tamper == "missing":
                rows.pop()
            elif tamper == "duplicate":
                rows[1] = dict(rows[0])
            elif tamper == "foreign":
                rows[1]["photo_id"] = "foreign"
            else:
                rows[1]["group_index"] = 1
            return rows

    result = await IncompleteReview(GroupGateway()).organize(GalleryTools(store, None, request, "invalid-review"), request, accepted())
    assert result["grouping_status"] == "failed" and result["items"] == accepted()["items"]
    detail = json.loads(store.rows("SELECT data FROM events WHERE kind='grouping_failed'")[0]["data"])
    assert detail["code"] == "invalid_review_members"


@pytest.mark.asyncio
@pytest.mark.parametrize("stall_round", [1, 2])
async def test_member_concurrency_and_regroup_share_one_deadline_and_cancel_all_children(store, stall_round):
    ids = ("b", "c", "d", "e", "f", "g")
    payload = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(payload, "JPEG")
    for pid in ids[2:]:
        store.upsert(asset(pid))
        store.put_image(pid, payload.getvalue())
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class SlowJudge:
        proposals = 0
        active = 0
        peak = 0
        cancelled = 0

        async def invoke(self, messages, schemas):
            name = schemas[0]["name"]
            if name in ("submit_result_groups", "submit_result_revision"):
                self.proposals += 1
                args = {"groups": [group(ids)]}
                if name == "submit_result_revision":
                    args.update(items=accepted(ids)["items"], omitted=[])
            else:
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(60 if self.proposals == stall_round else .02)
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
                finally:
                    self.active -= 1
                args = {"anchor_supported": True, "anchor_reason": "source is visible",
                        "verdict": "uncertain", "reason": "need another supported description"}
            return AIMessage(content="", tool_calls=[{"name": name, "id": "bounded", "args": args, "type": "tool_call"}])

    gateway = SlowJudge()
    started = time.monotonic()
    result = await ResultOrganizer(gateway, timeout=.5, review_concurrency=3).organize(
        GalleryTools(store, None, request, "bounded-review"), request, accepted(ids))
    elapsed = time.monotonic() - started
    assert result["grouping_status"] == "failed" and result["items"] == accepted(ids)["items"]
    assert gateway.proposals == stall_round
    assert gateway.peak == 3 and gateway.active == 0 and gateway.cancelled == 3
    assert elapsed < 3
    detail = json.loads(store.rows("SELECT data FROM events WHERE kind='grouping_failed'")[0]["data"])
    assert detail["code"] == "timeout"
    before = store.rows("SELECT COUNT(*) AS n FROM events")[0]["n"]
    await asyncio.sleep(.02)
    assert store.rows("SELECT COUNT(*) AS n FROM events")[0]["n"] == before


@pytest.mark.asyncio
async def test_group_diagnostics_never_copy_raw_provider_error_body(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class Unavailable:
        async def invoke(self, *args):
            raise RuntimeError("SENSITIVE_PROVIDER_RESPONSE_AND_TOKEN")

    result = await ResultOrganizer(Unavailable()).organize(GalleryTools(store, None, request, "provider-error"), request, accepted())
    assert result["grouping_status"] == "failed"
    events = store.rows("SELECT data FROM events")
    assert "SENSITIVE_PROVIDER" not in str(events)
    detail = json.loads(events[-1]["data"])
    assert detail["stage"] == "submit_result_groups" and detail["code"] == "model_unavailable"


@pytest.mark.asyncio
async def test_invalid_partition_is_logged_before_rejection(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await ResultOrganizer(GroupGateway(mode="foreign")).organize(GalleryTools(store, None, request, "bad-partition"), request, accepted())
    assert result["grouping_status"] == "failed"
    events = store.rows("SELECT kind,data FROM events ORDER BY seq")
    assert [e["kind"] for e in events] == ["group_proposal", "grouping_failed"]
    assert json.loads(events[-1]["data"])["code"] == "invalid_partition"


@pytest.mark.asyncio
async def test_verified_empty_result_requires_no_group_model(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    gateway = GroupGateway()
    proof = negative_proof(store, request.explore)
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "empty"), request,
                                                    {**accepted(()), "empty_evidence": proof})
    assert result == {**prepared(()), "empty_evidence": proof}
    assert gateway.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["cancel", "delete", "version", "corpus"])
async def test_mutation_during_group_review_prevents_publication(store, mutation):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "mutation", "mutation", request.model_dump_json(), "running", None, None, 0,
    ))

    class Verifier:
        async def invoke(self, messages, schemas):
            return AIMessage(content="", tool_calls=[{"name": "submit_candidate_review", "id": "v", "type": "tool_call", "args": {
                "selected_meaning": "source", "anchor_supported": True,
                "decisions": [{"index": n, "verdict": "supported", "reason": "verified candidate evidence"} for n in range(2)],
            }}])

    def change():
        if mutation == "cancel":
            store.write("UPDATE runs SET status='cancelled' WHERE id='mutation'")
        elif mutation == "delete":
            store.delete("b")
        elif mutation == "version":
            store.upsert(asset("a").model_copy(update={"version": "new"}))
        else:
            store.upsert(asset("new"))

    runner = GraphAgentRunner(store, None, RetrievalGateway(), EvidenceReviewer(Verifier()),
                              result_organizer=ResultOrganizer(GroupGateway(mutation=change)))
    with pytest.raises(ValueError):
        await runner.execute("mutation", request)
    assert not store.rows("SELECT * FROM events WHERE kind='results'")


@pytest.mark.asyncio
async def test_groups_are_created_only_after_independent_candidate_review(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class Verifier:
        async def invoke(self, messages, schemas):
            return AIMessage(content="", tool_calls=[{"name": "submit_candidate_review", "id": "v", "type": "tool_call", "args": {
                "selected_meaning": "source", "anchor_supported": True,
                "decisions": [{"index": n, "verdict": "supported" if n == 0 else "rejected",
                               "reason": "verified candidate evidence"} for n in range(2)],
            }}])

    gateway = GroupGateway(ids=("b",))
    runner = GraphAgentRunner(store, None, RetrievalGateway(), EvidenceReviewer(Verifier()), result_organizer=ResultOrganizer(gateway))
    result = await runner.execute("review-first", request)
    assert result["groups"] == [group(("b",))]
    assert result["grouping_status"] == "ready"
    events = store.rows("SELECT kind,data FROM events WHERE kind IN ('evidence_review','group_evidence_review','results') ORDER BY seq")
    assert [e["kind"] for e in events] == ["evidence_review", "group_evidence_review", "results"]
    assert json.loads(events[-1]["data"]) == result


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["retrieval", "candidate_review"])
@pytest.mark.parametrize("mutation", ["preview", "analysis", "corpus"])
async def test_original_corpus_revision_is_retained_before_grouping(store, phase, mutation):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    original_version = store.photo("a").version

    def change():
        if mutation == "preview":
            payload = io.BytesIO()
            Image.new("RGB", (100, 100), "blue").save(payload, "JPEG")
            store.put_image("a", payload.getvalue())
        elif mutation == "analysis":
            store.save_analysis(PhotoAnalysis(photo_id="a", description="updated observations"))
        else:
            store.upsert(asset("new"))
        # This is precisely the case that per-photo version checks miss.
        assert store.photo("a").version == original_version

    class Retrieval(RetrievalGateway):
        async def invoke(self, messages, schemas):
            if self.calls == 1 and phase == "retrieval":
                change()
            return await super().invoke(messages, schemas)

    class Verifier:
        async def invoke(self, messages, schemas):
            if phase == "candidate_review":
                change()
            return AIMessage(content="", tool_calls=[{"name": "submit_candidate_review", "id": "v", "type": "tool_call", "args": {
                "selected_meaning": "source", "anchor_supported": True,
                "decisions": [{"index": n, "verdict": "supported", "reason": "verified candidate evidence"} for n in range(2)],
            }}])

    grouping = GroupGateway()
    runner = GraphAgentRunner(store, None, Retrieval(), EvidenceReviewer(Verifier()), result_organizer=ResultOrganizer(grouping))
    with pytest.raises(ValueError, match="Gallery changed during exploration"):
        await runner.execute("before-grouping", request)
    assert grouping.calls == 0
    assert not store.rows("SELECT * FROM events WHERE kind='results'")
    assert not store.rows("SELECT * FROM cache")


def test_primary_cannot_submit_ready_groups(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    toolkit = GalleryTools(store, None, request, "primary")
    toolkit.seen = {"a", "b", "c"}
    with pytest.raises(ValueError, match="after independent"):
        toolkit.submit_exploration_result(ExplorationResult.model_validate(prepared()))


class NoCalls:
    calls = 0

    async def execute(self, *args):
        self.calls += 1
        raise AssertionError("Prepared reads must not run inference")


def test_ready_lookup_is_read_only_versioned_and_survives_restart(store):
    runner = NoCalls()
    service = RunService(store, runner)
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    request = RunRequest(role="explorer", explore=explore)
    assert service.ready(explore)["state"] == "pending"
    store.cache_put(service.cache_key(request), prepared())
    before = {table: store.rows(f"SELECT count(*) AS n FROM {table}")[0]["n"] for table in ("runs", "events", "cache")}
    for revision in (0, 99):
        assert service.ready(explore.model_copy(update={"request_revision": revision}))["result"] == prepared()
    assert before == {table: store.rows(f"SELECT count(*) AS n FROM {table}")[0]["n"] for table in before}
    assert runner.calls == 0
    reopened = Store(store.root)
    try:
        assert RunService(reopened, runner).ready(explore)["state"] == "ready"
    finally:
        reopened.close()
    store.upsert(asset("c").model_copy(update={"version": "2"}))
    assert service.ready(explore)["state"] == "pending"
    store.delete("a")
    with pytest.raises(ValueError, match="Unknown photo"):
        service.ready(explore)


def test_ready_canonicalizes_region_metadata_and_rejects_mismatched_crop(store):
    box = Box(x=.1, y=.1, width=.3, height=.4)
    store.save_analysis(PhotoAnalysis(photo_id="a", description="source", regions=[
        Region(id="region-a", photo_id="a", box=box, kind="object", label="actual label", evidence="visible"),
    ]))
    service = RunService(store, NoCalls())
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a", region_id="region-a", box=box, label="client hint"))
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=explore)), prepared())
    without_box = explore.model_copy(update={"anchor": explore.anchor.model_copy(update={"box": None, "label": "other hint"})})
    assert service.ready(without_box)["state"] == "ready"
    wrong_box = explore.model_copy(update={"anchor": explore.anchor.model_copy(update={"box": box.model_copy(update={"x": .2})})})
    with pytest.raises(ValueError, match="does not match"):
        service.ready(wrong_box)
    foreign = explore.model_copy(update={"anchor": explore.anchor.model_copy(update={"photo_id": "b"})})
    with pytest.raises(ValueError, match="Unknown anchor region"):
        service.ready(foreign)


@pytest.mark.parametrize("value", [accepted(), {**accepted(), "groups": [], "grouping_status": "failed"},
                                   {**prepared(), "complete": False},
                                   {**prepared(), "groups": [group(("a", "b"))]}])
def test_legacy_failed_partial_or_invalid_cache_never_claims_ready(store, value):
    service = RunService(store, NoCalls())
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=explore)), value)
    assert service.ready(explore)["state"] == "pending"


@pytest.mark.asyncio
async def test_grouping_failure_is_not_cached_as_success(store):
    class FailedGrouping:
        async def execute(self, *args):
            return {**accepted(), "groups": [], "grouping_status": "failed"}

    service = RunService(store, FailedGrouping())
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    run = service.start(RunRequest(role="explorer", explore=explore))
    await service.tasks[run["id"]]
    assert service.get(run["id"])["status"] == "incomplete"
    assert service.ready(explore)["state"] == "pending"


@pytest.mark.asyncio
async def test_invalid_ready_contract_cannot_be_marked_completed(store):
    class InvalidGrouping:
        async def execute(self, *args):
            return {**prepared(), "groups": [group(("b", "foreign"))]}

    service = RunService(store, InvalidGrouping())
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    run = service.start(RunRequest(role="explorer", explore=explore))
    await service.tasks[run["id"]]
    assert service.get(run["id"])["status"] == "failed"
    assert service.ready(explore)["state"] == "pending"


@pytest.mark.asyncio
async def test_global_organizer_is_not_automatically_started(store, monkeypatch):
    monkeypatch.delenv("CG_AUTO_ORGANIZE", raising=False)

    class Analyst:
        async def execute(self, *args):
            return {"photo_id": "a", "description": "observed"}

    service = RunService(store, Analyst())
    run = service.start(RunRequest(role="analyst", photo_ids=["a"]))
    await service.tasks[run["id"]]
    assert not store.rows("SELECT id FROM runs WHERE json_extract(request,'$.role')='organizer'")
