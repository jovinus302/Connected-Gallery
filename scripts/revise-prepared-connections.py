"""Independently review wording of existing prepared nonempty synthetic connections.

This command never changes the public model profile, starts retrieval, or chooses
new candidates. Every selected raw cache hash/revision is checked again by the
revision service before replacement. A failed revision preserves the old cache.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import apply_demo_model, read_demo_models
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, PhotoAnalysis, SemanticAnchor

_spec = importlib.util.spec_from_file_location("_revision_readonly", Path(__file__).with_name("audit-complete-demo.py"))
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--data-dir", type=Path, required=True)
    selection = value.add_mutually_exclusive_group(required=True)
    selection.add_argument("--source", "--photo-id", dest="photo_id", help="Revise every current region of this source unless --region-id is given")
    selection.add_argument("--all-ready", action="store_true", help="Explicitly select all prepared nonempty connections")
    value.add_argument("--region-id", help="One current region, used only with --photo-id")
    value.add_argument("--feedback-file", type=Path, help="Optional untrusted diagnostic prose, at most 8000 UTF-8 characters")
    value.add_argument("--env-file", type=Path)
    value.add_argument("--report", type=Path, required=True)
    return value


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def preflight(args):
    root = args.data_dir.resolve()
    if args.region_id and (args.all_ready or not args.photo_id):
        raise ValueError("--region-id requires a source photo selection")
    models = read_demo_models(root)
    if not models or not models.get("model"):
        raise ValueError("A marked synthetic gallery with an explicit public Connect model is required")
    report = args.report.resolve()
    if report.suffix.lower() != ".json" or report.is_relative_to(root) or report.exists():
        raise ValueError("Choose a new JSON report outside the source runtime")
    database = root / "gallery.sqlite"
    if not database.is_file() or database.is_symlink():
        raise ValueError("An existing regular synthetic gallery database is required")
    feedback, feedback_source = "", None
    if args.feedback_file is not None:
        if args.feedback_file.stat().st_size > 32_000:
            raise ValueError("Feedback must not exceed 8000 UTF-8 characters")
        feedback = args.feedback_file.read_text(encoding="utf-8")
        if len(feedback) > 8000:
            raise ValueError("Feedback must not exceed 8000 UTF-8 characters")
        feedback_source = "sha256:" + sha(feedback)
    apply_demo_model(root)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        store = _audit.ReadOnlyGallery(db)
        service = RunService(store, _audit.NoExecution())
        service.auto_enabled = service.auto_organize = False
        photos = store.photos()
        if not photos or any(p.device_id != "synthetic-demo" for p in photos):
            raise ValueError("Only synthetic demo photos may be revised with this command")
        if args.photo_id and args.photo_id not in {p.id for p in photos}:
            raise ValueError("Unknown source photo")
        selected, skipped = [], {"pending": 0, "empty": 0, "over_budget": 0}
        found_region = False
        for photo in photos:
            if args.photo_id and photo.id != args.photo_id:
                continue
            analysis = PhotoAnalysis.model_validate(store.analysis(photo.id))
            if analysis.photo_id != photo.id or any(r.photo_id != photo.id for r in analysis.regions):
                raise ValueError("Current analysis source does not match its photo")
            if len({r.id for r in analysis.regions}) != len(analysis.regions):
                raise ValueError("Current analysis has duplicate region IDs")
            for region in analysis.regions:
                if args.region_id and region.id != args.region_id:
                    continue
                found_region = True
                query = ExploreInput(anchor=SemanticAnchor(photo_id=photo.id, region_id=region.id,
                    box=region.box, label=region.label, kind=region.kind))
                ready = service.ready(query)
                reason = "pending" if ready["state"] != "ready" else (
                    "empty" if not ready["result"]["items"] else
                    "over_budget" if len(ready["result"]["items"]) > 24 else None)
                if reason:
                    if args.all_ready:
                        skipped[reason] += 1
                        continue
                    raise ValueError({"pending": "Selected connection is not currently prepared",
                                      "empty": "Only prepared nonempty connections can be revised",
                                      "over_budget": "Prepared revision supports at most 24 current candidates"}[reason])
                key = service.prepared_cache_key(query)
                row = store.cache_row(key)
                if row is None or row["revision"] != store.revision or not isinstance(row["data"], str):
                    raise ValueError("Prepared source changed before revision preflight")
                selected.append({"explore": query, "cache_key": key, "cache_sha256": sha(row["data"]),
                                 "revision": store.revision, "item_count": len(ready["result"]["items"])})
        if not found_region:
            raise ValueError("No matching current source region exists")
        if not selected:
            raise ValueError("No prepared nonempty connections are available to revise")
        if len({entry["cache_key"] for entry in selected}) != len(selected):
            raise ValueError("Selected prepared cache identities are not distinct")
        return {"root": root, "report": report, "model": models["model"], "selected": selected,
                "skipped": skipped, "feedback": feedback, "feedback_source": feedback_source}


def revision_service(root, model):
    # This is reached only after all requested selections pass read-only checks.
    from connected_gallery.adapters.store import Store
    from connected_gallery.adapters.proxy import ProxyGateway
    from connected_gallery.agent_runtime.organizer import ResultOrganizer
    from connected_gallery.agent_runtime.prepared_revision import PreparedRevisionRunner
    store = Store(root)
    gateway = ProxyGateway(primary=model, fallback=None, attempt_timeout=45, repeat_primary=False)
    service = RunService(store, PreparedRevisionRunner(store, ResultOrganizer(gateway, timeout=90)))
    service.auto_enabled = service.auto_organize = False
    return service


async def main(args):
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    values = preflight(args)
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ValueError("Existing model configuration is required for revision")
    service = revision_service(values["root"], values["model"])
    report = {"synthetic": True, "operation": "prepared_connection_revision", "model": values["model"],
              "selected_count": len(values["selected"]), "skipped": values["skipped"],
              "feedback_source": values["feedback_source"], "feedback_characters": len(values["feedback"]),
              "automatic_run_retries": 0, "max_revision_rounds": 2, "format_repairs_per_submission": 1,
              "attempts": []}

    def save():
        report["completed_count"] = sum(row["completed"] for row in report["attempts"])
        report["failed_count"] = sum(not row["completed"] and row["status"] not in ("starting", "queued", "running")
                                     for row in report["attempts"])
        report["in_progress_count"] = sum(row["status"] in ("starting", "queued", "running") for row in report["attempts"])
        report["unattempted_count"] = report["selected_count"] - len(report["attempts"])
        path = values["report"]
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    try:
        save()
        for selected in values["selected"]:
            query = selected["explore"]
            started = time.monotonic()
            row = {"run_id": None, "status": "starting", "result": None, "completed": False,
                   "photo_id": query.anchor.photo_id, "region_id": query.anchor.region_id,
                   "original_cache_sha256": selected["cache_sha256"], "original_revision": selected["revision"],
                   "original_item_count": selected["item_count"], "seconds": 0}
            report["attempts"].append(row)
            save()
            try:
                run = service.start_prepared_revision(query, feedback=values["feedback"],
                    feedback_source=values["feedback_source"], expected_cache_sha256=selected["cache_sha256"],
                    expected_revision=selected["revision"])
                row.update(run_id=run["id"], status=run["status"])
                save()
                while run["status"] in ("queued", "running"):
                    await asyncio.sleep(.2)
                    run = service.get(run["id"])
                result = run.get("result") or {}
                row.update(status=run["status"], result=run.get("result"),
                           completed=run["status"] == "completed" and result.get("complete") is True
                           and result.get("grouping_status") == "ready")
            except ValueError:
                # A CAS mismatch or changed selection must not fall back to a
                # newly discovered result or overwrite it after another attempt.
                row.update(status="rejected", result=None, completed=False, error="prepared_revision_precondition_failed")
            except asyncio.CancelledError:
                row.update(status="cancelled", result=None, completed=False, error="prepared_revision_interrupted")
                raise
            except Exception as exc:
                row.update(status="failed", result=None, completed=False, error=type(exc).__name__)
                raise
            finally:
                row["seconds"] = round(time.monotonic() - started, 3)
                save()
            print(json.dumps({"stage": "prepared_revision", **{k: v for k, v in row.items() if k != "result"}}, ensure_ascii=False), flush=True)
        return 0 if report["completed_count"] == report["selected_count"] else 2
    finally:
        await service.stop()
        service.store.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main(parser().parse_args())))
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        # Raw provider bodies, feedback contents and credential paths are never
        # copied into transport errors. Validation diagnostics above are fixed.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(json.dumps({"revision_started": False, "error": message}), flush=True)
        raise SystemExit(1) from None
