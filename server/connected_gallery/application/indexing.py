"""Materialize searchable representations of the agent's submitted evidence.

No categories, semantic judgments or ranking decisions live here. The stored
photo and agent-written text must both be indexed before a new analysis commits.
"""
from __future__ import annotations
import hashlib
from connected_gallery.domain.models import PhotoAnalysis
from connected_gallery.domain.ports import AnalysisRepository, EmbeddingProvider


class AnalysisIndexing:
    def __init__(self, store: AnalysisRepository, models: EmbeddingProvider):
        self.store = store
        self.models = models

    def keys(self, analysis, version):
        text = analysis.description + " " + analysis.ocr
        return (
            f"{analysis.photo_id}:image:{version}:{self.models.visual_space}",
            f"{analysis.photo_id}:text:{hashlib.sha256(text.encode()).hexdigest()}:{self.models.text_space}",
        )

    def prepare(self, analysis, version):
        image_key, text_key = self.keys(analysis, version)
        prepared = []
        for key, expected_space, encode in (
            (image_key, self.models.visual_space, lambda: self.models.image(self.store.read_image(analysis.photo_id))),
            (text_key, self.models.text_space, lambda: self.models.text(analysis.description + " " + analysis.ocr, query=False)),
        ):
            if self.store.has_vector(key):
                continue
            space, vector = encode()
            if space != expected_space:
                raise ValueError("Embedding provider returned an unexpected model space")
            prepared.append((key, analysis.photo_id, space, vector))
        return prepared

    def repair(self, photo_id):
        photo = self.store.photo(photo_id)
        existing = self.store.analysis(photo_id)
        if existing is None:
            raise ValueError("Analyze the photo before repairing its indexes")
        analysis = PhotoAnalysis.model_validate(existing)
        vectors = self.prepare(analysis, photo.version)
        if vectors:
            self.store.save_analysis(analysis, vectors=vectors, expected_version=photo.version, expected_analysis=existing)
        return {"photo_id": photo_id, "indexes_added": len(vectors)}

    def report(self):
        assets, evidence, keys = self.store.analysis_snapshot()
        photos = {p.id: p for p in assets}
        analyses = [PhotoAnalysis.model_validate(a) for a in evidence]
        ready, missing = [], []
        for analysis in analyses:
            if analysis.photo_id not in photos:
                continue
            required = self.keys(analysis, photos[analysis.photo_id].version)
            (ready if all(key in keys for key in required) else missing).append(analysis.photo_id)
        return {"photo_count": len(photos), "analyzed_count": len(analyses),
                "ready_count": len(ready), "missing_index_ids": missing}
