"""Negative-review scope transport and fail-closed behavior, using model doubles.

The doubles supply judgments; these are not live-model semantic accuracy tests.
Distinct image fixtures verify that the model receives full candidate evidence,
and the assertions outside invoke cannot be swallowed by review error handling.
No demonstration photo IDs, object classes, or answer rules are used here.
"""
import base64
import copy
import io
import json

import pytest
from langchain_core.messages import AIMessage
from PIL import Image, ImageDraw

from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import Box, ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store


class ScopeJudge:
    def __init__(self, *, verdict="unrelated", reason, scope=True, anchor=True,
                 scope_reason="제공된 전체 사진에서 선택 대상의 직접적인 시각적 관계를 검토했습니다.",
                 omit_last=False):
        self.verdict, self.reason = verdict, reason
        self.scope, self.anchor, self.scope_reason = scope, anchor, scope_reason
        self.omit_last, self.calls = omit_last, []

    async def invoke(self, messages, schemas):
        self.calls.append((messages, copy.deepcopy(schemas)))
        count = schemas[0]["input_schema"]["properties"]["decisions"]["minItems"]
        args = {
            "selected_meaning": "선택된 형태가 보이는 대상" if self.anchor else "선택 대상을 식별할 수 없습니다.",
            "anchor_supported": self.anchor, "scope_sufficient": self.scope,
            "scope_reason": self.scope_reason,
            "decisions": [{"index": i, "verdict": self.verdict if i == 0 else "unrelated",
                           "reason": self.reason if i == 0 else "선택 대상과 직접 비교할 시각적 단서가 없습니다."}
                          for i in range(count - int(self.omit_last))],
        }
        return AIMessage(content="", tool_calls=[{
            "name": "submit_empty_review", "args": args, "id": str(len(self.calls)), "type": "tool_call"}])


def selected_request():
    return RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(
        photo_id="a", kind="object", label="선택된 형태", box=Box(x=.2, y=.1, width=.4, height=.3))))


def install_distinct_images(store):
    for pid, color in [("a", "orange"), ("b", "navy"), ("c", "green")]:
        image = Image.new("RGB", (100, 100), color)
        # Evidence near all four edges is deliberately outside a central crop.
        draw = ImageDraw.Draw(image)
        for box in [(0, 0, 9, 9), (90, 0, 99, 9), (0, 90, 9, 99), (90, 90, 99, 99)]:
            draw.rectangle(box, fill="magenta")
        out = io.BytesIO()
        image.save(out, "JPEG")
        store.put_image(pid, out.getvalue())


