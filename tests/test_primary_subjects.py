import pytest
from pydantic import ValidationError

from connected_gallery.domain.models import Box, ExploreInput, PhotoAnalysis, Region, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store


def analysis(count):
    return PhotoAnalysis(photo_id="a", description="observed subjects", regions=[
        Region(id=f"r{index}", photo_id="a", box=Box(x=.1, y=.1, width=.2, height=.2),
               kind=("person", "object", "text", "place")[index % 4], label=f"subject {index}", evidence="visible")
        for index in range(count)
    ])


def test_new_submission_is_bounded_without_breaking_legacy_reads(store):
    legacy = analysis(5)
    store.save_analysis(legacy)
    assert len(PhotoAnalysis.model_validate(store.analysis("a")).regions) == 5
    toolkit = GalleryTools(store, None, RunRequest(role="analyst", photo_ids=["a"]), "main-subjects")
    toolkit.seen = {"a"}
    schema = next(s for s in toolkit.schemas() if s["name"] == "submit_photo_analysis")
    assert schema["input_schema"]["properties"]["regions"]["maxItems"] == 3
    with pytest.raises(ValidationError, match="at most 3"):
        toolkit.invoke("submit_photo_analysis", legacy.model_dump(mode="json"))
    assert [r["id"] for r in store.analysis("a")["regions"]] == [f"r{index}" for index in range(5)]
    with pytest.raises(ValidationError, match="at most 3"):
        toolkit.submit_photo_analysis(legacy)
    assert toolkit.result is None


def test_agent_chooses_which_subjects_survive_and_their_order(store):
    observed = analysis(5)
    chosen = observed.model_copy(update={"regions": [observed.regions[i] for i in (4, 1, 3)]})
    toolkit = GalleryTools(store, None, RunRequest(role="analyst", photo_ids=["a"]), "chosen")
    toolkit.seen = {"a"}
    toolkit.invoke("submit_photo_analysis", chosen.model_dump(mode="json"))
    saved = store.analysis("a")
    assert [r["id"] for r in saved["regions"]] == ["r4", "r1", "r3"]
    assert [r["kind"] for r in saved["regions"]] == ["person", "object", "place"]


def test_explorer_cannot_access_retired_global_spaces_but_legacy_organizer_can(store):
    explorer = GalleryTools(store, None, RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a"))), "explorer")
    assert "read_spaces" not in {s["name"] for s in explorer.schemas()}
    with pytest.raises(ValueError):
        explorer.invoke("read_spaces", {})
    organizer = GalleryTools(store, None, RunRequest(role="organizer"), "legacy")
    assert "read_spaces" in {s["name"] for s in organizer.schemas()}
    assert isinstance(organizer.invoke("read_spaces", {}), dict)
