"""Materialize searchable representations of the agent's submitted evidence.

No categories, semantic judgments or ranking decisions live here. The stored
photo, agent-written text and agent-selected regions are indexed before a new analysis commits.
"""
from __future__ import annotations
from connected_gallery.domain.models import PhotoAnalysis
from connected_gallery.domain.ports import AnalysisRepository, EmbeddingProvider
from connected_gallery.domain.index_keys import image_key, text_key, region_key


class AnalysisIndexing:
    def __init__(self, store: AnalysisRepository, models: EmbeddingProvider):
        self.store = store
        self.models = models

    def keys(self, analysis, version):
        text = analysis.description + " " + analysis.ocr
        return tuple(dict.fromkeys([
            image_key(analysis.photo_id, version, self.models.visual_space),
            text_key(analysis.photo_id, text, self.models.text_space),
            *[region_key(analysis.photo_id, version, r.box, self.models.visual_space) for r in analysis.regions],
        ]))

    def prepare(self, analysis, version):
        full_key, evidence_key = self.keys(analysis, version)[:2]
        prepared = []
        representations = [
            (full_key, self.models.visual_space, lambda: self.models.image(self.store.read_image(analysis.photo_id))),
            (evidence_key, self.models.text_space, lambda: self.models.text(analysis.description + " " + analysis.ocr, query=False)),
            *[(region_key(analysis.photo_id, version, r.box, self.models.visual_space), self.models.visual_space,
               lambda box=r.box: self.models.image(self.store.read_image(analysis.photo_id, box))) for r in analysis.regions],
        ]
        seen = set()
        for key, expected_space, encode in representations:
            if key in seen or self.store.has_vector(key):
                continue
            seen.add(key)
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
        ready, missing, full_ready = [], [], 0
        selected_keys = set()
        for analysis in analyses:
            if analysis.photo_id not in photos:
                continue
            required = self.keys(analysis, photos[analysis.photo_id].version)
            full_ready += all(key in keys for key in required[:2])
            selected_keys.update(required[2:])
            (ready if all(key in keys for key in required) else missing).append(analysis.photo_id)
        return {"photo_count": len(photos), "analyzed_count": len(analyses),
                "ready_count": len(ready), "full_photo_text_ready_count": full_ready,
                "selected_region_index_count": len(selected_keys),
                "indexed_selected_region_count": len(selected_keys & keys), "missing_index_ids": missing}
