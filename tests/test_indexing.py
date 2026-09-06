import sqlite3
import pytest
from connected_gallery.application.indexing import AnalysisIndexing
from connected_gallery.domain.models import PhotoAnalysis, RunRequest
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
