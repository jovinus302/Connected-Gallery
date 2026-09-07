"""Offline two-sided comparison fixtures; no personal/demo photos or live models."""
import base64
import io
import json

import pytest
from langchain_core.messages import AIMessage
from PIL import Image, ImageDraw

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.context import ContextTools
from test_contracts import store
from test_photo_context import PhotoContextAgent, observation_plan, request


MATCH = "두 칸의 색이 모두 같습니다."
DIFFERENCE = "왼쪽 색은 같고 오른쪽 색은 다릅니다."
CANDIDATE_ONLY = "후보 사진의 오른쪽 칸은 초록색입니다."


def pattern(store, pid, left, right):
    image = Image.new("RGB", (100, 100), left)
    ImageDraw.Draw(image).rectangle((50, 0, 99, 99), fill=right)
    output = io.BytesIO()
    image.save(output, "PNG")
    store.put_image(pid, output.getvalue())


def proposal(reason=MATCH, ids=("b", "c")):
    return {"summary": "사진에 보이는 색 배열을 비교해 볼 수 있습니다.", "complete": True,
            "groups": [{"id": "colors", "title": "색 배열 비교", "reason": reason, "photo_ids": list(ids)}]}


def observed_tools(store, run_id):
    tools = ContextTools(store, None, request(), run_id)
    tools.image_block("a")
    tools.invoke("list_photos", {})
    tools.invoke("plan_photo_context", observation_plan(("b", "c")))
    return tools


class PixelComparisonGateway:
    """Fixture judge compares two visible positions from each supplied actual image."""
    def __init__(self, repair="unchanged"):
        self.repair = repair
        self.planning_calls = self.review_calls = 0
        self.feedback_seen = None
        self.observations = []

    @staticmethod
    def color(pixel):
        if max(pixel) - min(pixel) < 40:
            return "unobservable"
        return ("red", "green", "blue")[max(range(3), key=lambda index: pixel[index])]

    async def invoke(self, messages, schemas):
        name = schemas[0]["name"]
        if name != "submit_context_review":
            self.planning_calls += 1
            if self.planning_calls == 1:
                return AIMessage(content="", tool_calls=[{"name": "plan_photo_context", "id": "plan", "type": "tool_call",
                    "args": observation_plan(("b", "c"))}])
            value = proposal(MATCH + " 실제 동일 개체인지는 확인되지 않습니다.")
            if self.planning_calls > 2:
                for message in messages:
                    if isinstance(message.content, str) and "independent_context_review" in message.content:
                        self.feedback_seen = json.loads(message.content)["independent_context_review"]["visual_review"]
                if self.repair == "observed_difference":
                    # The fixture proposer elects to retain both photos with distinct supported claims.
                    value = proposal()
                    value["groups"] = [
                        {"id": "contrast", "title": "색 차이 비교", "reason": DIFFERENCE, "photo_ids": ["b"]},
                        {"id": "agreement", "title": "색 일치 비교", "reason": MATCH, "photo_ids": ["c"]}]
                elif self.repair == "caveat_only":
                    value["groups"][0]["reason"] += " 전체적으로 비슷해 보일 수 있습니다."
            return AIMessage(content="", tool_calls=[{"name": "submit_photo_context", "id": f"submit-{self.planning_calls}",
                                                       "type": "tool_call", "args": value}])

        self.review_calls += 1
        system = messages[0].content
        assert "first observe that attribute in SOURCE" in system
        assert "THIS candidate" in system and "One matching attribute cannot substantiate another" in system
        assert "disclaimer about uncertain identity does not repair" in system
        assert "candidate-only descriptions" in system and "do not" in system
        assert len(messages) == 2  # No earlier review verdict or proposer conversation is recycled.
        assert "prior-review-marker" not in encoded([message.content for message in messages])
        pictures, source_id, current_id = {}, None, None
        for block in messages[1].content[:-1]:
            if block["type"] == "text":
                metadata = json.loads(block["text"])
                current_id = metadata["photo_id"]
                if metadata["source"]:
                    assert source_id is None
                    source_id = current_id
            elif block["type"] == "image":
                with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as image:
                    pictures[current_id] = tuple(self.color(image.convert("RGB").getpixel(point))
                                                 for point in ((25, 25), (75, 25)))
        assert source_id is not None and set(pictures) == {"a", "b", "c"}
        self.observations.append(pictures)
        value = json.loads(messages[1].content[-1]["text"])["proposed_context"]
        members = []
        for index, group in enumerate(value["groups"]):
            for pid in group["photo_ids"]:
                source, candidate = pictures[source_id], pictures[pid]
                if "unobservable" in (*source, *candidate):
                    verdict = "uncertain"
                elif group["reason"].startswith(DIFFERENCE):
                    verdict = "supported" if source[0] == candidate[0] and source[1] != candidate[1] else "rejected"
                elif group["reason"].startswith(CANDIDATE_ONLY):
                    verdict = "supported" if candidate[1] == "green" else "rejected"
                else:
                    assert group["reason"].startswith(MATCH)
                    verdict = "supported" if source == candidate else "rejected"
                members.append({"group_id": group["id"], "photo_id": pid, "verdict": verdict,
                    "reason": f"/groups/{index}/reason 색 속성: 원본={source}, 후보={candidate}. 두 관찰을 대조했습니다."})
        return AIMessage(content="", tool_calls=[{"name": "submit_context_review", "id": f"review-{self.review_calls}",
            "type": "tool_call", "args": {"summary_supported": True, "summary_reason": "비교할 수 있다는 범위만 설명합니다.",
                "members": members, "empty_supported": False, "context_scope_supported": True,
                "context_scope_reason": "두 칸의 실제 색을 확인했습니다."}}])


