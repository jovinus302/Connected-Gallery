"""Fabricated negative evidence for isolated tests; never application input."""
import os
from connected_gallery.domain.empty_evidence import EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY


def negative_proof(store, explore):
    source = store.photo(explore.anchor.photo_id)
    eligible = sorted(photo.id for photo in store.photos(explore.year) if photo.id != source.id)
    ids = [source.id, *eligible]
    return {"spec": EMPTY_EVIDENCE_SPEC, "policy": EMPTY_EVIDENCE_POLICY, "reviewed": True,
            "anchor_supported": True, "scope_sufficient": True, "selected_meaning": "Test selected subject",
            "scope_reason": "Isolated test double inspected the complete eligible set", "anchor": explore.anchor.model_dump(mode="json"),
            "direction": explore.direction, "year": explore.year, "gallery_revision": store.revision,
            "cache_model": os.getenv("CG_MODEL", "gpt-5.4-mini"), "inspection_mode": "source_crop_and_full_candidates",
            "eligible_photo_ids": eligible, "inspected_photo_ids": ids,
            "photo_versions": {pid: store.photo(pid).version for pid in ids},
            "decisions": [{"photo_id": pid, "verdict": "unrelated", "reason": "Test independent negative judgment"} for pid in eligible]}
