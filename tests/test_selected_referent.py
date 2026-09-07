"""Selection-preservation transport and gates, with isolated image/model doubles.

These tests do not claim a live model follows the instruction. They verify that
every relevant model sees the same rule, actual selected crop and fixed hint,
and that its unsupported-source/related-candidate judgments retain their scope.
"""
import base64
import hashlib
import io
import json

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_specs.prompts import PROMPTS, SELECTED_REFERENT_CONTRACT
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import Box, ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from empty_proof_fixture import negative_proof
from test_contracts import store
from test_result_groups import prepared


def selection(kind, *, direction="related"):
    # Fixture meanings deliberately do not use any actual demonstration target.
    label = "선택한 수납 케이스" if kind == "object" else "선택한 전시장 내부"
    return RunRequest(role="explorer", explore=ExploreInput(direction=direction,
        anchor=SemanticAnchor(photo_id="a", kind=kind, label=label,
                              box=Box(x=.1, y=.2, width=.4, height=.3))))


def response(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "fixture-review", "type": "tool_call"}])


def observe_contract(messages):
    systems = [message.content for message in messages if message.type == "system"]
    assert len(systems) == 1 and systems[0].count(SELECTED_REFERENT_CONTRACT) == 1
    human = next(message.content for message in messages if message.type == "human")
    images = [block for block in human if isinstance(block, dict) and block.get("type") == "image"]
    shapes = []
    for block in images:
        with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as image:
            shapes.append(image.size)
    return human, shapes


class Judgment:
    def __init__(self, req, *, source_present=True, related_candidate=True):
        self.req, self.source_present, self.related_candidate = req, source_present, related_candidate
        self.calls, self.shapes = 0, []

    async def invoke(self, messages, schemas):
        self.calls += 1
        human, shapes = observe_contract(messages)
        self.shapes.append(shapes)
        metadata = json.loads(human[0]["text"])
        expected = self.req.explore.anchor
        hint = metadata.get("selected_meaning_hint", metadata.get("selected_label_hint"))
        assert hint == expected.label and metadata["selected_kind"] == expected.kind
        assert metadata["direction"] == self.req.explore.direction
        text = json.dumps([message.content for message in messages], ensure_ascii=False)
        assert "RETRIEVAL_PROPOSED_SUBSTITUTE" not in text and "PRIOR_SUBSTITUTE_LEAD" not in text
        schema = schemas[0]
        fields = schema["input_schema"]["properties"]
        assert "intended" in fields["selected_meaning"]["description"]
        assert "intended" in fields["anchor_supported"]["description"]
        count = fields["decisions"]["minItems"]
        assert count == fields["decisions"]["maxItems"] == 2
        negative = schema["name"] == "submit_empty_review"
        # This is a model double's explicit visual judgment, never an ID-based
        # application rule: first photo matches only a different surrounding
        # subject; the second can depict a directly related selected referent.
        decisions = [{"index": 0, "verdict": "unrelated" if negative else "rejected",
            "reason": "함께 보이는 다른 대상만 비슷하며 선택 대상과의 직접 관계는 확인되지 않습니다."},
            {"index": 1, "verdict": ("possible_relation" if negative else "supported") if self.related_candidate
                                    else ("unrelated" if negative else "rejected"),
             "reason": "선택한 대상 자체의 형태와 용도를 비교할 근거가 있습니다." if self.related_candidate
                       else "선택한 대상이나 직접 관련된 대상이 확인되지 않습니다."}]
        args = {"selected_meaning": expected.label if self.source_present else "의도된 선택 대상을 확인할 수 없습니다.",
                "anchor_supported": self.source_present, "decisions": decisions}
        if negative:
            args.update(scope_sufficient=self.source_present,
                        scope_reason="같은 선택 대상을 기준으로 모든 제공 사진을 검토했습니다.")
        return response(schema["name"], args)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["object", "place"])
@pytest.mark.parametrize("negative", [False, True])
async def test_contents_or_foreground_lead_cannot_replace_fixed_source_in_independent_review(store, kind, negative):
    req = selection(kind)
    toolkit = GalleryTools(store, None, req, "fixed-selection")
    toolkit.prior_attempt_feedback = {"text": "PRIOR_SUBSTITUTE_LEAD"}
    toolkit.seen = {"a"}
    judge = Judgment(req)
    draft = {"label": "RETRIEVAL_PROPOSED_SUBSTITUTE", "complete": True,
             "items": [] if negative else [{"photo_id": pid, "reason": "RETRIEVAL_PROPOSED_SUBSTITUTE"} for pid in "bc"]}
    result = await EvidenceReviewer(judge).review(toolkit, req, draft)
    assert judge.calls == 1 and judge.shapes == [[(40, 30), (100, 100), (100, 100), (40, 30)]]
    assert req.explore.anchor.label == selection(kind).explore.anchor.label
    assert toolkit.review_anchor_supported is True
    if negative:
        assert not result["complete"] and result["items"] == [] and "empty_evidence" not in result
        assert toolkit.review_feedback[1]["photo_id"] == "c" and toolkit.review_feedback[1]["verdict"] == "possible_relation"
        assert toolkit.seen == {"a"}  # A judge's lead gives no Explorer inspection credit.
    else:
        assert result["complete"] and [item["photo_id"] for item in result["items"]] == ["c"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["object", "place"])
