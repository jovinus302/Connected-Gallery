"""Create a NEW packaging input containing only current prepared demo caches.

The source SQLite connection is read-only. Only the private staging backup is
pruned. This is NOT a public delivery: package-demo.py must subsequently remove
execution history, feedback, Spaces and local URIs from its own copied database.
No Store initialization, model gateway, preparation or server is used here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import apply_demo_model, public_demo_marker, effective_context_model, connection_models
from connected_gallery.application.service import RunService
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
from connected_gallery.domain.context import CONTEXT_SPEC, CONTEXT_POLICY
from connected_gallery.domain.models import ExploreInput, PhotoAnalysis, RunRequest, SemanticAnchor

# Hyphenated CLI names cannot be imported with ordinary Python module syntax.
_spec = importlib.util.spec_from_file_location("_staging_readonly_audit", Path(__file__).with_name("audit-complete-demo.py"))
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)
ReadOnlyGallery, NoExecution = _audit.ReadOnlyGallery, _audit.NoExecution


class StageError(ValueError):
    """Only fixed, non-payload messages from this class may reach CLI output."""


def require(condition, message):
    if not condition:
        raise StageError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular_file(path, root):
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
            "A required regular input file is missing or outside the synthetic runtime")


def file_state(path):
    info = path.stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "mode": info.st_mode, "device": info.st_dev, "inode": info.st_ino}


def database_metadata(root):
    # Access times and shared-memory lock bytes are not dataset metadata.
    return {name: file_state(root / name) if (root / name).exists() else None
            for name in ("gallery.sqlite", "gallery.sqlite-wal")}


def logical_state(db, *, exclude_cache=False):
    schema = [tuple(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
    tables = []
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if exclude_cache and name == "cache":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        # Hash rows independently so SQL ordering, NULLs and blobs are harmless.
        rows = sorted(sha(repr(tuple(row)).encode()) for row in db.execute("SELECT * FROM " + quoted))
        tables.append((name, len(rows), sha(json.dumps(rows).encode())))
    return {"schema_sha256": sha(repr(schema).encode()), "tables_sha256": sha(repr(tables).encode())}


def read_source_state(db):
    return {"revision": db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0],
            "active_runs": db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0],
            "data_version": db.execute("PRAGMA data_version").fetchone()[0],
            "total_changes": db.total_changes, "logical": logical_state(db)}


def current_inventory(db, expected_photos, expected_regions):
    """Validate every actual current key; never search obsolete payloads for substitutes."""
    store, runner = ReadOnlyGallery(db), NoExecution()
    service = RunService(store, runner)
    service.auto_enabled = service.auto_organize = False
    photos, anchors = store.photos(), []
    require(len(photos) == expected_photos, "Synthetic photo count does not match the expected count")
    require(all(photo.device_id == "synthetic-demo" for photo in photos), "Every photo must use device_id synthetic-demo")
    require(all(row["id"] == photo.id and row["version"] == photo.version for row, photo in zip(
        db.execute("SELECT id,version FROM photos ORDER BY id"), photos)), "Photo row identity or version mismatch")
    for photo in photos:
        analysis = PhotoAnalysis.model_validate(store.analysis(photo.id))
        require(analysis.photo_id == photo.id and all(region.photo_id == photo.id for region in analysis.regions),
                "Current analysis has an inconsistent source")
        require(len({region.id for region in analysis.regions}) == len(analysis.regions), "Current analysis has duplicate region IDs")
        anchors.extend(SemanticAnchor(photo_id=photo.id, region_id=region.id, box=region.box,
                                      label=region.label, kind=region.kind) for region in analysis.regions)
    require(len(anchors) == expected_regions, "Current region count does not match the expected count")
    retained, results = {}, []
    changes_before = db.total_changes

    def take(key, kind):
        require(key not in retained, "Current prepared keys are not distinct")
        rows = db.execute("SELECT revision,data,CAST(data AS BLOB) AS bytes FROM cache WHERE key=?", (key,)).fetchall()
        require(len(rows) == 1, "A current prepared cache key is missing or duplicated")
        row = rows[0]
        require(row["revision"] == store.revision, "A current prepared cache has a stale revision")
        require(isinstance(row["data"], str), "A current prepared cache payload is not text")
        try:
            cached = json.loads(row["data"])
        except (TypeError, ValueError):
            raise StageError("A current prepared cache contains corrupt JSON") from None
        require(isinstance(cached, dict), "A current prepared cache payload is not an object")
        retained[key] = (row["revision"], row["bytes"])
        results.append({"key": key, "kind": kind, "revision": row["revision"], "payload_sha256": sha(row["bytes"])})
        return cached

    empty_connect = empty_context = 0
    for anchor in anchors:
        query = ExploreInput(anchor=anchor)
        key = service.prepared_cache_key(query) or service.cache_key(RunRequest(role="explorer", explore=query))
        take(key, "connect")
        value = service.ready(query)
        require(value["state"] == "ready", "A current Connect result is not completely prepared")
        results[-1]["cache_model"] = value.get("cache_model")
        require(value["revision"] == store.revision and value["result"]["complete"]
                and value["result"]["grouping_status"] == "ready", "A current Connect result is incomplete")
        empty_connect += not value["result"]["items"]
    for photo in photos:
        key = service.contexts.key(photo.id)
        cached = take(key, "context")
        context = service.contexts.cached_context(photo.id, cached)
        value = service.context_ready(photo.id)
        require(context.complete and value["state"] in ("ready", "empty") and value["revision"] == store.revision,
                "A current photo context is not completely prepared")
        empty_context += value["state"] == "empty"
    require(len(retained) == expected_photos + expected_regions, "Current prepared cache count mismatch")
    require(db.total_changes == changes_before and runner.calls == 0 and not service.tasks,
            "Prepared validation attempted execution or a database write")
    return photos, retained, {"connect": len(anchors), "contexts": len(photos),
                             "confirmed_empty_connect": empty_connect, "confirmed_empty_context": empty_context,
                             "execution_attempts": runner.calls, "cache_records": results}


def stage(args):
    root, destination = args.data_dir.resolve(), args.stage_dir.resolve()
    require(args.expected_photos > 0 and args.expected_regions > 0, "Expected counts must be positive")
    require(not args.stage_dir.exists() and not args.stage_dir.is_symlink() and not destination.exists(),
            "Choose a staging directory that does not exist")
    require(destination != root and not destination.is_relative_to(root) and not root.is_relative_to(destination),
            "Staging must be separate from the original runtime")
    marker, database = root / "synthetic-demo.json", root / "gallery.sqlite"
    regular_file(marker, root)
    regular_file(database, root)
    marker_bytes, marker_metadata = marker.read_bytes(), file_state(marker)
    try:
        require(json.loads(marker_bytes).get("synthetic") is True, "A marked synthetic gallery is required")
        public_marker = public_demo_marker(root, default_model=os.getenv("CG_MODEL", "gpt-5.4-mini"))
        model = public_marker["model"]
    except (ValueError, TypeError, AttributeError):
        raise StageError("The synthetic marker or public model profile is invalid") from None
    metadata_before = database_metadata(root)
    previous_model = os.environ.get("CG_MODEL")
    previous_context_model = os.environ.get("CG_CONTEXT_MODEL")
    previous_compatible_models = os.environ.get("CG_COMPATIBLE_CONNECTION_MODELS")
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only=ON")
    try:
        apply_demo_model(root)
        os.environ["CG_MODEL"] = model
        source.execute("BEGIN")
        before = read_source_state(source)
        require(before["active_runs"] == 0, "Preparation is active; stage only after all jobs finish")
        # Reject private assets before creating any copy, even with a synthetic marker.
        photos = ReadOnlyGallery(source).photos()
        require(photos and all(photo.device_id == "synthetic-demo" for photo in photos),
                "Every photo must use device_id synthetic-demo")
        image_baseline = {}
        for photo in photos:
            image = root / "images" / (sha(photo.id.encode()) + ".jpg")
            regular_file(image, root)
            info = file_state(image)
            image_baseline[photo.id] = (info, sha(image.read_bytes()))
            require(file_state(image) == info, "A processed image changed before the staging snapshot")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".stage-complete-demo-", dir=destination.parent) as temporary:
            temporary = Path(temporary).resolve()
            require(temporary.parent == destination.parent and temporary != root, "Temporary staging directory escaped its parent")
            staged = temporary / "runtime"
            staged.mkdir()
            copied_db = staged / "gallery.sqlite"
            target = sqlite3.connect(copied_db)
            target.row_factory = sqlite3.Row
            try:
                source.backup(target)
                require(logical_state(target) == before["logical"], "The SQLite backup does not match the source snapshot")
                require(target.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Staging SQLite integrity check failed")
                photos, retained, validation = current_inventory(target, args.expected_photos, args.expected_regions)
                non_cache_before = logical_state(target, exclude_cache=True)
                old_keys = [row[0] for row in target.execute("SELECT key FROM cache ORDER BY key")]
                obsolete_keys = [key for key in old_keys if key not in retained]
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute("PRAGMA secure_delete=ON")
                target.executemany("DELETE FROM cache WHERE key=?", ((key,) for key in obsolete_keys))
                target.commit()
                actual = {row["key"]: (row["revision"], row["bytes"]) for row in target.execute(
                    "SELECT key,revision,CAST(data AS BLOB) AS bytes FROM cache")}
                require(actual == retained, "Current cache payload bytes or revisions changed during staging")
                require(logical_state(target, exclude_cache=True) == non_cache_before,
                        "Staging changed non-cache database records")
                require(target.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Pruned SQLite integrity check failed")
                staged_revision = target.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]
                require(staged_revision == before["revision"], "Staging changed the gallery revision")
            finally:
                target.close()
            (staged / "images").mkdir()
            image_records, input_images = [], []
            for photo in photos:
                name = sha(photo.id.encode()) + ".jpg"
                image = root / "images" / name
                regular_file(image, root)
                info, digest = image_baseline[photo.id]
                content = image.read_bytes()
                require(file_state(image) == info and sha(content) == digest, "A processed image changed while being copied")
                (staged / "images" / name).write_bytes(content)
                record = {"photo_id": photo.id, "file": "images/" + name, "sha256": sha(content), "bytes": len(content)}
                image_records.append(record)
                input_images.append((image, info, record["sha256"]))
            (staged / "synthetic-demo.json").write_text(json.dumps(public_marker) + "\n", encoding="utf-8")
            # Release the snapshot so concurrent commits cannot hide behind it.
            source.rollback()
            source.execute("BEGIN")
            after = read_source_state(source)
            require(before == after, "Original gallery changed during staging")
            require(database_metadata(root) == metadata_before and marker.read_bytes() == marker_bytes
                    and file_state(marker) == marker_metadata, "Original database or marker metadata changed during staging")
            require(all(file_state(path) == info and sha(path.read_bytes()) == digest for path, info, digest in input_images),
                    "Original processed images changed during staging")
            report = {"schema_version": 1, "staged_at": datetime.now(timezone.utc).isoformat(),
                "synthetic": True, "staging_only": True, "requires_package_demo_sanitization": True,
                "model": model, "context_model": effective_context_model(), "revision": staged_revision, "agent_spec": AGENT_SPEC_VERSION,
                "compatible_connection_models": connection_models(model)[1:],
                "retrieval_policy": RETRIEVAL_POLICY, "context_spec": CONTEXT_SPEC, "context_policy": CONTEXT_POLICY,
                "source_read_only_verified": True, "source_state_before": before, "source_state_after": after,
                "source_file_metadata_unchanged": True, "retained_payload_bytes_and_revisions_unchanged": True,
                "non_cache_records_unchanged": True, "cache_before": len(old_keys), "cache_after": len(retained),
                "obsolete_cache_removed": len(obsolete_keys),
                "removed_keys_sha256": sha(json.dumps(sorted(obsolete_keys)).encode()),
                "retained_keys_sha256": sha(json.dumps(sorted(retained)).encode()),
                "validation": validation, "images": image_records,
                "file_copy_allowlist": ["gallery.sqlite", "synthetic-demo.json", "images/<photo-id-sha256>.jpg"],
                "external_credentials_launch_files_checkpoints_copied": False,
                "database_history_retained_for_final_packager": True,
                "scope": "Current prepared cache contracts only; no semantic or browser accuracy claim"}
            (staged / "stage-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            require(not destination.exists(), "Staging destination appeared during validation")
            # Publish only the complete new staging input; never overwrite a path.
            staged.rename(destination)
        return report
    except StageError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StageError("Current synthetic photos, analyses or prepared cache evidence failed validation") from None
    finally:
        source.close()
        if previous_model is None:
            os.environ.pop("CG_MODEL", None)
        else:
            os.environ["CG_MODEL"] = previous_model
        if previous_context_model is None:
            os.environ.pop("CG_CONTEXT_MODEL", None)
        else:
            os.environ["CG_CONTEXT_MODEL"] = previous_context_model
        if previous_compatible_models is None:
            os.environ.pop("CG_COMPATIBLE_CONNECTION_MODELS", None)
        else:
            os.environ["CG_COMPATIBLE_CONNECTION_MODELS"] = previous_compatible_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--expected-photos", type=int, default=20)
    parser.add_argument("--expected-regions", type=int, default=47)
    args = parser.parse_args()
    try:
        report = stage(args)
        print(json.dumps({"staged": True, "photos": len(report["images"]), "current_cache": report["cache_after"],
                          "obsolete_cache_removed": report["obsolete_cache_removed"], "read_only": report["source_read_only_verified"]}))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"staged": False, "error": str(exc) if isinstance(exc, StageError) else type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
