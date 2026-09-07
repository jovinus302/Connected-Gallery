import json

import pytest
from langchain_core.messages import AIMessage

from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from test_contracts import store


def reply(name, args, turn):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(turn), "type": "tool_call"}])


class Verifier:
    async def invoke(self, messages, schemas):
        return reply("submit_candidate_review", {"selected_meaning": "source", "anchor_supported": True,
            "decisions": [{"index": 0, "verdict": "supported", "reason": "independent evidence"}]}, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("plain_turn", [2, 5])
async def test_explorer_plain_response_gets_one_reminder_inside_original_budget(store, plain_turn):
    class Gateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls < plain_turn:
                return reply("inspect_photos", {"photo_ids": ["b"]}, self.calls)
            if self.calls == plain_turn:
                return AIMessage(content="I have found a relevant photo")
            assert "No exploration result has been submitted" in str([m.content for m in messages])
            if plain_turn == 5:
                assert [s["name"] for s in schemas] == ["submit_exploration_result"]
            return reply("submit_exploration_result", {"label": "confirmed", "complete": True,
                "items": [{"photo_id": "b", "reason": "observed"}]}, self.calls)

    gateway = Gateway()
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await GraphAgentRunner(store, None, gateway, EvidenceReviewer(Verifier())).execute("reminder", request)
    assert gateway.calls == plain_turn + 1 <= 6
    assert [i["photo_id"] for i in result["items"]] == ["b"]
    reminders = store.rows("SELECT data FROM events WHERE kind='submission_reminder'")
    assert len(reminders) == 1
    assert json.loads(reminders[0]["data"])["turns_used"] == plain_turn


@pytest.mark.asyncio
async def test_repeated_plain_responses_do_not_create_fake_completion(store):
    class Gateway:
        calls = 0

        async def invoke(self, *args):
            self.calls += 1
            return AIMessage(content="A plain message without submission")

    gateway = Gateway()
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    with pytest.raises(RuntimeError, match="without a valid submitted result"):
        await GraphAgentRunner(store, None, gateway, EvidenceReviewer(Verifier())).execute("no-submit", request)
    assert gateway.calls == 2
    assert len(store.rows("SELECT data FROM events WHERE kind='submission_reminder'")) == 1
    assert not store.rows("SELECT data FROM events WHERE kind='results'")


@pytest.mark.asyncio
async def test_missing_submission_after_exhausted_budget_does_not_get_extra_turn(store):
    class Gateway:
        calls = 0

        async def invoke(self, *args):
            self.calls += 1
            if self.calls < 6:
                return reply("inspect_photos", {"photo_ids": ["b"]}, self.calls)
            return AIMessage(content="No terminal submission")

    gateway = Gateway()
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    with pytest.raises(RuntimeError, match="without a valid submitted result"):
        await GraphAgentRunner(store, None, gateway, EvidenceReviewer(Verifier())).execute("spent", request)
    assert gateway.calls == 6
    assert not store.rows("SELECT data FROM events WHERE kind IN ('submission_reminder','results')")


@pytest.mark.asyncio
async def test_reminded_explorer_can_honestly_submit_incomplete_empty_result(store):
    class Gateway:
        calls = 0

        async def invoke(self, *args):
            self.calls += 1
            if self.calls == 2:
                return reply("submit_exploration_result", {"label": "근거가 부족해요", "items": [], "complete": False}, self.calls)
            return AIMessage(content="Evidence unavailable")

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await GraphAgentRunner(store, None, Gateway(), EvidenceReviewer(Verifier())).execute("honest-empty", request)
    assert result["items"] == [] and result["complete"] is False
    assert len(store.rows("SELECT data FROM events WHERE kind='submission_reminder'")) == 1
