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
    with TestClient(app) as client:
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
