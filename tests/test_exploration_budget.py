"""Offline observation turns remain bounded and cannot create empty proof."""
import base64
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from PIL import Image

from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor, PhotoAnalysis, Region, Box
from test_contracts import store
from test_submission_reminder import Verifier, reply

spec = importlib.util.spec_from_file_location("preparation_response_budget", Path(__file__).resolve().parents[1] / "scripts/prepare-demo.py")
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


@pytest.mark.parametrize("value", [True, False, None, 5, 13, 0, 7.0, "8"])
def test_runner_rejects_invalid_or_non_integer_response_budget(value):
    with pytest.raises(ValueError, match="integer from 6 to 12"):
        GraphAgentRunner(None, None, None, exploration_responses=value)


class ObservingGateway:
    def __init__(self, responses, empty=False):
        self.responses, self.empty = responses, empty
        self.calls, self.late_image_sizes = 0, []

    async def invoke(self, messages, schemas):
        self.calls += 1
        remaining = self.responses - self.calls + 1
        budget = messages[1].content
        assert f"{remaining} model responses" in budget
        assert f"{2 * self.responses - self.calls + 1} tool calls remain" in budget
        if self.calls < self.responses:
            assert "inspect_photos" in [schema["name"] for schema in schemas]
            # Simulate repeated partial progress before a genuinely new image
            # on response 7 (or 11 for the maximum supported configuration).
            if self.calls % 2 == 0:
                return reply("submit_exploration_result", {"label": "partial fixture", "complete": False,
                    "items": [{"photo_id": "b", "reason": "observed so far"}]}, self.calls)
            pid = "c" if self.calls == self.responses - 1 and self.responses > 6 else "b"
            return reply("inspect_photos", {"photo_ids": [pid]}, self.calls)
        assert [schema["name"] for schema in schemas] == ["submit_exploration_result"]
        last_tool = [message for message in messages if isinstance(message, ToolMessage)][-1]
        assert isinstance(last_tool.content, list)
        self.late_image_sizes = [Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size
                                 for block in last_tool.content if block.get("type") == "image"]
        items = [] if self.empty else [{"photo_id": "c" if self.responses > 6 else "b", "reason": "observed fixture"}]
        return reply("submit_exploration_result", {"label": "fixture", "items": items,
                     "complete": self.responses > 6}, self.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [6, 8, 12])
async def test_default_six_and_extended_observation_use_real_tool_images(store, responses):
    image = io.BytesIO()
    Image.new("RGB", (63, 47), "blue").save(image, "JPEG")
    store.put_image("c", image.getvalue())
    gateway = ObservingGateway(responses)
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    options = {} if responses == 6 else {"exploration_responses": responses}
    runner = GraphAgentRunner(store, None, gateway, EvidenceReviewer(Verifier()), **options)
    result = await runner.execute("bounded", RunRequest(role="explorer", explore=query))
    assert gateway.calls == runner.exploration_responses == responses
    assert result["complete"] is (responses > 6)
    inspections = [json.loads(row["data"]) for row in store.rows("SELECT data FROM events WHERE kind='tool'")]
    if responses == 6:
        assert all("c" not in event["seen"] for event in inspections)
        assert gateway.late_image_sizes == [(100, 100)]
    else:
        assert all("c" not in event["seen"] for event in inspections if event["name"] == "initial_photo")
        observed = [event for event in inspections if event["name"] == "inspect_photos"]
        assert all("c" not in event["seen"] for event in observed[:-1])
        assert "c" in observed[-1]["seen"]
        assert gateway.late_image_sizes == [(63, 47)]


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [6, 12])
async def test_batched_calls_cannot_exceed_twice_response_budget(store, responses):
    class ExcessCalls:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "id": str(n), "type": "tool_call", "name": "inspect_photos", "args": {"photo_ids": ["b"]}
                } for n in range(2 * responses + 3)])
            assert [schema["name"] for schema in schemas] == ["submit_exploration_result"]
            assert "Tool budget reserved for submission" in str([message.content for message in messages])
            return reply("submit_exploration_result", {"label": "bounded", "complete": True,
                "items": [{"photo_id": "b", "reason": "observed"}]}, "terminal")

    gateway = ExcessCalls()
    result = await GraphAgentRunner(store, None, gateway, EvidenceReviewer(Verifier()),
        exploration_responses=responses).execute("too-many-tools", RunRequest(role="explorer",
            explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"))))
    executed = [json.loads(row["data"]) for row in store.rows("SELECT data FROM events WHERE kind='tool_timing'")]
    assert gateway.calls == 2 and result["complete"]
    assert len(executed) == 2 * responses
    assert sum(event["name"] == "inspect_photos" for event in executed) == 2 * responses - 1


@pytest.mark.asyncio
async def test_extended_complete_empty_still_requires_independent_negative_proof(store):
    class UnavailableJudge:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            assert schemas[0]["name"] == "submit_empty_review"
            raise RuntimeError("isolated fixture review unavailable")

    judge = UnavailableJudge()
    gateway = ObservingGateway(8, empty=True)
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    result = await GraphAgentRunner(store, None, gateway, EvidenceReviewer(judge),
        result_organizer=ResultOrganizer(None), exploration_responses=8).execute(
            "no-negative-proof", RunRequest(role="explorer", explore=query))
    assert gateway.calls == 8 and judge.calls == 1
    assert result["items"] == [] and result["complete"] is False
    assert result["grouping_status"] == "failed" and "empty_evidence" not in result
    service = RunService(store, None)
    # Even a caller forging a complete flag cannot make a proofless row ready.
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=query)),
                    {**result, "complete": True, "grouping_status": "ready"})
    assert service.ready(query)["state"] == "pending"


