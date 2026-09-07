import json

import pytest
from langchain_core.messages import AIMessage

from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import ExploreInput, PhotoAnalysis, RunRequest, SemanticAnchor
from test_contracts import store


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
@pytest.mark.parametrize("mode", ["filter", "reject_all", "wrong_crop", "malformed", "cancelled"])
async def test_only_independently_reviewed_candidates_reach_result_events(store, mode):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    store.save_analysis(PhotoAnalysis(photo_id="b", description="unsupported retrieval claim"))
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "review", "review", request.model_dump_json(), "running", None, None, 0,
    ))

    class ReviewGateway:
        async def invoke(self, messages, schemas):
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

    runner = GraphAgentRunner(store, None, RetrievalGateway(), EvidenceReviewer(ReviewGateway()))
    if mode in ("malformed", "cancelled"):
        with pytest.raises(ValueError):
            await runner.execute("review", request)
        assert not store.rows("SELECT * FROM events WHERE kind='results'")
    else:
        result = await runner.execute("review", request)
        assert result["items"] == ([{"photo_id": "b", "reason": "시각 근거 확인"}] if mode == "filter" else [])
        assert result["complete"] == (mode == "filter")
        events = store.rows("SELECT data FROM events WHERE kind='results'")
        assert len(events) == 1
        assert json.loads(events[0]["data"]) == result
