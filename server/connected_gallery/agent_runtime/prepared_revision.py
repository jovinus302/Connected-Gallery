"""Offline image reobservation and independent revision, without retrieval tools."""
from connected_gallery.adapters.store import encoded
from connected_gallery.application.prepared_revision import (
    PREPARED_REVISION_SPEC, REVIEW_EVENT, source_event, text_sha256, validate_current_source,
)
from connected_gallery.gallery_tools.registry import GalleryTools


class PreparedRevisionRunner:
    supports_prepared_revision = True

    def __init__(self, store, organizer):
        self.store = store
        self.organizer = organizer

    async def execute(self, run_id, request):
        # No GraphAgentRunner, search, local model loading, history loader or
        # checkpoint replay is involved. Organizer only reads actual images.
        from connected_gallery.application.service import RunService
        if request.role != "explorer":
            raise ValueError("Prepared revision requires an explorer selection")
        source = source_event(self.store, run_id)
        if source is None:
            raise ValueError("Prepared revision has no original cache provenance")
        gateway = self.organizer.gateway
        primary = getattr(gateway, "primary", None)
        if primary is not None and (primary != source["execution_identity"]["logical_model"]
                                    or getattr(gateway, "fallback", None) not in (None, primary)):
            raise ValueError("Prepared revision must preserve the original model profile")
        validator = RunService(self.store, self)
        with self.store.lock:
            original = validate_current_source(validator, request, source)
        toolkit = GalleryTools(self.store, None, request, run_id)
        # Keep even accidental future exposure from granting retrieval actions.
        toolkit.definitions = {}
        self.store.event(run_id, "progress", {"message": "준비된 사진 연결의 설명을 다시 확인하고 있어요"})
        result = await self.organizer.revise_prepared(toolkit, request, original,
                                                     feedback=source["untrusted_quality_feedback"])
        with self.store.lock:
            validate_current_source(validator, request, source)
        if result.get("complete") and result.get("grouping_status") == "ready" and result.get("items"):
            self.store.event(run_id, REVIEW_EVENT, {"spec": PREPARED_REVISION_SPEC,
                "original_cache_sha256": source["original_cache_sha256"],
                "result_sha256": text_sha256(encoded(result)), "label_group_item_reviewed": True})
        return result
