import json

import pytest
from langchain_core.messages import AIMessage

from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import ExploreInput, PhotoAnalysis, RunRequest, SemanticAnchor
from test_contracts import store


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["filter", "cancel", "user_include"])
async def test_spaces_publish_only_after_membership_review_and_preserve_user_edits(store, mode):
    from connected_gallery.agent_runtime.reviewer import SpaceEvidenceReviewer
    request = RunRequest(role="organizer")
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "spaces-review", "spaces-review", request.model_dump_json(), "running", None, None, 0,
    ))
    if mode == "user_include":
        store.write("INSERT INTO feedback VALUES(?,?)", ("include", json.dumps({
            "kind": "space_include", "space_id": "context", "photo_id": "c",
        })))

    class Primary:
        async def invoke(self, messages, schemas):
            return AIMessage(content="", tool_calls=[{
                "name": "submit_space_proposal", "id": "proposal", "type": "tool_call",
                "args": {"spaces": [{"id": "context", "name": "Observed context", "meaning": "Visible activity",
                                     "items": [{"photo_id": p, "reason": "primary claim"} for p in ["b", "c"]]}]},
            }])

    class Verifier:
        async def invoke(self, messages, schemas):
            assert store.spaces() == []
            assert "primary claim" not in str([m.content for m in messages])
            if mode == "cancel":
                store.write("UPDATE runs SET status='cancelled' WHERE id='spaces-review'")
            return AIMessage(content="", tool_calls=[{
                "name": "submit_candidate_review", "id": "review", "type": "tool_call",
                "args": {"decisions": [{"index": i, "verdict": "supported" if i == 0 else "rejected",
                                        "reason": "independent visible evidence"} for i in range(2)]},
            }])

    runner = GraphAgentRunner(store, None, Primary(), space_reviewer=SpaceEvidenceReviewer(Verifier()))
    if mode == "cancel":
        with pytest.raises(ValueError, match="no longer active"):
            await runner.execute("spaces-review", request)
        assert store.spaces() == []
    else:
        result = await runner.execute("spaces-review", request)
        expected = ["b", "c"] if mode == "user_include" else ["b"]
        assert [item["photo_id"] for item in result["spaces"][0]["items"]] == expected
        assert [item["photo_id"] for item in store.spaces()[0]["items"]] == expected


class RetrievalGateway:
    def __init__(self):
        self.calls = 0

    async def invoke(self, messages, schemas):
        self.calls += 1
        if self.calls == 1:
            name, args = "inspect_photos", {"photo_ids": ["b", "c"]}
        else:
            name, args = "submit_exploration_result", {
                "label": "선택 대상", "complete": True,
                "items": [{"photo_id": pid, "reason": "unsupported retrieval claim"} for pid in ["b", "c"]],
            }
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args, "id": str(self.calls), "type": "tool_call",
        }])


@pytest.mark.asyncio
async def test_plain_ending_after_partial_proposal_still_requires_review(store):
    class PartialGateway(RetrievalGateway):
        async def invoke(self, messages, schemas):
            if self.calls >= 2:
                return AIMessage(content="These partial results are all I can confirm")
            response = await super().invoke(messages, schemas)
            if self.calls == 2:
                response.tool_calls[0]["args"]["complete"] = False
            return response

    class Verifier:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            assert not store.rows("SELECT * FROM events WHERE kind='results'")
            return AIMessage(content="", tool_calls=[{
                "name": "submit_candidate_review", "id": "review", "type": "tool_call",
                "args": {"selected_meaning": "selected object", "anchor_supported": True,
                         "decisions": [{"index": n, "verdict": "supported" if n == 0 else "rejected",
                                        "reason": "independent evidence"} for n in range(2)]},
            }])

    verifier = Verifier()
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await GraphAgentRunner(store, None, PartialGateway(), EvidenceReviewer(verifier)).execute("partial-end", request)
    assert verifier.calls == 1
    assert result["complete"] is False
    assert [item["photo_id"] for item in result["items"]] == ["b"]
    events = store.rows("SELECT data FROM events WHERE kind='results'")
    assert len(events) == 1 and json.loads(events[0]["data"]) == result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["filter", "reject_all", "wrong_crop", "malformed", "cancelled"])
