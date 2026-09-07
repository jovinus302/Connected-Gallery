import asyncio

import pytest
from fastapi.testclient import TestClient

from connected_gallery.adapters.store import encoded
from connected_gallery.application.service import RunService
from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.auth import server_token
from connected_gallery.domain.models import ExploreInput, PhotoAnalysis, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import asset, store


class RecordingRunner:
    def __init__(self):
        self.roles = []

    async def execute(self, rid, request):
        self.roles.append(request.role)
        return {"label": "observed", "items": [], "complete": True}


def seed_space(store):
    value = {"id": "legacy", "name": "Saved context", "meaning": "Prior evidence",
             "items": [{"photo_id": "a", "reason": "Previously included"}]}
    store.write("INSERT INTO spaces VALUES(?,?)", ("legacy", encoded(value)))
    return value


def seed_run(store, rid, request, status, result=None):
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        rid, request.idempotency_key, request.model_dump_json(), status,
        encoded(result) if result is not None else None, None, 0,
    ))


def test_retired_spaces_api_cannot_read_generate_or_edit_existing_data(tmp_path):
    runner = RecordingRunner()
    app = create_app(tmp_path, lambda _: runner)
    with TestClient(app, headers={"Authorization": "Bearer " + server_token(tmp_path)}) as client:
        db = app.state.store
        db.upsert(asset())
        legacy = seed_space(db)
        request = RunRequest(role="organizer", idempotency_key="old-completed")
        seed_run(db, "old-completed", request, "completed", {"spaces": [legacy]})
        revision = db.revision
        runs = db.rows("SELECT * FROM runs")
        assert client.get("/spaces").status_code == 404
        assert "/spaces" not in client.get("/openapi.json").json()["paths"]
        # Reusing a completed organizer key must not bypass retirement.
        for key in ("new-request", "old-completed"):
            assert client.post("/runs", json={"role": "organizer", "idempotency_key": key}).status_code == 410
        for kind in ("space_include", "space_exclude"):
            assert client.post("/feedback", json={
                "kind": kind, "space_id": "legacy", "photo_id": "a",
            }).status_code == 410
        assert db.spaces() == [legacy]
        assert db.rows("SELECT * FROM runs") == runs
        assert db.rows("SELECT * FROM feedback") == []
        assert db.revision == revision
        assert runner.roles == []
        # Ordinary analytics and photo access remain available.
        assert client.post("/feedback", json={"kind": "metric", "value": "hop"}).status_code == 200
        assert client.get("/assets").json()["assets"][0]["id"] == "a"


@pytest.mark.asyncio
async def test_finishing_last_analysis_does_not_start_organizer(store):
    runner = RecordingRunner()
    service = RunService(store, runner)
    run = service.start(RunRequest(role="analyst", photo_ids=["a"]))
    await asyncio.wait_for(service.tasks[run["id"]], 2)
    assert service.get(run["id"])["status"] == "completed"
    assert runner.roles == ["analyst"]
    assert len(store.rows("SELECT * FROM runs")) == 1
    assert service.tasks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_status", ["queued", "running"])
async def test_recovery_retires_organizer_but_keeps_analysis_exploration_and_saved_data(store, legacy_status):
    legacy = seed_space(store)
    store.save_analysis(PhotoAnalysis(photo_id="a", description="Existing evidence"))
    store.cache_put("existing-context", {"items": [{"photo_id": "b", "reason": "observed"}]})
    cache = store.cache_get("existing-context")
    revision = store.revision
    runner = RecordingRunner()
    service = RunService(store, runner)
    legacy_result = {"spaces": [legacy]}
    seed_run(store, "legacy-run", RunRequest(role="organizer"), legacy_status, legacy_result)
    seed_run(store, "analysis-run", RunRequest(role="analyst", photo_ids=["b"]), "queued")
    seed_run(store, "explore-run", RunRequest(role="explorer", explore=ExploreInput(
        anchor=SemanticAnchor(photo_id="a"))), "running")
    await service.recover()
    assert set(service.tasks) == {"analysis-run", "explore-run"}
    await asyncio.wait_for(asyncio.gather(*list(service.tasks.values())), 2)
    retired = service.get("legacy-run")
    assert retired["status"] == "cancelled"
    assert "Spaces" in retired["error"]
    assert retired["result"] == legacy_result
    assert sorted(runner.roles) == ["analyst", "explorer"]
    assert service.get("analysis-run")["status"] == "completed"
    assert service.get("explore-run")["status"] == "completed"
    assert store.spaces() == [legacy]
    assert store.analysis("a")["description"] == "Existing evidence"
    assert store.cache_get("existing-context") == cache
    assert store.revision == revision
    await service.stop(preserve_pending=True)
    await service.recover()
    assert service.tasks == {}
    assert service.get("legacy-run")["status"] == "cancelled"


def test_direct_service_cannot_start_legacy_organizer(store):
    service = RunService(store, RecordingRunner())
    with pytest.raises(ValueError, match="Spaces"):
        service.start(RunRequest(role="organizer"))
    assert store.rows("SELECT * FROM runs") == []


def test_active_explorer_has_no_space_tools_and_still_has_context_search(store):
    toolkit = GalleryTools(store, None, RunRequest(role="explorer", explore=ExploreInput(
        anchor=SemanticAnchor(photo_id="a"))), "explore")
    names = {tool["name"] for tool in toolkit.schemas()}
    assert "read_spaces" not in names
    assert "submit_space_proposal" not in names
    assert {"search_time", "search_visual", "inspect_photos", "submit_exploration_result"} <= names
