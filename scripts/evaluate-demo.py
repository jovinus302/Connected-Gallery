"""Evaluation-only minimum retrieval coverage; never a runtime preparation input.

Reads actual prepared results through RunService.ready with execution disabled.
Expected IDs and review criteria stay in this evaluator and are never passed to
the service. Group meanings and extra candidates require separate human review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))

from connected_gallery.adapters.store import Store
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
from connected_gallery.application.service import RunService
from connected_gallery.application.demo_profile import apply_demo_model
from connected_gallery.domain.models import ExploreInput, SemanticAnchor


class NoExecution:
    def __init__(self):
        self.calls = 0

    async def execute(self, *args):
        self.calls += 1
        raise AssertionError("Evaluation must never start model work")


class ReadOnlyStore(Store):
    def __init__(self, root):
        self.root = root
        self.lock = threading.RLock()
        self.db = sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

    def write(self, *args, **kwargs):
        raise AssertionError("Evaluation store is read-only")


def counters(store):
    return {"revision": store.revision,
            "events": store.rows("SELECT count(*) AS n FROM events")[0]["n"],
            "model_timing_events": store.rows("SELECT count(*) AS n FROM events WHERE kind='model_timing'")[0]["n"],
            "runs": store.rows("SELECT count(*) AS n FROM runs")[0]["n"],
            "active_runs": store.rows("SELECT count(*) AS n FROM runs WHERE status IN ('queued','running')")[0]["n"],
            "data_version": store.rows("PRAGMA data_version")[0]["data_version"]}


def original_hashes(document, case_path):
    relative = document.get("provenance", {}).get("images")
    if not relative:
        return None
    folder = (case_path.parent / relative).resolve()
    if not folder.is_relative_to(case_path.parent) or not folder.is_dir():
        raise ValueError("Referenced original samples must be available beside the evaluation cases")
    hashes = set()
    for path in folder.iterdir():
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder):
            raise ValueError("Evaluation cannot follow sample symlinks")
        hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return hashes


def evaluate(args):
    root, case_path, report_path = args.data_dir.resolve(), args.cases.resolve(), args.report.resolve()
    if case_path.is_relative_to(root) or report_path.is_relative_to(root) or case_path == report_path:
        raise ValueError("Evaluation cases and reports must remain outside the runtime and separate from each other")
    marker = root / "synthetic-demo.json"
    if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is not True:
        raise ValueError("A marked synthetic gallery is required")
    apply_demo_model(root)
    case_bytes = case_path.read_bytes()
    document = json.loads(case_bytes)
    if (document.get("schema_version") != 1 or document.get("synthetic") is not True or
            document.get("purpose") != "evaluation_only_never_runtime_input"):
        raise ValueError("Use a version-1 synthetic evaluation-only case document")
    cases = document.get("cases", [])
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Evaluation cases must have unique IDs")
    hashes = original_hashes(document, case_path)
    store = ReadOnlyStore(root)
    runner = NoExecution()
    service = RunService(store, runner)
    service.auto_enabled = False
    try:
        before = counters(store)
        if before["active_runs"]:
            raise ValueError("Wait for active preparation to finish before evaluating")
        photos = {photo.id: photo for photo in store.photos()}
        if not photos or any(photo.device_id != "synthetic-demo" for photo in photos.values()):
            raise ValueError("Every evaluated gallery asset must have device_id synthetic-demo")
        reference_assets = {asset["runtime_photo_id"]: asset["sha256"] for asset in document.get("assets", [])}
        if not set(reference_assets).issubset(photos):
            raise ValueError("Evaluation asset references a foreign photo ID")
        # Validate all IDs before making any service lookup, so one bad case
        # cannot produce a misleading partly successful evaluation report.
        for case in cases:
            expected = case["minimum_expected_hits"]["photo_ids"]
            minimum = case["minimum_expected_hits"]["minimum_count"]
            references = {case["source_region"]["photo_id"], *expected}
            for claim in case.get("forbidden_identity_claims", []):
                references.update(claim.get("photo_ids", []))
            if not references.issubset(photos):
                raise ValueError("Evaluation case references a foreign photo ID")
            if (len(set(expected)) != len(expected) or not isinstance(minimum, int) or
                    not 0 <= minimum <= len(expected) or case["source_region"]["photo_id"] in expected):
                raise ValueError("Expected hits must be unique non-source IDs with a valid minimum count")
        report = {"synthetic": True, "evaluation_only": True,
                  "metric_scope": "minimum retrieval coverage only",
                  "manual_review_status": "not_reviewed", "precision_evaluated": False,
                  "group_semantics_evaluated": False, "overall_accuracy_evaluated": False,
                  "cases_sha256": hashlib.sha256(case_bytes).hexdigest(),
                  "agent_spec": AGENT_SPEC_VERSION, "retrieval_policy": RETRIEVAL_POLICY,
                  "cache_model": os.getenv("CG_MODEL", "gpt-5.4-mini"),
                  "analysis_snapshot_revision": document.get("analysis_snapshot_revision"),
                  "runtime_revision": before["revision"],
                  "hash_verification": "original bytes and ingestion version" if hashes is not None else "recorded ingestion version only",
                  "evaluation_rules": document.get("evaluation_rules", []), "before": before, "cases": []}
        for case in cases:
            anchor = case["source_region"]
            photo = photos[anchor["photo_id"]]
            region = next((r for r in (store.analysis(photo.id) or {}).get("regions", [])
                           if r["id"] == anchor["region_id"]), None)
            stale = []
            expected = case["minimum_expected_hits"]["photo_ids"]
            source_hash = case["source_image_sha256"]
            if photo.version != source_hash or (hashes is not None and source_hash not in hashes):
                stale.append("source_image_hash_changed_or_unavailable")
            for pid in expected:
                expected_hash = reference_assets.get(pid)
                if expected_hash and (photos[pid].version != expected_hash or (hashes is not None and expected_hash not in hashes)):
                    stale.append("expected_image_hash_changed_or_unavailable:" + pid)
            if not region:
                stale.append("source_region_missing")
            elif (region["kind"] != anchor["kind"] or region["label"] != anchor["label"] or
                  any(abs(region["box"][key] - anchor["box"][key]) > .00001 for key in ("x", "y", "width", "height"))):
                stale.append("source_region_snapshot_changed")
            row = {"id": case["id"], "title": case.get("title", ""), "source_region": anchor,
                   "source_crop_observation": case.get("source_crop_observation", ""),
                   "minimum_expected_hits": case["minimum_expected_hits"], "expected_ids": expected,
                   "manual_review_criteria": case.get("manual_review_criteria", []),
                   "forbidden_identity_claims": case.get("forbidden_identity_claims", []),
                   "uncertainty": case.get("uncertainty", ""), "manual_review_status": "not_reviewed",
                   "hit_ids": [], "missing_ids": None, "unevaluated_expected_ids": expected,
                   "additional_ids_for_manual_review": [], "items": [], "groups": [],
                   "minimum_count_reached": None, "minimum_retrieval_coverage": None}
            if stale:
                row.update(state="stale_case", stale_reasons=stale)
            else:
                # Only the current ordinary anchor crosses into application
                # code. No scenario name, expected ID or rubric is supplied.
                current_anchor = SemanticAnchor(photo_id=photo.id, region_id=region["id"],
                                                box=region["box"], kind=region["kind"], label=region["label"])
                ready = service.ready(ExploreInput(anchor=current_anchor))
                row["state"] = ready["state"]
                row["lookup_revision"] = ready["revision"]
                if ready["state"] == "ready":
                    result = ready["result"]
                    ids = {item["photo_id"] for item in result["items"]}
                    hits = [pid for pid in expected if pid in ids]
                    row.update(hit_ids=hits, missing_ids=[pid for pid in expected if pid not in ids],
                               unevaluated_expected_ids=[], additional_ids_for_manual_review=sorted(ids - set(expected)),
                               items=result["items"], groups=result["groups"], complete=result["complete"],
                               grouping_status=result["grouping_status"],
                               minimum_count_reached=len(hits) >= case["minimum_expected_hits"]["minimum_count"],
                               minimum_retrieval_coverage={"hit_count": len(hits), "listed_expected_count": len(expected),
                                                           "fraction": len(hits) / len(expected) if expected else None})
            report["cases"].append(row)
        after = counters(store)
        report["after"] = after
        report["delta"] = {key: after[key] - before[key] for key in before}
        report["event_delta"] = after["events"] - before["events"]
        report["execution_attempts"] = runner.calls
        report["read_only_verified"] = before == after and runner.calls == 0 and not service.tasks
        report["case_states"] = dict(Counter(case["state"] for case in report["cases"]))
        report["ready_cases_reaching_minimum_count"] = sum(case["minimum_count_reached"] is True for case in report["cases"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key not in {"cases", "before", "after", "evaluation_rules"}}, ensure_ascii=False))
        return report
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / ".runtime" / "demo")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    try:
        report = evaluate(parser.parse_args())
        if not report["read_only_verified"]:
            raise SystemExit("Runtime changed during evaluation; discard this report and rerun when idle")
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise SystemExit(str(exc) if isinstance(exc, ValueError) else f"Evaluation failed ({type(exc).__name__})") from None


if __name__ == "__main__":
    main()
