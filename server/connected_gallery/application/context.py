"""Read-only context lookup and durable, snapshot-scoped preparation identity."""
from __future__ import annotations

import hashlib
import json
import re
import time

from connected_gallery.adapters.store import encoded
from connected_gallery.domain.context import (
    CONTEXT_POLICY, CONTEXT_SPEC, CONTEXT_WORDING_MODEL, ContextEvidence, PhotoContext,
    capture_metadata, context_wording_fields,
)
from connected_gallery.domain.models import RunRequest, new_id
from connected_gallery.application.demo_profile import effective_context_model


class ContextService:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def key(self, photo_id):
        asset = self.store.photo(photo_id)
        return hashlib.sha256(encoded(["photo-context", CONTEXT_SPEC, CONTEXT_POLICY, CONTEXT_WORDING_MODEL,
            effective_context_model(), photo_id, asset.version, self.store.revision]).encode()).hexdigest()

    def validate(self, photo_id, raw):
        self.store.photo(photo_id)
        context = PhotoContext.model_validate(
            {k: v for k, v in raw.items() if k != "evidence"} if isinstance(raw, dict) else raw)
        # General words or short numeric photo IDs are valid gallery identities,
        # but their ordinary occurrence in prose does not establish ID leakage.
        identifiers = [re.escape(p.id) for p in self.store.photos() if
            re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", p.id)
            or (len(p.id) >= 16 and re.fullmatch(r"[A-Za-z0-9._:-]+", p.id) and re.search(r"[0-9]", p.id))]
        if identifiers:
            exposed_id = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(identifiers) + r")(?![A-Za-z0-9])")
            if any(exposed_id.search(field["text"]) for field in context_wording_fields(context)):
                raise ValueError("Context display text exposes an internal photo identifier")
        for group in context.groups:
            for pid in group.photo_ids:
                if pid == photo_id:
                    raise ValueError("Opened photo cannot be its own context member")
                self.store.photo(pid)
        return context

    def validate_evidence(self, photo_id, context, raw):
        evidence = ContextEvidence.model_validate(raw)
        ids = set(evidence.inspected_photo_ids)
        expected = {(g.id, pid) for g in context.groups for pid in g.photo_ids}
        actual = [(r.group_id, r.photo_id) for r in evidence.reviewed_members]
        expected_paths = {field["path"] for field in context_wording_fields(context)}
        if (photo_id not in ids or len(ids) != len(evidence.inspected_photo_ids)
                or set(evidence.photo_versions) != ids
                or any(pid not in ids for _, pid in expected)
                or len(actual) != len(expected) or set(actual) != expected
                or evidence.gallery_revision != self.store.revision
                or evidence.source_version != self.store.photo(photo_id).version):
            raise ValueError("Context evidence does not match its current source and members")
        if (len(evidence.planned_photo_ids) != len(set(evidence.planned_photo_ids))
                or photo_id in evidence.planned_photo_ids or not set(evidence.planned_photo_ids).issubset(ids)
                or evidence.wording_review_model != CONTEXT_WORDING_MODEL
                or len(evidence.wording_checked_paths) != len(expected_paths)
                or set(evidence.wording_checked_paths) != expected_paths):
            raise ValueError("Context plan completion or exact wording review evidence is invalid")
        for pid, version in evidence.photo_versions.items():
            if self.store.photo(pid).version != version:
                raise ValueError("Inspected context photo changed")
        if not context.groups and set(p.id for p in self.store.photos()) != ids:
            raise ValueError("Empty context needs whole-gallery image evidence")
        return evidence

    def cache_value(self, photo_id, raw):
        context = self.validate(photo_id, raw)
        evidence = self.validate_evidence(photo_id, context, raw.get("evidence"))
        return {"kind": "photo_context", "photo_id": photo_id, "context_spec": CONTEXT_SPEC,
                "context_policy": CONTEXT_POLICY, "context": context.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json")}

    def cached_context(self, photo_id, cached):
        if (not isinstance(cached, dict)
                or set(cached) != {"kind", "photo_id", "context_spec", "context_policy", "context", "evidence"}
                or cached["kind"] != "photo_context" or cached["photo_id"] != photo_id
                or type(cached["context_spec"]) is not int or cached["context_spec"] != CONTEXT_SPEC
                or cached["context_policy"] != CONTEXT_POLICY):
            raise ValueError("Context cache identity mismatch")
        context = self.validate(photo_id, cached["context"])
        self.validate_evidence(photo_id, context, cached["evidence"])
        return context

    def ready(self, photo_id):
        """Never creates a task, cache, event or model call, even for pending/failed."""
        with self.store.lock:
            asset = self.store.photo(photo_id)
            key = self.key(photo_id)
            value = {"photo_id": photo_id, "state": "pending", "revision": self.store.revision,
                     "capture": capture_metadata(asset), "context": None}
            cached = self.store.cache_get(key)
            if cached:
                try:
                    context = self.cached_context(photo_id, cached)
                    if context.complete:
                        return {**value, "state": "ready" if context.groups else "empty",
                                "context": context.model_dump(mode="json", exclude={"complete"})}
                except ValueError:
                    pass
            rows = self.store.rows("SELECT id,status FROM runs WHERE key LIKE ? "
                "AND json_extract(request,'$.role')='context' "
                "AND json_extract(request,'$.photo_ids[0]')=? ORDER BY started DESC LIMIT 1",
                (f"context:{key}:%", photo_id))
            if rows:
                row = rows[0]
                if row["status"] in ("queued", "running"):
                    return {**value, "state": "running", "run_id": row["id"]}
                if row["status"] in ("failed", "incomplete", "cancelled"):
                    return {**value, "state": "failed", "error": "context_preparation_failed"}
            return value

    def start(self, photo_id, *, refresh_prepared=False):
        if type(refresh_prepared) is not bool:
            raise ValueError("Context refresh must be explicitly true or false")
        with self.store.lock:
            key = self.key(photo_id)
            # ready() deliberately serves the last valid result while a refresh
            # runs, so deduplication must inspect active work independently.
            active = self.store.rows("SELECT id FROM runs WHERE key LIKE ? "
                "AND status IN ('queued','running') AND json_extract(request,'$.role')='context' "
                "AND json_extract(request,'$.photo_ids[0]')=? ORDER BY started DESC LIMIT 1",
                (f"context:{key}:%", photo_id))
            if active:
                return self.service.get(active[0]["id"])
            value = self.ready(photo_id)
            if value["state"] == "running":
                return self.service.get(value["run_id"])
            rid = new_id()
            request = RunRequest(role="context", photo_ids=[photo_id],
                idempotency_key=f"context:{key}:{rid}")
            cached = self.store.cache_get(key) if not refresh_prepared and value["state"] in ("ready", "empty") else None
            self.store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
                rid, request.idempotency_key, request.model_dump_json(), "completed" if cached else "queued",
                encoded({**cached["context"], "evidence": cached["evidence"]}) if cached else None, None, time.time()))
            if refresh_prepared:
                previous = self.store.rows("SELECT revision,data FROM cache WHERE key=?", (key,))
                previous = previous[0] if previous else None
                self.store.event(rid, "context_refresh_requested", {
                    "cache_key": key, "photo_id": photo_id, "source_version": self.store.photo(photo_id).version,
                    "revision": self.store.revision, "context_model": effective_context_model(),
                    "previous_state": value["state"],
                    "previous_cache_revision": previous["revision"] if previous else None,
                    "previous_cache_sha256": hashlib.sha256(previous["data"].encode("utf-8")).hexdigest()
                        if previous and isinstance(previous["data"], str) else None})
            if not cached:
                self.service.schedule(rid, request)
            return self.service.get(rid)

    def prepare(self, photo_id):
        current = self.ready(photo_id)
        if current["state"] in ("ready", "empty"):
            return {**current, "run_id": None, "status": "completed"}
        run = self.start(photo_id)
        return {**self.ready(photo_id), "run_id": run["id"], "status": run["status"]}
