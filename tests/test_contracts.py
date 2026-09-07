import io
import asyncio
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError
from connected_gallery.domain.models import *
from connected_gallery.adapters.store import Store
from connected_gallery.gallery_tools.registry import GalleryTools
from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.auth import server_token


def asset(pid="a", year=2020, source="media_store"):
    return PhotoAsset(
        id=pid,
        device_id="device",
        version="1",
        captured_at=f"{year}-06-01T12:00:00+00:00",
        time_source=source,
        width=100,
        height=100,
    )


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    for pid, year in [("a", 2020), ("b", 2015), ("c", 2020)]:
        s.upsert(asset(pid, year))
        b = io.BytesIO()
        Image.new("RGB", (100, 100), "red").save(b, "JPEG")
        s.put_image(pid, b.getvalue())
    yield s
    s.close()


def test_region_bounds():
    with pytest.raises(ValidationError):
        Box(x=0.8, y=0.2, width=0.3, height=0.2)


def test_year_excludes_unknown_capture_time(store):
    store.upsert(asset("d", 2020, "modified"))
    assert {p.id for p in store.photos(2020)} == {"a", "c"}


def test_vector_search_filters_before_top_k(store):
    store.vector("a", "a", "test", [1, 0])
    store.vector("b", "b", "test", [0.9, 0.1])
    assert store.search("test", [1, 0], {"b"}, 1)[0]["photo_id"] == "b"
    assert store.search("other", [1, 0], {"b"}, 1) == []


def test_candidate_limit_counts_distinct_photos_after_region_indexing(store):
    store.vector("b:whole", "b", "test", [1, 0])
    store.vector("b:crop1", "b", "test", [.99, .01])
    store.vector("b:crop2", "b", "test", [.98, .02])
    store.vector("c:whole", "c", "test", [.8, .2])
    found = store.search("test", [1, 0], {"b", "c"}, 2)
    assert [r["photo_id"] for r in found] == ["b", "c"]
    assert found[0]["artifact"] == "b:whole"


def test_explorer_rejects_unseen_and_wrong_year(store):
    req = RunRequest(
        role="explorer",
        explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"), year=2015),
    )
    tools = GalleryTools(store, None, req, "test")
    tools.seen = {"a"}
    with pytest.raises(ValueError):
        tools.submit_exploration_result(
            ExplorationResult(
                label="test", items=[ResultItem(photo_id="b", reason="x")]
            )
        )
    tools.seen.add("b")
    tools.submit_exploration_result(
        ExplorationResult(label="test", items=[ResultItem(photo_id="b", reason="x")])
    )
    tools.seen.add("c")
    with pytest.raises(ValueError):
        tools.submit_exploration_result(
            ExplorationResult(
                label="test", items=[ResultItem(photo_id="c", reason="x")]
            )
        )


def test_delete_and_version_invalidate_artifacts(store):
    store.save_analysis(PhotoAnalysis(photo_id="a", description="wine"))
    store.vector("a", "a", "test", [1, 0])
    store.cache_put("test", {"items": ["a"]})
    store.upsert(asset().model_copy(update={"version": "2"}))
    assert store.analysis("a") is None
    assert store.search("test", [1, 0], {"a"}) == []
    assert store.cache_get("test") is None
    assert not store.image_path("a").exists()
    store.delete("a")
    with pytest.raises(ValueError):
        store.photo("a")


def test_organizer_requires_coverage_and_preserves_edits(store):
    req = RunRequest(role="organizer")
    tools = GalleryTools(store, None, req, "test")
    proposal = SpaceProposal(
        spaces=[
            Space(
                id="s",
                name="맥락",
                meaning="사용 목적",
                items=[ResultItem(photo_id="a", reason="evidence")],
            )
        ]
    )
    with pytest.raises(ValueError):
        tools.submit_space_proposal(proposal)
    tools.list_photos(
        __import__(
            "connected_gallery.gallery_tools.registry", fromlist=["ListArgs"]
        ).ListArgs()
    )
    tools.submit_space_proposal(proposal)
    f = Feedback(kind="space_exclude", space_id="s", photo_id="a")
    store.write("INSERT INTO feedback VALUES(?,?)", (f.event_id, f.model_dump_json()))
    tools.submit_space_proposal(proposal)
    assert store.spaces()[0]["items"] == []


class SubmittedRunner:
    async def execute(self, rid, request):
        await asyncio.sleep(0.01)
        return {"label": "test", "items": [], "complete": True}


def test_api_runs_and_idempotency(tmp_path):
    app = create_app(tmp_path, lambda s: SubmittedRunner())
    with TestClient(app, headers={"Authorization": "Bearer " + server_token(tmp_path)}) as client:
        assert (
            client.post(
                "/assets/sync", json={"assets": [asset().model_dump(mode="json")]}
            ).status_code
            == 200
        )
        request = RunRequest(
            role="explorer",
            explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")),
            idempotency_key="one",
        ).model_dump(mode="json")
        first = client.post("/runs", json=request).json()
        second = client.post("/runs", json=request).json()
        assert first["id"] == second["id"]
        request["explore"]["year"] = 2015
        assert client.post("/runs", json=request).status_code == 400
        assert client.delete("/assets/a").status_code == 200
        assert client.get("/assets/a/analysis").status_code == 400


