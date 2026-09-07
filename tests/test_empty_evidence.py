import json
import asyncio
import base64
import io
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from PIL import Image

from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import Box, ExplorationResult, ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from empty_proof_fixture import negative_proof
from test_contracts import asset, store


def empty():
    return {"label": "retrieval-only-label", "complete": True, "items": []}


class Judge:
    def __init__(self, verdict="unrelated", scope=True, anchor=True, mutation=None, malformed=False):
        self.verdict, self.scope, self.anchor = verdict, scope, anchor
        self.mutation, self.malformed, self.calls, self.image_counts = mutation, malformed, 0, []
        self.image_shapes = []

    async def invoke(self, messages, schemas):
        self.calls += 1
        text = json.dumps([message.content for message in messages])
        assert "PREVIOUS_FAILURE_SENTINEL" not in text and "retrieval-only-label" not in text
        schema = schemas[0]
        assert schema["name"] == "submit_empty_review"
        assert "not the identical brand/product" in text and "never selects" in text
        count = schema["input_schema"]["properties"]["decisions"]["minItems"]
        assert schema["input_schema"]["properties"]["decisions"]["maxItems"] == count
        self.image_counts.append(len([block for block in messages[1].content if block.get("type") == "image"]))
        self.image_shapes.append([Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size
                                  for block in messages[1].content if block.get("type") == "image"])
        if self.mutation:
            self.mutation()
        return AIMessage(content="", tool_calls=[{"name": "submit_empty_review", "id": str(self.calls), "type": "tool_call", "args": {
            "selected_meaning": "선택한 대상", "anchor_supported": self.anchor, "scope_sufficient": self.scope,
            "scope_reason": "모든 후보의 실제 이미지를 비교한 격리 테스트 판단",
            "decisions": [{"index": i, "verdict": self.verdict if i == 0 else "unrelated",
                           "reason": "같은 제품 여부와 직접 관련성을 구분한 검토"} for i in range(count - int(self.malformed))]}}])


@pytest.mark.asyncio
async def test_whole_gallery_negative_review_creates_portable_proof_without_group_model(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a", box=Box(x=.1,y=.1,width=.3,height=.4))))
    toolkit = GalleryTools(store, None, request, "negative")
    toolkit.prior_attempt_feedback = {"text": "PREVIOUS_FAILURE_SENTINEL"}
    judge = Judge()
    result = await EvidenceReviewer(judge).review(toolkit, request, empty())
    assert judge.calls == 1 and judge.image_counts == [4]  # selected crop twice + 2 full candidates
    assert judge.image_shapes == [[(30, 40), (100, 100), (100, 100), (30, 40)]]
    assert set(result["empty_evidence"]["inspected_photo_ids"]) == {"a", "b", "c"}
    assert result["complete"] and result["items"] == []
    grouped = await ResultOrganizer(None).organize(toolkit, request, result)
    assert grouped["grouping_status"] == "ready" and grouped["empty_evidence"] == result["empty_evidence"]
    assert not store.rows("SELECT * FROM events WHERE kind='group_proposal'")
    service = RunService(store, None)
    base = service.cache_key(request)
    old = {**empty(), "grouping_status": "ready", "groups": []}
    store.cache_put(base, old)
    assert service.ready(request.explore)["state"] == "pending"
    proof_key = service.empty_cache_key(request.explore)
    store.cache_put(proof_key, grouped)
    assert service.ready(request.explore)["state"] == "ready"
    assert service.prepared_cache_key(request.explore) == proof_key
    assert store.cache_get(base) == old  # The old unreviewed cache was not rewritten.


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict,scope,anchor", [("possible_relation", True, True), ("uncertain", True, True),
                                                  ("unrelated", False, True), ("unrelated", True, False)])
async def test_possible_relation_uncertainty_or_scope_failure_stays_incomplete(store, verdict, scope, anchor):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    toolkit = GalleryTools(store, None, request, "investigate")
    toolkit.seen = {"a"}
    result = await EvidenceReviewer(Judge(verdict, scope, anchor)).review(toolkit, request, empty())
    assert not result["complete"] and result["items"] == [] and "empty_evidence" not in result
    assert toolkit.review_feedback[0]["verdict"] == verdict
    assert toolkit.empty_review_status == "needs_investigation"
    assert toolkit.seen == {"a"}
    with pytest.raises(ValueError, match="Inspect candidate"):
        toolkit.submit_exploration_result(ExplorationResult(label="blind lead", items=[{"photo_id":"b","reason":"Only feedback"}]))
    grouped = await ResultOrganizer(None).organize(toolkit, request, result)
    assert grouped["grouping_status"] == "failed"


