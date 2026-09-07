"""Private offline revision provenance and atomic replacement of one current cache.

This introduces no public cache namespace, API route or retrieval policy. The
source row remains usable until an independently reviewed replacement commits.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from connected_gallery.adapters.store import encoded
from connected_gallery.application.attempt_feedback import execution_identity
from connected_gallery.domain.models import ExplorationResult, RunRequest, new_id


PREPARED_REVISION_SPEC = 1
SOURCE_EVENT = "prepared_revision_source"
REVIEW_EVENT = "prepared_revision_reviewed"
MAX_FEEDBACK_CHARS = 8000


def text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_event(store, run_id):
    rows = store.rows("SELECT data FROM events WHERE run_id=? AND kind=?", (run_id, SOURCE_EVENT))
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("Prepared revision provenance must occur exactly once")
    value = json.loads(rows[0]["data"])
    if (value.get("spec") != PREPARED_REVISION_SPEC or value.get("mode") != "prepared_revision"
            or text_sha256(value["original_cache_data"]) != value["original_cache_sha256"]):
        raise ValueError("Prepared revision provenance is invalid")
    return value


def image_fingerprints(store, request, result):
    """Actual decoded evidence, including an uploaded crop preview when present."""
    anchor = request.explore.anchor
    pairs = [("source_crop", anchor.photo_id, anchor.box)]
    pairs += [("candidate:" + item["photo_id"], item["photo_id"], None) for item in result["items"]]
    fingerprints = {}
    for key, pid, box in pairs:
        image = store.read_image(pid, box)
        try:
            if image.width <= 0 or image.height <= 0:
                raise ValueError("Prepared revision image is empty")
            digest = hashlib.sha256(encoded([image.mode, image.size]).encode())
            digest.update(image.tobytes())
            fingerprints[key] = digest.hexdigest()
        finally:
            image.close()
    return fingerprints


def validate_current_source(service, request, source):
    canonical = service._canonical_explore(request.explore)
    current_request = request.model_copy(update={"explore": canonical})
    if service.cache_key(current_request) != source["original_cache_key"]:
        raise ValueError("Prepared revision requires the source cache's primary model")
    if execution_identity(service.store, current_request) != source["execution_identity"]:
        raise ValueError("Prepared revision selection or gallery identity changed")
    rows = service.store.rows("SELECT revision,data FROM cache WHERE key=?", (source["original_cache_key"],))
    if (len(rows) != 1 or rows[0]["revision"] != source["original_cache_revision"]
            or rows[0]["data"] != source["original_cache_data"]
            or text_sha256(rows[0]["data"]) != source["original_cache_sha256"]):
        raise ValueError("Prepared revision source cache changed")
    original = ExplorationResult.model_validate_json(source["original_cache_data"])
    if original.grouping_status != "ready" or not original.complete or not 1 <= len(original.items) <= 24:
        raise ValueError("Prepared revision source is not a bounded ready nonempty result")
    if service.prepared_cache_key(canonical) != source["original_cache_key"]:
        raise ValueError("Prepared revision source is no longer current")
    if image_fingerprints(service.store, current_request, original.model_dump(mode="json")) != source["image_fingerprints"]:
        raise ValueError("Prepared revision source image evidence changed")
    return original.model_dump(mode="json")


def start_prepared_revision(service, explore, *, feedback="", feedback_source=None,
                            expected_cache_sha256=None, expected_revision=None):
    if not getattr(service.runner, "supports_prepared_revision", False):
        raise ValueError("Prepared revision requires the explicit offline runner")
    if not isinstance(feedback, str) or len(feedback) > MAX_FEEDBACK_CHARS:
        raise ValueError("Quality feedback must be text of at most 8000 characters")
    if feedback_source is not None and (not isinstance(feedback_source, str) or len(feedback_source) > 240):
        raise ValueError("Feedback source must be a short provenance string")
    if expected_cache_sha256 is not None and (not isinstance(expected_cache_sha256, str)
                                             or re.fullmatch(r"[0-9a-f]{64}", expected_cache_sha256) is None):
        raise ValueError("Expected cache hash must be a SHA256 hex digest")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("Expected revision must be a nonnegative integer")
    store = service.store
    with store.lock:
        # BEGIN IMMEDIATE also serializes writers in other preparation processes.
        # Use direct SQL here: Store.write commits its own individual statement.
        store.db.execute("BEGIN IMMEDIATE")
        try:
            explore = service._canonical_explore(explore)
            request = RunRequest(role="explorer", explore=explore,
                                 idempotency_key="prepared-revision:" + new_id())
            key = service.prepared_cache_key(explore)
            if key is None:
                raise ValueError("Prepared revision requires a current ready result")
            if key != service.cache_key(request):
                raise ValueError("Prepared revision requires the source cache's primary model")
            row = store.rows("SELECT revision,data FROM cache WHERE key=?", (key,))[0]
            original = ExplorationResult.model_validate_json(row["data"])
            if not original.items or len(original.items) > 24:
                raise ValueError("Prepared revision supports only 1 to 24 existing nonempty candidates")
            digest = text_sha256(row["data"])
            if expected_cache_sha256 is not None and expected_cache_sha256 != digest:
                raise ValueError("Prepared revision source cache changed since selection")
            if expected_revision is not None and expected_revision != store.revision:
                raise ValueError("Prepared revision gallery changed since selection")
            matching_runs = []
            for prior in store.rows("SELECT id,request,result FROM runs WHERE result IS NOT NULL AND json_extract(request,'$.role')='explorer'"):
                try:
                    if (service.cache_key(RunRequest.model_validate_json(prior["request"])) == key
                            and json.loads(prior["result"]) == json.loads(row["data"])):
                        matching_runs.append(prior["id"])
                except (ValueError, TypeError, KeyError):
                    continue
            source = {"spec": PREPARED_REVISION_SPEC, "mode": "prepared_revision",
                "original_cache_key": key, "original_cache_revision": row["revision"],
                "original_cache_data": row["data"], "original_cache_sha256": digest,
                "prior_matching_run_ids": matching_runs,
                "execution_identity": execution_identity(store, request),
                "image_fingerprints": image_fingerprints(store, request, original.model_dump(mode="json")),
                "untrusted_quality_feedback": feedback, "feedback_source": feedback_source,
                "feedback_sha256": text_sha256(feedback)}
            rid = new_id()
            now = time.time()
            store.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
                rid, request.idempotency_key, request.model_dump_json(), "queued", None, None, now))
            store.db.execute("INSERT INTO events(run_id,kind,data,at) VALUES(?,?,?,?)", (rid, SOURCE_EVENT, encoded(source), now))
            store.db.commit()
        except BaseException:
            store.db.rollback()
            raise
    service.schedule(rid, request)
    return service.get(rid)


def finish_prepared_revision(service, run_id, request, result, complete):
    """CAS publishes the new ready row and completed run in ONE transaction."""
    store = service.store
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            source = source_event(store, run_id)
            if source is None:
                raise ValueError("Prepared revision source is missing")
            if complete:
                original = validate_current_source(service, request, source)
                value = ExplorationResult.model_validate(result)
                if not value.complete or value.grouping_status != "ready" or not value.items:
                    raise ValueError("Prepared revision cannot publish an unreviewed or empty result")
                allowed = {item["photo_id"] for item in original["items"]}
                if not {item.photo_id for item in value.items} <= allowed:
                    raise ValueError("Prepared revision cannot add candidates")
                proofs = store.rows("SELECT data FROM events WHERE run_id=? AND kind=?", (run_id, REVIEW_EVENT))
                proof = json.loads(proofs[0]["data"]) if len(proofs) == 1 else {}
                if proof != {"spec": PREPARED_REVISION_SPEC, "original_cache_sha256": source["original_cache_sha256"],
                              "result_sha256": text_sha256(encoded(result)), "label_group_item_reviewed": True}:
                    raise ValueError("Prepared revision independent review provenance is missing")
                changed = store.db.execute("UPDATE cache SET data=? WHERE key=? AND revision=? AND data=?", (
                    encoded(result), source["original_cache_key"], source["original_cache_revision"], source["original_cache_data"]))
                if changed.rowcount != 1:
                    raise ValueError("Prepared revision compare-and-swap failed")
            status = "completed" if complete else "incomplete"
            changed = store.db.execute("UPDATE runs SET status=?,result=? WHERE id=? AND status='running'", (status, encoded(result), run_id))
            if changed.rowcount != 1:
                raise ValueError("Prepared revision run is no longer active")
            store.db.execute("INSERT INTO events(run_id,kind,data,at) VALUES(?,?,?,?)", (
                run_id, "prepared_revision_committed" if complete else "prepared_revision_incomplete",
                encoded({"spec": PREPARED_REVISION_SPEC, "original_cache_key": source["original_cache_key"],
                         "original_cache_sha256": source["original_cache_sha256"],
                         "result_sha256": text_sha256(encoded(result)), "cache_replaced": complete}), time.time()))
            store.db.commit()
        except BaseException:
            store.db.rollback()
            raise