async def test_only_independently_reviewed_candidates_reach_result_events(store, mode):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    store.save_analysis(PhotoAnalysis(photo_id="b", description="unsupported retrieval claim"))
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "review", "review", request.model_dump_json(), "running", None, None, 0,
    ))

    class ReviewGateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            # The primary model has submitted, but nothing unreviewed is visible.
            assert not store.rows("SELECT * FROM events WHERE kind='results'")
            assert "unsupported retrieval claim" not in json.dumps([m.content for m in messages])
            assert schemas[0]["name"] == "submit_candidate_review"
            if mode == "cancelled":
                store.write("UPDATE runs SET status='cancelled' WHERE id='review'")
            decisions = [
                {"index": 1, "verdict": "rejected", "reason": "대상이 보이지 않음"},
                {"index": 0, "verdict": "rejected" if mode == "reject_all" else "supported", "reason": "시각 근거 확인"},
            ]
            if mode == "malformed":
                decisions[0]["index"] = 0
            return AIMessage(content="", tool_calls=[{
                "name": "submit_candidate_review", "id": "review", "type": "tool_call",
                "args": {"selected_meaning": "선택 대상", "anchor_supported": mode != "wrong_crop",
                         "decisions": decisions},
            }])

    verifier = ReviewGateway()
    runner = GraphAgentRunner(store, None, RetrievalGateway(), EvidenceReviewer(verifier))
    if mode in ("malformed", "cancelled"):
        with pytest.raises(ValueError):
            await runner.execute("review", request)
        assert not store.rows("SELECT * FROM events WHERE kind='results'")
        assert verifier.calls == (2 if mode == "malformed" else 1)
    else:
        result = await runner.execute("review", request)
        assert result["items"] == ([{"photo_id": "b", "reason": "시각 근거 확인"}] if mode == "filter" else [])
        assert result["complete"] == (mode == "filter")
        events = store.rows("SELECT data FROM events WHERE kind='results'")
        assert len(events) == 1
        assert json.loads(events[0]["data"]) == result
        assert len(store.rows("SELECT * FROM events WHERE kind='evidence_review'")) == (2 if mode == "reject_all" else 1)


@pytest.mark.asyncio
async def test_review_repairs_missing_index_once_before_publishing(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class RepairGateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            assert not store.rows("SELECT * FROM events WHERE kind='results'")
            assert schemas[0]["input_schema"]["properties"]["decisions"]["minItems"] == 2
            if self.calls == 2:
                assert "[0, 1]" in messages[-1].content
            return AIMessage(content="", tool_calls=[{
                "name": "submit_candidate_review", "id": "review", "type": "tool_call",
                "args": {"selected_meaning": "selected object", "anchor_supported": True,
                         "decisions": [{"index": n, "verdict": "supported", "reason": "visible evidence"}
                                       for n in ([0] if self.calls == 1 else [0, 1])]},
            }])

    verifier = RepairGateway()
    result = await GraphAgentRunner(store, None, RetrievalGateway(), EvidenceReviewer(verifier)).execute("repair-review", request)
    assert verifier.calls == 2
    assert [item["photo_id"] for item in result["items"]] == ["b", "c"]
    assert len(store.rows("SELECT * FROM events WHERE kind='review_validation_retry'")) == 1
    assert len(store.rows("SELECT * FROM events WHERE kind='results'")) == 1


@pytest.mark.asyncio
async def test_rejected_evidence_guides_one_new_retrieval_before_publication(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))

    class RefiningGateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls in (1, 3):
                if self.calls == 3:
                    assert "independent_visual_evidence" in json.dumps([m.content for m in messages])
                    assert not store.rows("SELECT * FROM events WHERE kind='results'")
                name, args = "inspect_photos", {"photo_ids": ["b" if self.calls == 1 else "c"]}
            else:
                name, args = "submit_exploration_result", {
                    "label": "선택 대상", "complete": True,
                    "items": [{"photo_id": "b" if self.calls == 2 else "c", "reason": "initial claim"}],
                }
            return AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": str(self.calls), "type": "tool_call",
            }])

    class ReviewGateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            return AIMessage(content="", tool_calls=[{
                "name": "submit_candidate_review", "id": "review", "type": "tool_call",
                "args": {"selected_meaning": "선택 대상", "anchor_supported": True, "decisions": [{
                    "index": 0, "verdict": "rejected" if self.calls == 1 else "supported", "reason": "독립 비교 근거",
                }]},
            }])

    primary, verifier = RefiningGateway(), ReviewGateway()
    result = await GraphAgentRunner(store, None, primary, EvidenceReviewer(verifier)).execute("refine", request)
    assert primary.calls == 4 and verifier.calls == 2
    assert [item["photo_id"] for item in result["items"]] == ["c"]
    events = store.rows("SELECT data FROM events WHERE kind='results'")
    assert len(events) == 1 and json.loads(events[0]["data"]) == result