@pytest.mark.asyncio
async def test_model_budget_and_missing_images_cannot_become_confirmed_empty(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    judge = Judge()
    store.image_path("c").unlink()
    result = await EvidenceReviewer(judge).review(GalleryTools(store, None, request, "missing"), request, empty())
    assert not result["complete"] and judge.calls == 0
    for i in range(23):
        store.upsert(asset("extra" + str(i)))
    result = await EvidenceReviewer(judge).review(GalleryTools(store, None, request, "budget"), request, empty())
    assert not result["complete"] and judge.calls == 0
    event = json.loads(store.rows("SELECT data FROM events WHERE run_id='budget'")[0]["data"])
    assert event["code"] == "candidate_budget"


@pytest.mark.asyncio
async def test_malformed_negative_review_fails_after_one_format_repair(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    judge = Judge(malformed=True)
    result = await EvidenceReviewer(judge).review(GalleryTools(store, None, request, "bad-review"), request, empty())
    assert judge.calls == 2 and not result["complete"] and "empty_evidence" not in result


@pytest.mark.asyncio
async def test_gallery_changes_during_negative_review_abort_the_run(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    with pytest.raises(ValueError, match="changed"):
        await EvidenceReviewer(Judge(mutation=store.bump)).review(GalleryTools(store, None, request, "changed"), request, empty())


@pytest.mark.parametrize("damage", ["missing", "old_spec", "model", "revision", "version", "coverage", "decision", "anchor"])
def test_ready_rejects_invalid_or_stale_negative_proof_without_deleting_it(store, damage):
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    service = RunService(store, None)
    proof = negative_proof(store, query)
    if damage == "old_spec": proof["spec"] = 0
    if damage == "model": proof["cache_model"] = "different-model"
    if damage == "revision": proof["gallery_revision"] -= 1
    if damage == "version": proof["photo_versions"]["b"] = "old-version"
    if damage == "coverage":
        proof["eligible_photo_ids"].remove("b");proof["inspected_photo_ids"].remove("b");del proof["photo_versions"]["b"]
        proof["decisions"] = [d for d in proof["decisions"] if d["photo_id"] != "b"]
    if damage == "decision": proof["decisions"] = proof["decisions"][:1]
    if damage == "anchor": proof["anchor"]["label"] = "different referent"
    value = {**empty(), "groups": [], "grouping_status": "ready"}
    if damage != "missing": value["empty_evidence"] = proof
    key = service.empty_cache_key(query)
    store.cache_put(key, value)
    assert service.ready(query)["state"] == "pending" and service.prepared_cache_key(query) is None
    assert store.cache_get(key) == value


def test_retrieval_cannot_forge_negative_proof_and_positive_serialization_is_unchanged(store):
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    request = RunRequest(role="explorer", explore=query)
    toolkit = GalleryTools(store, None, request, "forged")
    schema = next(s for s in toolkit.schemas() if s["name"] == "submit_exploration_result")
    assert "empty_evidence" not in schema["input_schema"]["properties"]
    with pytest.raises(ValueError, match="retrieval agent"):
        toolkit.submit_exploration_result(ExplorationResult(**empty(), empty_evidence=negative_proof(store, query)))
    positive = {"label": "Selected", "items": [{"photo_id": "b", "reason": "Seen"}], "complete": True,
                "grouping_status": "ready", "groups": [{"id": "g", "title": "Relation", "reason": "Visible", "photo_ids": ["b"]}]}
    assert ExplorationResult.model_validate(positive).model_dump(mode="json") == positive
    service = RunService(store, None)
    store.cache_put(service.cache_key(request), positive)
    assert service.ready(query)["result"] == positive


def test_corrupt_current_positive_is_not_hidden_by_a_prior_negative_proof(store):
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    service = RunService(store, None)
    store.cache_put(service.empty_cache_key(query), {**empty(), "groups": [], "grouping_status": "ready",
                                                    "empty_evidence": negative_proof(store, query)})
    base = service.cache_key(RunRequest(role="explorer", explore=query))
    store.write("INSERT INTO cache VALUES(?,?,?)", (base, store.revision, "broken current positive"))
    assert service.ready(query)["state"] == "pending" and service.prepared_cache_key(query) is None


@pytest.mark.asyncio
async def test_service_writes_verified_empty_to_its_proof_key_only(store):
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    value = {**empty(), "groups": [], "grouping_status": "ready", "empty_evidence": negative_proof(store, query)}
    class PreparedFixtureRunner:
        async def execute(self, *args): return value
    service = RunService(store, PreparedFixtureRunner())
    request = RunRequest(role="explorer", explore=query)
    base = service.cache_key(request)
    old = {**empty(), "groups": [], "grouping_status": "ready"}
    store.cache_put(base, old)
    run = service.start(request)
    await asyncio.gather(*list(service.tasks.values()))
    assert service.get(run["id"])["status"] == "completed"
    assert store.cache_get(base) == old
    assert store.cache_get(service.empty_cache_key(query)) == value
    assert service.ready(query)["result"] == value


@pytest.mark.asyncio
async def test_negative_leads_require_explorer_inspection_and_resubmission(store):
    class Retrieval:
        calls = 0
        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls == 1: name,args = "inspect_photos", {"photo_ids": ["a", "b", "c"]}
            elif self.calls == 2: name,args = "submit_exploration_result", empty()
            elif self.calls == 3:
                assert "investigation leads, not accepted photos" in json.dumps([m.content for m in messages])
                assert not store.rows("SELECT * FROM events WHERE kind='results'")
                name,args = "inspect_photos", {"photo_ids": ["b"]}
            else: name,args = "submit_exploration_result", {"label": "Inspected alternative", "complete": True,
                                                               "items": [{"photo_id": "b", "reason": "Directly related but different"}]}
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(self.calls), "type": "tool_call"}])

    class Review(Judge):
        async def invoke(self, messages, schemas):
            if schemas[0]["name"] == "submit_empty_review": return await super().invoke(messages, schemas)
            return AIMessage(content="", tool_calls=[{"name": "submit_candidate_review", "id": "positive", "type": "tool_call", "args": {
                "selected_meaning": "Selected", "anchor_supported": True,
                "decisions": [{"index": 0, "verdict": "supported", "reason": "Independent direct relationship"}]}}])

    retrieval = Retrieval()
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await GraphAgentRunner(store, None, retrieval, EvidenceReviewer(Review("possible_relation"))).execute("refined-empty", request)
    assert retrieval.calls == 4 and result["items"] == [{"photo_id": "b", "reason": "Independent direct relationship"}]
    assert "empty_evidence" not in result