@pytest.mark.parametrize("negative", [False, True])
async def test_absent_intended_target_remains_incomplete_even_if_other_subjects_are_visible(store, kind, negative):
    req = selection(kind)
    toolkit = GalleryTools(store, None, req, "missing-intended-target")
    # Even a supported candidate verdict cannot override source invalidity.
    judge = Judgment(req, source_present=False, related_candidate=not negative)
    draft = {"label": "RETRIEVAL_PROPOSED_SUBSTITUTE", "complete": True,
             "items": [] if negative else [{"photo_id": pid, "reason": "RETRIEVAL_PROPOSED_SUBSTITUTE"} for pid in "bc"]}
    result = await EvidenceReviewer(judge).review(toolkit, req, draft)
    assert result["items"] == [] and not result["complete"] and "empty_evidence" not in result
    assert toolkit.review_anchor_supported is False
    assert judge.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["object", "place"])
async def test_fixed_referent_still_allows_model_verified_empty_without_manual_omissions(store, kind):
    req = selection(kind)
    toolkit = GalleryTools(store, None, req, "verified-fixed-empty")
    judge = Judgment(req, related_candidate=False)
    result = await EvidenceReviewer(judge).review(toolkit, req, {"label": "Selected", "complete": True, "items": []})
    assert result["complete"] and result["empty_evidence"]["selected_meaning"] == req.explore.anchor.label
    assert result["empty_evidence"]["anchor"] == req.explore.anchor.model_dump(mode="json")
    assert [item["verdict"] for item in result["empty_evidence"]["decisions"]] == ["unrelated", "unrelated"]
    assert judge.calls == 1 and toolkit.empty_review_status == "verified_empty"


@pytest.mark.asyncio
@pytest.mark.parametrize("negative", [False, True])
async def test_same_moment_retains_original_full_context_and_does_not_require_object_in_candidates(store, negative):
    req = selection("place", direction="same_moment")
    toolkit, judge = GalleryTools(store, None, req, "same-context"), Judgment(req)
    result = await EvidenceReviewer(judge).review(toolkit, req, {"label": "Selected", "complete": True,
        "items": [] if negative else [{"photo_id": pid, "reason": "Claim"} for pid in "bc"]})
    assert judge.shapes[0][:2] == [(40, 30), (100, 100)]
    assert len(judge.shapes[0]) == (5 if negative else 6)
    assert toolkit.review_anchor_supported and result["complete"] == (not negative)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_present", [False, True])
async def test_group_proposer_and_independent_member_judge_share_intended_source_contract(store, source_present):
    req = selection("place")
    toolkit = GalleryTools(store, None, req, "group-selection")
    calls = []
    class GroupJudge:
        async def invoke(self, messages, schemas):
            human, shapes = observe_contract(messages)
            metadata = json.loads(human[-1]["text"])
            assert metadata["source_hint"]["selected_kind"] == "place"
            assert metadata["source_hint"]["selected_label"] == req.explore.anchor.label
            assert metadata["source_hint"]["direction"] == "related"
            assert shapes == [(40, 30), (100, 100)]
            name = schemas[0]["name"]
            calls.append(name)
            if name == "submit_result_groups":
                return response(name, {"groups": [{"id": "g", "title": "선택한 공간", "reason": "공간 구성을 비교합니다.", "photo_ids": ["c"]}]})
            return response(name, {"anchor_supported": source_present,
                "anchor_reason": "의도된 공간이 보입니다." if source_present else "다른 대상만 보여 의도된 공간을 확인할 수 없습니다.",
                "verdict": "supported", "reason": "선택한 공간 자체에 대한 비교입니다."})
    result = await ResultOrganizer(GroupJudge()).organize(toolkit, req, {
        "label": "공간", "complete": True, "items": [{"photo_id": "c", "reason": "공간을 비교합니다."}]})
    assert calls == ["submit_result_groups", "submit_group_member_review"]
    assert result["grouping_status"] == ("ready" if source_present else "failed")


def test_existing_prepared_positive_and_negative_namespaces_are_unchanged(store, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "fixture-model")
    monkeypatch.delenv("CG_COMPATIBLE_CONNECTION_MODELS", raising=False)
    assert PROMPTS["explorer"].count(SELECTED_REFERENT_CONTRACT) == 1
    req, service = selection("object"), RunService(store, None)
    value = req.explore.model_dump(mode="json", exclude={"request_revision"})
    value["photo_version"] = store.photo("a").version
    original = hashlib.sha256(encoded(["agent-spec-v18", "v13-reviewed-result-revision", "fixture-model", value]).encode()).hexdigest()
    assert service.cache_key(req) == original
    store.cache_put(original, prepared())
    assert service.ready(req.explore)["result"] == prepared()
    other = selection("place")
    base = service.cache_key(other)
    negative_key = hashlib.sha256(encoded(["empty-evidence", 1, "whole-eligible-independent-negative-v1", base, store.revision]).encode()).hexdigest()
    assert service.empty_cache_key(other.explore) == negative_key
    empty = {"label": "검토한 결과", "complete": True, "items": [], "groups": [], "grouping_status": "ready",
             "empty_evidence": negative_proof(store, other.explore)}
    store.cache_put(negative_key, empty)
    assert service.ready(other.explore)["result"] == empty
