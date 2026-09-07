"""Independent negative evidence strengthens empty results without rekeying positives."""
import os

EMPTY_EVIDENCE_SPEC = 1
EMPTY_EVIDENCE_POLICY = "whole-eligible-independent-negative-v1"
MAX_EMPTY_CANDIDATES = 24


def validate_empty_evidence(store, explore, raw, *, model=None):
    from connected_gallery.domain.models import EmptyEvidence

    proof = EmptyEvidence.model_validate(raw)
    source = store.photo(explore.anchor.photo_id)
    eligible = {photo.id: photo.version for photo in store.photos(explore.year) if photo.id != source.id}
    versions = {source.id: source.version, **eligible}
    if (proof.anchor != explore.anchor or proof.direction != explore.direction or proof.year != explore.year
            or proof.gallery_revision != store.revision or proof.photo_versions != versions
            or set(proof.eligible_photo_ids) != set(eligible)
            or set(proof.inspected_photo_ids) != set(versions)
            or proof.cache_model != (model if model is not None else os.getenv("CG_MODEL", "gpt-5.4-mini"))):
        raise ValueError("Empty evidence does not match the current selection and gallery")
    if explore.anchor.region_id:
        region = next((r for r in (store.analysis(source.id) or {}).get("regions", [])
                       if r["id"] == explore.anchor.region_id), None)
        if (region is None or region["kind"] != proof.anchor.kind or region["label"] != proof.anchor.label
                or region["box"] != proof.anchor.box.model_dump()):
            raise ValueError("Empty evidence anchor no longer matches the analyzed region")
    return proof