def assert_scope_evidence_transport(judge, toolkit):
    messages, schemas = judge.calls[0]
    prompt = next(message.content for message in messages if message.type == "system")
    # Protect the two-sided contract: neither hidden-fact speculation nor a
    # convenient negative conclusion may replace assessment of visible evidence.
    for clause in [
        "does not require disproving unknown facts",
        "an observable target-specific lead",
        "actual occlusion, blur, or ambiguity",
        "including visible secondary or background subjects",
        "not merely a shared broad category",
        "scope_sufficient=false for incomplete candidate review",
        "if it prevents identifying that target, anchor_supported must remain false",
        "Never overlook a relevant ambiguous cue to obtain an empty result",
    ]:
        assert clause in prompt
    fields = schemas[0]["input_schema"]["properties"]
    definitions = schemas[0]["input_schema"]["$defs"]["NegativeDecision"]["properties"]
    assert definitions["verdict"]["enum"] == ["unrelated", "possible_relation", "uncertain"]
    assert "not a hypothetical hidden relationship" in definitions["verdict"]["description"]
    assert "relevant visible secondary subjects" in definitions["reason"]["description"]
    assert "not proof that an unseen real-world relationship is impossible" in fields["scope_sufficient"]["description"]
    assert fields["decisions"]["minItems"] == fields["decisions"]["maxItems"] == 2

    content = next(message.content for message in messages if message.type == "human")
    metadata = json.loads(content[0]["text"])
    assert metadata["selected_kind"] == "object" and metadata["selected_label_hint"] == "선택된 형태"
    assert metadata["eligible_candidate_count"] == 2
    images = [block for block in content if block.get("type") == "image"]
    with Image.open(io.BytesIO(base64.b64decode(images[0]["source"]["data"]))) as source:
        assert source.size == (40, 30)
    assert images[0] == images[-1]
    for index, pid in enumerate(["b", "c"]):
        marker = next(i for i, block in enumerate(content) if block.get("text") == f"FULL CANDIDATE {index}")
        actual = content[marker + 1]
        with Image.open(io.BytesIO(base64.b64decode(actual["source"]["data"]))) as candidate:
            # Check the full frame and distinguishing center/edge evidence
            # without changing the Explorer's image-inspection ledger.
            assert candidate.size == (100, 100)
            with toolkit.store.read_image(pid) as original:
                assert all(abs(a - b) < 15 for a, b in zip(candidate.getpixel((50, 50)), original.getpixel((50, 50))))
            for point in [(4, 4), (95, 4), (4, 95), (95, 95)]:
                red, green, blue = candidate.getpixel(point)
                assert red > 180 and blue > 180 and green < 70


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_reason", [
    "두 대상에 보이지 않는 현실의 관계가 있을지는 알 수 없지만 제공된 전체 사진에는 직접 비교할 단서가 없습니다.",
    "선택 대상은 일부 가려져도 의도된 범위를 식별할 수 있고 전체 후보에 직접 관련된 시각적 단서가 없습니다.",
])
async def test_visible_scope_can_support_empty_without_disproving_hidden_facts(store, scope_reason):
    install_distinct_images(store)
    req = selected_request()
    toolkit = GalleryTools(store, None, req, "visible-scope")
    toolkit.seen = {"a"}
    judge = ScopeJudge(reason="넓은 범주만 같고 선택 대상을 직접 비교할 구체적 형태나 사용 맥락은 보이지 않습니다.",
                       scope_reason=scope_reason)
    reviewed = await EvidenceReviewer(judge).review(toolkit, req, {"label": "선택", "complete": True, "items": []})
    assert len(judge.calls) == 1 and toolkit.seen == {"a"}
    assert_scope_evidence_transport(judge, toolkit)
    assert toolkit.seen == {"a"}
    assert reviewed["complete"] and reviewed["items"] == []
    assert reviewed["empty_evidence"]["scope_reason"] == scope_reason
    assert reviewed["empty_evidence"]["eligible_photo_ids"] == ["b", "c"]
    assert reviewed["empty_evidence"]["spec"] == 1
    organized = await ResultOrganizer(None).organize(toolkit, req, reviewed)
    service = RunService(store, None)
    key = service.empty_cache_key(req.explore)
    store.cache_put(key, organized)
    assert service.ready(req.explore)["state"] == "ready"
    assert service.prepared_cache_key(req.explore) == key


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict,reason,scope,anchor", [
    ("possible_relation", "배경에 작게 보이는 대상의 굽은 연결부와 반복 문양이 선택 대상과 구체적으로 비교됩니다.", True, True),
    ("uncertain", "주변의 반복 문양이 관련 단서일 수 있으나 흐림 때문에 연결부의 형태를 판독할 수 없습니다.", True, True),
    ("unrelated", "선택 대상이 가려져 의도된 범위를 식별할 수 없습니다.", True, False),
    ("unrelated", "관련 증거의 판독을 끝내지 못해 전체 후보 검토 범위가 충분하지 않습니다.", False, True),
])
async def test_observed_leads_or_actual_evidence_limits_cannot_become_ready_empty(store, verdict, reason, scope, anchor):
    install_distinct_images(store)
    req = selected_request()
    toolkit = GalleryTools(store, None, req, "limited-scope")
    toolkit.seen = {"a"}
    judge = ScopeJudge(verdict=verdict, reason=reason, scope=scope, anchor=anchor)
    result = await EvidenceReviewer(judge).review(toolkit, req, {"label": "선택", "complete": True, "items": []})
    assert len(judge.calls) == 1 and toolkit.seen == {"a"}
    assert_scope_evidence_transport(judge, toolkit)
    assert result["items"] == [] and not result["complete"] and "empty_evidence" not in result
    assert toolkit.empty_review_status == "needs_investigation"
    assert toolkit.review_feedback[0] == {"photo_id": "b", "verdict": verdict, "reason": reason}
    event = json.loads(store.rows("SELECT data FROM events WHERE kind='empty_evidence_review'")[0]["data"])
    assert event["anchor_supported"] is anchor and event["scope_sufficient"] is scope
    assert event["status"] == "needs_investigation"
    grouped = await ResultOrganizer(None).organize(toolkit, req, result)
    assert grouped["grouping_status"] == "failed"
    assert RunService(store, None).ready(req.explore)["state"] == "pending"


@pytest.mark.asyncio
async def test_claimed_whole_scope_without_one_candidate_decision_remains_unverified(store):
    req = selected_request()
    toolkit = GalleryTools(store, None, req, "claimed-scope")
    judge = ScopeJudge(reason="직접 관련성이 없습니다.", scope=True, anchor=True, omit_last=True)
    result = await EvidenceReviewer(judge).review(toolkit, req, {"label": "선택", "complete": True, "items": []})
    assert len(judge.calls) == 2  # The single format repair must not invent the missing decision.
    assert not result["complete"] and "empty_evidence" not in result
    assert toolkit.empty_review_status == "insufficient"
    assert not store.rows("SELECT * FROM events WHERE kind='empty_evidence_review' AND data LIKE '%verified_empty%'")