@pytest.fixture
def colored(store):
    pattern(store, "a", "red", "blue")
    pattern(store, "b", "red", "green")
    pattern(store, "c", "red", "blue")
    return store


@pytest.mark.asyncio
@pytest.mark.parametrize("obscured,expected", [(False, "rejected"), (True, "uncertain")])
async def test_each_candidate_is_compared_to_source_for_every_asserted_attribute(colored, obscured, expected):
    if obscured:
        pattern(colored, "b", "red", "gray")
    gateway = PixelComparisonGateway()
    tools = observed_tools(colored, "pairwise")
    colored.event("prior", "context_evidence_review", {"reason": "prior-review-marker", "supported": True})
    agent = PhotoContextAgent(colored, None, gateway)
    supported, feedback = await agent._review(tools, proposal(MATCH + " 동일 개체 여부는 모릅니다.", ("c", "b")), 1)
    verdicts = {m["photo_id"]: m for m in feedback["members"]}
    assert supported is False and verdicts["b"]["verdict"] == expected and verdicts["c"]["verdict"] == "supported"
    assert "원본=" in verdicts["b"]["reason"] and "후보=" in verdicts["b"]["reason"]
    assert not colored.rows("SELECT 1 FROM events WHERE kind='context_result'")


@pytest.mark.asyncio
async def test_candidate_only_description_does_not_invent_the_same_source_attribute(colored):
    gateway = PixelComparisonGateway()
    supported, feedback = await PhotoContextAgent(colored, None, gateway)._review(
        observed_tools(colored, "candidate-only"), proposal(CANDIDATE_ONLY, ("b",)), 1)
    assert supported is True and feedback["members"][0]["verdict"] == "supported"
    assert gateway.observations[0]["a"][1] != gateway.observations[0]["b"][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", ["unchanged", "caveat_only", "observed_difference"])
async def test_existing_repair_budget_requires_corrected_comparison_not_a_generic_caveat(colored, repair):
    gateway = PixelComparisonGateway(repair)
    agent = PhotoContextAgent(colored, None, gateway)
    if repair == "observed_difference":
        result = await agent.execute("comparison-repair", request())
        assert result["complete"] and {pid for group in result["groups"] for pid in group["photo_ids"]} == {"b", "c"}
        assert next(group for group in result["groups"] if group["photo_ids"] == ["b"])["reason"] == DIFFERENCE
        assert result["evidence"]["inspected_photo_ids"] == ["a", "b", "c"]
    else:
        with pytest.raises(RuntimeError, match="failed independent review"):
            await agent.execute("comparison-repair", request())
        assert not colored.rows("SELECT 1 FROM events WHERE kind='context_result'")
    assert gateway.review_calls == 2 and gateway.planning_calls == 3
    assert next(item for item in gateway.feedback_seen["members"] if item["photo_id"] == "b")["verdict"] == "rejected"