def test_sync_snapshot_returns_only_requested_current_analysis_and_active_jobs(tmp_path):
    app = create_app(tmp_path, lambda s: SubmittedRunner())
    with TestClient(app, headers={"Authorization": "Bearer " + server_token(tmp_path)}) as client:
        s = app.state.store
        for pid in ("a", "b", "c"):
            s.upsert(asset(pid))
        for pid in ("a", "b"):
            s.save_analysis(PhotoAnalysis(photo_id=pid, description="existing evidence"))
        request = RunRequest(role="analyst", photo_ids=["c"])
        s.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
            "active-c", "active-c", request.model_dump_json(), "queued", None, None, 0,
        ))
        response = client.post("/assets/sync", json={"assets": [
            asset("a").model_dump(mode="json"), asset("c").model_dump(mode="json"),
        ]}).json()
        assert [a["photo_id"] for a in response["analyses"]] == ["a"]
        assert response["active_analysis_ids"] == ["c"]
        assert s.analysis("b") is not None
        changed = asset("a").model_copy(update={"version": "2"})
        response = client.post("/assets/sync", json={"assets": [changed.model_dump(mode="json")]}).json()
        assert response["analyses"] == []
        assert response["active_analysis_ids"] == []


def test_empty_index_cannot_claim_complete_no_results(store):
    request = RunRequest(
        role="explorer",
        explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"), year=2015),
    )
    toolkit = GalleryTools(store, None, request, "empty-index")
    toolkit.seen = {"a"}
    with pytest.raises(ValueError):
        toolkit.submit_exploration_result(ExplorationResult(label="empty", items=[]))
    toolkit.submit_exploration_result(
        ExplorationResult(label="partial", items=[], complete=False)
    )
    assert toolkit.result["complete"] is False


def test_exact_region_preview_and_delete(store):
    box = Box(x=0.1, y=0.1, width=0.2, height=0.2)
    data = io.BytesIO()
    Image.new("RGB", (200, 200), "blue").save(data, "JPEG")
    store.put_region_image("a", box, data.getvalue())
    revision = store.revision
    store.put_region_image("a", box, data.getvalue())
    assert store.revision == revision
    assert store.read_image("a", box).getpixel((20, 20))[2] > 240
    store.delete("a")
    assert not store.rows("SELECT * FROM artifacts WHERE photo_id=?", ("a",))


def test_version_change_during_run_blocks_submission(store):
    request = RunRequest(role="analyst", photo_ids=["a"])
    toolkit = GalleryTools(store, None, request, "stale")
    toolkit.seen = {"a"}
    store.upsert(asset().model_copy(update={"version": "new"}))
    with pytest.raises(ValueError):
        toolkit.submit_photo_analysis(PhotoAnalysis(photo_id="a", description="stale"))


def test_catalog_is_bounded_but_inspection_keeps_evidence(store):
    from connected_gallery.gallery_tools.registry import ListArgs, InspectArgs

    store.save_analysis(
        PhotoAnalysis(photo_id="a", description="a" * 2000, ocr="b" * 2000)
    )
    tools = GalleryTools(store, None, RunRequest(role="organizer"), "compact")
    item = next(
        x for x in tools.list_photos(ListArgs())["photos"] if x["photo_id"] == "a"
    )
    assert item["summary"]["truncated"] is True
    assert len(item["summary"]["description_excerpt"]) == 160
    inspected = tools.inspect_photos(InspectArgs(photo_ids=["a"]))
    assert "a" * 2000 in inspected[0]["text"]


def test_time_candidates_keep_user_year_and_require_visual_verification(store):
    from connected_gallery.gallery_tools.registry import TimeArgs
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"), year=2015))
    toolkit = GalleryTools(store, None, request, "time")
    toolkit.seen = {"a"}
    candidates = toolkit.search_time(TimeArgs(start="2010-01-01T00:00:00Z", end="2030-01-01T00:00:00Z"))
    assert [x["photo_id"] for x in candidates["candidates"]] == ["b"]
    with pytest.raises(ValueError, match="Inspect candidate"):
        toolkit.submit_exploration_result(ExplorationResult(label="same moment", items=[ResultItem(photo_id="b", reason="time proximity")]))
    with pytest.raises(ValidationError, match="timezone-aware"):
        TimeArgs(start="2015-01-01T00:00:00", end="2015-01-02T00:00:00")


def test_time_candidates_distinguish_modified_timestamp(store):
    from connected_gallery.gallery_tools.registry import TimeArgs
    store.upsert(asset("b", 2015, "modified").model_copy(update={"version": "2"}))
    toolkit = GalleryTools(store, None, RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"))), "time-unknown")
    result = toolkit.search_time(TimeArgs(start="2010-01-01T00:00:00Z", end="2030-01-01T00:00:00Z"))
    assert {x["photo_id"] for x in result["candidates"]} == {"c"}
    assert result["unknown_capture_time_count"] == 1


def test_explorer_cannot_follow_back_to_its_own_anchor(store):
    toolkit = GalleryTools(store, None, RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"))), "self-result")
    toolkit.seen = {"a"}
    assert "a" not in toolkit.candidate_ids()
    with pytest.raises(ValueError, match="already being viewed"):
        toolkit.submit_exploration_result(ExplorationResult(label="대상", items=[ResultItem(photo_id="a", reason="same image")]))