def test_cli_defaults_to_six_and_accepts_all_bounded_choices():
    parser = preparation.argument_parser()
    assert parser.parse_args(["--samples", "unused"]).exploration_responses == 6
    for value in range(6, 13):
        assert parser.parse_args(["--samples", "unused", "--exploration-responses", str(value)]).exploration_responses == value


@pytest.mark.parametrize("value", ["5", "13", "0", "8.0", "true"])
def test_cli_rejects_invalid_response_budget(value):
    with pytest.raises(SystemExit) as error:
        preparation.argument_parser().parse_args(["--samples", "unused", "--exploration-responses", value])
    assert error.value.code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 5, 13, 8.0, "8"])
async def test_programmatic_cli_rejects_before_environment_or_database_construction(value):
    # No remaining arguments exist: invalid budget must fail before any work.
    with pytest.raises(ValueError, match="integer from 6 to 12"):
        await preparation.main(SimpleNamespace(exploration_responses=value))


@pytest.mark.asyncio
@pytest.mark.parametrize("responses", [6, 10])
async def test_cli_wires_runner_and_records_global_and_per_run_budget(store, monkeypatch, capsys, responses):
    from connected_gallery.adapters import models, proxy
    from connected_gallery.application import demo_profile, service
    for photo in store.photos():
        store.save_analysis(PhotoAnalysis(photo_id=photo.id, description="fixture",
            regions=[Region(id="r", photo_id="a", box=Box(x=0, y=0, width=1, height=1),
                            kind="object", label="fixture", evidence="visible")] if photo.id == "a" else []))
    constructed = []

    class PreparedService:
        def __init__(self, current_store, runner):
            constructed.append(runner)

        def ready(self, query):
            return {"state": "pending"}

        def start(self, request):
            return {"id": "fixture-run"}

        def get(self, run_id):
            return {"id": run_id, "status": "incomplete", "result": {"items": [], "complete": False}}

        async def stop(self, **kwargs):
            pass

    monkeypatch.setattr(models, "LocalModels", lambda root: None)
    monkeypatch.setattr(proxy, "ProxyGateway", lambda **kwargs: SimpleNamespace(primary="fixture-model"))
    monkeypatch.setattr(service, "RunService", PreparedService)
    monkeypatch.setattr(demo_profile, "prepare_demo_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(demo_profile, "connection_models", lambda primary: [primary])
    for name in ("CG_AUTO_ORGANIZE", "CG_ANALYSIS_CONCURRENCY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, "fixture")
    args = preparation.argument_parser().parse_args(["--samples", "unused", "--data-dir", str(store.root),
        "--stage", "prepare", "--exploration-responses", str(responses)])
    await preparation.main(args)
    assert len(constructed) == 1 and constructed[0].exploration_responses == responses
    report = json.loads((store.root / "preparation-report.json").read_text(encoding="utf-8"))
    assert report["exploration_responses"] == report["connections"]["r"]["exploration_responses"] == responses
    assert report["exploration_tool_calls"] == report["connections"]["r"]["exploration_tool_calls"] == 2 * responses
    emitted = json.loads(capsys.readouterr().out.strip())
    assert emitted["exploration_responses"] == responses and emitted["exploration_tool_calls"] == 2 * responses
