import sqlite3
import pytest
from connected_gallery.application.indexing import AnalysisIndexing
from connected_gallery.domain.models import PhotoAnalysis, RunRequest, Region, Box
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store


class Models:
    visual_space = "visual-test"
    text_space = "text-test"

    def __init__(self):
        self.calls = 0

    def image(self, image):
        self.calls += 1
        return self.visual_space, [1, 0]

    def text(self, text, query=False):
        self.calls += 1
        return self.text_space, [0, 1]


def test_repair_indexes_existing_evidence_once(store):
    original = PhotoAnalysis(photo_id="a", description="모델이 관찰한 설명", ocr="읽은 글씨")
    store.save_analysis(original)
    models = Models()
    indexing = AnalysisIndexing(store, models)
    assert indexing.report()["ready_count"] == 0
    assert indexing.repair("a")["indexes_added"] == 2
    assert indexing.report()["ready_count"] == 1
    revision = store.revision
    assert indexing.repair("a")["indexes_added"] == 0
    assert models.calls == 2
    assert store.revision == revision
    assert store.analysis("a") == original.model_dump(mode="json")


def test_index_failure_cannot_commit_completed_analysis(store):
    class FailedModels(Models):
        def text(self, text, query=False):
            raise RuntimeError("Encoder unavailable")

    toolkit = GalleryTools(store, FailedModels(), RunRequest(role="analyst", photo_ids=["a"]), "failed-index")
    toolkit.seen = {"a"}
    with pytest.raises(RuntimeError, match="Encoder unavailable"):
        toolkit.invoke("submit_photo_analysis", {"photo_id": "a", "description": "관찰 결과"})
    assert toolkit.result is None
    assert store.analysis("a") is None
    assert not store.rows("SELECT * FROM vectors")


def test_analysis_and_vector_writes_rollback_together(store):
    store.db.execute("CREATE TRIGGER fail_index BEFORE INSERT ON vectors BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END")
    analysis = PhotoAnalysis(photo_id="a", description="must roll back")
    with pytest.raises(sqlite3.IntegrityError):
        store.save_analysis(analysis, vectors=[("key", "a", "test", [1, 0])], expected_version="1")
    assert store.analysis("a") is None
    assert not store.rows("SELECT * FROM evidence_fts")
    assert not store.rows("SELECT * FROM vectors")


def test_index_commit_rejects_changed_photo_version(store):
    analysis = PhotoAnalysis(photo_id="a", description="stale")
    vectors = AnalysisIndexing(store, Models()).prepare(analysis, "1")
    store.upsert(store.photo("a").model_copy(update={"version": "2"}))
    with pytest.raises(ValueError, match="changed during indexing"):
        store.save_analysis(analysis, vectors=vectors, expected_version="1")
    assert store.analysis("a") is None
    assert not store.rows("SELECT * FROM vectors")


def test_repair_cannot_overwrite_concurrent_user_correction(store):
    store.save_analysis(PhotoAnalysis(photo_id="a", description="original"))

    class ConcurrentEdit(Models):
        def text(self, text, query=False):
            store.save_analysis(PhotoAnalysis(photo_id="a", description="user correction"))
            return super().text(text, query=query)

    with pytest.raises(ValueError, match="Analysis changed"):
        AnalysisIndexing(store, ConcurrentEdit()).repair("a")
    assert store.analysis("a")["description"] == "user correction"
    assert not store.rows("SELECT * FROM vectors")


def selected_analysis(box=None):
    box = box or Box(x=.1, y=.2, width=.3, height=.4)
    return PhotoAnalysis(photo_id="a", description="agent evidence", regions=[
        Region(photo_id="a", box=box, kind="object", label="selected object", evidence="observed"),
        Region(photo_id="a", box=box, kind="text", label="selected text", evidence="observed"),
        Region(photo_id="a", box=Box(x=0, y=0, width=1, height=1), kind="place", label="scene", evidence="observed"),
    ])


def test_selected_regions_are_indexed_once_and_full_scene_reuses_photo(store):
    analysis = selected_analysis()
    store.save_analysis(analysis)
    models = Models()
    index = AnalysisIndexing(store, models)
    assert index.repair("a")["indexes_added"] == 3
    assert models.calls == 3
    assert index.repair("a")["indexes_added"] == 0
    assert index.report()["indexed_selected_region_count"] == 1
    assert store.analysis("a") == analysis.model_dump(mode="json")


def test_region_and_text_corrections_remove_only_obsolete_derived_vectors(store):
    index = AnalysisIndexing(store, Models())
    original = selected_analysis()
    store.save_analysis(original)
    index.repair("a")
    old_keys = set(index.keys(original, "1"))
    store.vector("a:crop:explicit-tool", "a", "visual-test", [1, 0])
    corrected = selected_analysis(Box(x=.2, y=.3, width=.3, height=.4))
    corrected.description = "corrected evidence"
    store.save_analysis(corrected)
    new_keys = set(index.keys(corrected, "1"))
    assert all(not store.has_vector(key) for key in old_keys - new_keys)
    assert store.has_vector("a:crop:explicit-tool")
    assert index.report()["ready_count"] == 0
    assert index.repair("a")["indexes_added"] == 2
    assert index.report()["ready_count"] == 1


def test_failed_selected_crop_index_does_not_commit_partial_analysis(store):
    class FailedCrop(Models):
        def image(self, image):
            if image.size != (100, 100):
                raise RuntimeError("Crop encoding failed")
            return super().image(image)

    toolkit = GalleryTools(store, FailedCrop(), RunRequest(role="analyst", photo_ids=["a"]), "crop-failure")
    toolkit.seen = {"a"}
    with pytest.raises(RuntimeError, match="Crop encoding"):
        toolkit.submit_photo_analysis(selected_analysis())
    assert store.analysis("a") is None
    assert not store.rows("SELECT * FROM vectors")
