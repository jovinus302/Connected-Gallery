import io

import pytest
from PIL import Image

from connected_gallery.domain.models import Box, RunRequest, PhotoAnalysis
from connected_gallery.gallery_tools.registry import GalleryTools, GroundArgs, RegionArgs
from test_contracts import store


@pytest.mark.parametrize("crop", [None, Box(x=.2, y=.3, width=.5, height=.4)])
def test_grounding_uses_actual_preview_size_and_full_photo_coordinates(store, crop):
    # Asset metadata stays 100x100; inference uses a 200x80 preview (or a
    # separately uploaded 300x120 crop), never the metadata dimensions.
    payload = io.BytesIO()
    Image.new("RGB", (200, 80)).save(payload, "JPEG")
    store.put_image("a", payload.getvalue())
    if crop:
        payload = io.BytesIO()
        Image.new("RGB", (300, 120)).save(payload, "JPEG")
        store.put_region_image("a", crop, payload.getvalue())

    class Detector:
        calls = 0

        def ground(self, image, query):
            self.calls += 1
            w, h = image.size
            return {"boxes": [[w*.1, h*.2, w*.7, h*.8], [-w, -h, w*2, h*2],
                              [w*2, h*2, w*3, h*3]],
                    "text_labels": ["target", "whole", "outside"], "scores": [.9, .8, .7]}

    detector = Detector()
    toolkit = GalleryTools(store, detector, RunRequest(role="analyst", photo_ids=["a"]), "geometry")
    args = GroundArgs(photo_id="a", box=crop, query="target")
    result = toolkit.ground_regions(args)
    boxes = [d["box"] for d in result["detections"]]
    assert len(boxes) == 2
    expected = dict(x=.25, y=.38, width=.3, height=.24) if crop else dict(x=.1, y=.2, width=.6, height=.6)
    assert boxes[0] == pytest.approx(expected)
    assert boxes[1] == pytest.approx(crop.model_dump() if crop else dict(x=0, y=0, width=1, height=1))
    assert toolkit.ground_regions(args) == result
    assert detector.calls == 1  # Existing raw inference evidence remains reusable.


def test_face_boxes_map_to_full_photo_without_changing_face_index(store):
    class Faces:
        def faces(self, image):
            return {"faces": [{"box": dict(x=.1, y=.2, width=.6, height=.5), "vector": [1, 0]}]}

    toolkit = GalleryTools(store, Faces(), RunRequest(role="analyst", photo_ids=["a"]), "faces")
    crop = Box(x=.2, y=.3, width=.5, height=.4)
    result = toolkit.analyze_faces(RegionArgs(photo_id="a", box=crop))
    assert result["faces"][0]["index"] == 0
    assert result["faces"][0]["box"] == pytest.approx(dict(x=.25, y=.38, width=.3, height=.2))
    assert len(store.rows("SELECT key FROM vectors WHERE space='sface'")) == 1


def test_crop_observation_does_not_claim_whole_photo_caption(store):
    import json

    store.save_analysis(PhotoAnalysis(photo_id="a", description="An object outside the selected crop"))
    toolkit = GalleryTools(store, None, RunRequest(role="analyst", photo_ids=["a"]), "crop-context")
    whole = toolkit.image_block("a")
    crop = toolkit.image_block("a", Box(x=.2, y=.3, width=.5, height=.4))
    assert json.loads(whole[0]["text"])["analysis"]["description"]
    assert json.loads(crop[0]["text"])["analysis"] is None
    assert crop[1]["type"] == "image"
