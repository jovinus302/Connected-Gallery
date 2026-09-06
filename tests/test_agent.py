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
