"""Read-only acceptance audit for prepared Connect and photo-detail contexts.

This audits stored data/edges, not browser behavior or semantic accuracy. All
expectations and the optional probe anchor stay in this evaluation process.
No Store constructor, model gateway, execution, or background jobs are used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import apply_demo_model
from connected_gallery.application.service import RunService
from connected_gallery.domain.context import CONTEXT_POLICY, CONTEXT_SPEC, capture_metadata
from connected_gallery.domain.models import ExploreInput, PhotoAsset, PhotoAnalysis, RunRequest, SemanticAnchor
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY


def require(value, message):
    if not value:
        raise ValueError(message)


class NoExecution:
    def __init__(self):
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Acceptance audit must not execute models")


class ReadOnlyGallery:
    def __init__(self, db):
        self.db = db
        self.lock = threading.RLock()

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args)]

    @property
    def revision(self):
        return self.db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]

    def photo(self, pid):
        row = self.db.execute("SELECT data FROM photos WHERE id=?", (pid,)).fetchone()
        require(row is not None, "Unknown synthetic photo ID")
        return PhotoAsset.model_validate_json(row[0])

    def photos(self, year=None):
        values = [PhotoAsset.model_validate_json(row[0]) for row in self.db.execute("SELECT data FROM photos ORDER BY id")]
        return values if year is None else [value for value in values if value.year == year]

    def analysis(self, pid):
        row = self.db.execute("SELECT data FROM analyses WHERE photo_id=?", (pid,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_row(self, key):
        row = self.db.execute("SELECT revision,data FROM cache WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def cache_get(self, key):
        row = self.cache_row(key)
        return json.loads(row["data"]) if row and row["revision"] == self.revision else None

    def write(self, *args, **kwargs):
        raise AssertionError("Acceptance store is read-only")


def counters(db):
    scalar = lambda sql: db.execute(sql).fetchone()[0]
    return {"revision": scalar("SELECT value FROM state WHERE key='revision'"),
            "photos": scalar("SELECT count(*) FROM photos"), "analyses": scalar("SELECT count(*) FROM analyses"),
            "cache": scalar("SELECT count(*) FROM cache"), "runs": scalar("SELECT count(*) FROM runs"),
            "events": scalar("SELECT count(*) FROM events"),
            "model_timing_events": scalar("SELECT count(*) FROM events WHERE kind='model_timing'"),
            "active_runs": scalar("SELECT count(*) FROM runs WHERE status IN ('queued','running')"),
            "spaces": scalar("SELECT count(*) FROM spaces"),
            "data_version": scalar("PRAGMA data_version"), "connection_total_changes": db.total_changes}


def fingerprints(db):
    # Hash logical contents as well as counts; a same-count UPDATE must be detected.
    result = {}
    for table in ("photos", "analyses", "cache", "state", "runs", "events", "spaces"):
        values = sorted(tuple(row) for row in db.execute('SELECT * FROM "' + table + '"'))
        result[table] = hashlib.sha256(repr(values).encode()).hexdigest()
    return result


def cache_diagnosis(store, key):
    row = store.cache_row(key)
    if not row:
        return "no_current_key"
    if row["revision"] != store.revision:
        return "stale_revision"
    try:
        json.loads(row["data"])
    except ValueError:
        return "corrupt_json"
    return "current_cache_present"


def inspect_connect(service, anchor):
    row = {"source_region": anchor.model_dump(mode="json"), "state": "invalid", "prepared": False,
           "confirmed_empty": False, "items": [], "groups": []}
    try:
        query = ExploreInput(anchor=anchor)
        key = service.cache_key(RunRequest(role="explorer", explore=query))
        row["cache_diagnosis"] = cache_diagnosis(service.store, key)
        result = service.ready(query)
        row.update(state=result["state"], revision=result["revision"])
        if result["state"] == "ready":
            value = result["result"]
            # Actual ready() has already checked the current canonical anchor and result schema/IDs.
            row.update(prepared=True, confirmed_empty=not value["items"],
                       label=value["label"], items=value["items"], groups=value["groups"],
                       complete=value["complete"], grouping_status=value["grouping_status"])
    except (ValueError, KeyError, TypeError) as exc:
        row["error_type"] = type(exc).__name__
    return row


def inspect_context(service, photo):
    row = {"photo_id": photo.id, "source_version": photo.version, "state": "invalid", "prepared": False,
           "confirmed_empty": False, "context": None, "evidence_valid": False}
    try:
        key = service.contexts.key(photo.id)
        row["cache_diagnosis"] = cache_diagnosis(service.store, key)
        response = service.context_ready(photo.id)
        row.update(state=response["state"], revision=response["revision"], capture=response["capture"],
                   context=response["context"])
        if response["state"] in ("ready", "empty"):
            cached = service.store.cache_get(key)
            service.contexts.cached_context(photo.id, cached)
            evidence = cached["evidence"]
            row.update(prepared=True, confirmed_empty=response["state"] == "empty", evidence_valid=True,
                       evidence={"gallery_revision": evidence["gallery_revision"], "source_version": evidence["source_version"],
                                 "inspected_photo_ids": evidence["inspected_photo_ids"],
                                 "photo_versions": evidence["photo_versions"],
                                 "reviewed_members": evidence["reviewed_members"],
                                 "summary_reviewed": evidence["summary_reviewed"]})
    except (ValueError, KeyError, TypeError) as exc:
        row["error_type"] = type(exc).__name__
    return row


def three_hop_routes(edges, max_per_start=2):
    """Find bounded examples of directed 3-edge paths over FOUR distinct photos."""
    outgoing = defaultdict(list)
    for edge in edges:
        outgoing[edge["source_photo_id"]].append(edge)
    examples = []
    starts = []
    for start in sorted(outgoing):
        found, paths = [], set()

        def visit(photo, visited, selected):
            if len(found) >= max_per_start:
                return
            if len(selected) == 3:
                identity = tuple(visited)
                if identity not in paths:
                    paths.add(identity)
                    found.append({"photo_ids": visited, "steps": selected})
                return
            for edge in outgoing.get(photo, []):
                target = edge["next_photo_id"]
                if target not in visited:
                    visit(target, [*visited, target], [*selected, edge])
                if len(found) >= max_per_start:
                    break

        visit(start, [start], [])
        if found:
            starts.append(start)
            examples.extend(found)
    return {"starts_with_three_hop_route": starts, "example_count": len(examples), "examples": examples,
            "max_examples_per_start": max_per_start, "exhaustive_route_count": False,
            "semantic_pivots_or_identity_verified": False}


def metadata_review(photos, fixture_path=None):
    rows = []
    for photo in photos:
        capture = capture_metadata(photo)
        trusted = photo.time_source in ("exif", "media_store", "demo_fixture")
        usable = photo.captured_at is not None and photo.captured_at.tzinfo is not None and trusted
        if photo.time_source == "demo_fixture":
            usable = usable and photo.device_id == "synthetic-demo"
        expected_date = photo.captured_at.astimezone(timezone(timedelta(hours=9))).date().isoformat() if usable else None
        valid = ((capture is None) if not usable else
                 capture is not None and capture["source"] == photo.time_source and capture["date"] == expected_date and
                 capture["timezone"] == "Asia/Seoul")
        rows.append({"photo_id": photo.id, "captured_at": photo.captured_at.isoformat() if photo.captured_at else None,
                     "time_source": photo.time_source, "capture": capture, "policy_valid": valid})
    result = {"policy": "Only timezone-aware exif/media_store/synthetic demo_fixture are calendar evidence; Asia/Seoul UTC+09",
              "source_counts": dict(Counter(photo.time_source for photo in photos)),
              "capture_present": sum(row["capture"] is not None for row in rows),
              "capture_absent": sum(row["capture"] is None for row in rows),
              "valid": all(row["policy_valid"] for row in rows), "photos": rows,
              "same_date_proves_same_event": False, "synthetic_dates_are_real_capture_facts": False}
    if fixture_path:
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        require(document.get("synthetic") is True and document.get("not_real_capture_facts") is True,
                "Metadata fixture must disclose invented capture facts")
        expected = {row["photo_id"]: row for row in document["photos"]}
        matches = len(expected) == len(document["photos"]) == len(photos) and set(expected) == {p.id for p in photos}
        mismatches = []
        for photo in photos:
            value = expected.get(photo.id)
            stamp = datetime.fromisoformat(value["captured_at"]) if value and value.get("captured_at") else None
            if value is None or value["time_source"] != photo.time_source or stamp != photo.captured_at:
                mismatches.append(photo.id)
        result.update(fixture_exact_match=matches and not mismatches, fixture_mismatch_ids=mismatches,
                      fixture_sha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest())
        result["valid"] = result["valid"] and result["fixture_exact_match"]
    return result


def audit(args):
    root, report_path = args.data_dir.resolve(), args.report.resolve()
    require(not report_path.is_relative_to(root), "Report must be outside the runtime")
    require(not report_path.exists(), "Choose a report path that does not exist")
    marker = root / "synthetic-demo.json"
    require(marker.is_file() and not marker.is_symlink() and json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is True,
            "A synthetic demo marker is required")
    db_path = root / "gallery.sqlite"
    require(db_path.is_file() and not db_path.is_symlink(), "A regular existing gallery database is required")
    previous_model = os.environ.get("CG_MODEL")
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        before = counters(db)
        require(before["active_runs"] == 0, "Preparation is active; do not run final acceptance yet")
        db.execute("BEGIN")
        require(counters(db) == before, "Gallery changed before acceptance snapshot")
        hashes_before = fingerprints(db)
        apply_demo_model(root)
        runner = NoExecution()
        store = ReadOnlyGallery(db)
        service = RunService(store, runner)
        service.auto_enabled = False
        service.auto_organize = False
        photos = store.photos()
        require(photos and all(p.device_id == "synthetic-demo" for p in photos), "Every photo must use device_id synthetic-demo")
        analyses, anchors, issues = {}, [], []
        for photo in photos:
            try:
                analysis = PhotoAnalysis.model_validate(store.analysis(photo.id))
                require(analysis.photo_id == photo.id, "Analysis source mismatch")
                require(len({region.id for region in analysis.regions}) == len(analysis.regions), "Duplicate region IDs")
                require(all(region.photo_id == photo.id for region in analysis.regions), "Foreign region source")
                analyses[photo.id] = analysis
                anchors.extend(SemanticAnchor(photo_id=photo.id, region_id=region.id, box=region.box,
                                              label=region.label, kind=region.kind) for region in analysis.regions)
            except (ValueError, TypeError) as exc:
                issues.append({"photo_id": photo.id, "error_type": type(exc).__name__})
        manifest_valid = True
        if args.manifest:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            expected = {row["sha256"][:32]: row["sha256"] for row in manifest}
            manifest_valid = (len(expected) == len(manifest) == len(photos) and set(expected) == {p.id for p in photos}
                              and all(p.version == expected.get(p.id) for p in photos))
        connections = [inspect_connect(service, anchor) for anchor in anchors]
        contexts = [inspect_context(service, photo) for photo in photos]
        metadata = metadata_review(photos, args.fixture)
        context_by_id = {row["photo_id"]: row for row in contexts}
        connect_edges, context_edges = [], []
        for connection in connections:
            anchor = connection["source_region"]
            for item in connection["items"] if connection["prepared"] else []:
                connect_edges.append({"source_photo_id": anchor["photo_id"], "source_region": anchor,
                                      "next_photo_id": item["photo_id"], "reason": item["reason"]})
        for context in contexts:
            for group in (context["context"] or {}).get("groups", []) if context["prepared"] else []:
                context_edges.extend({"source_photo_id": context["photo_id"], "next_photo_id": pid,
                                      "group_id": group["id"], "title": group["title"], "reason": group["reason"]}
                                     for pid in group["photo_ids"])
        routes = three_hop_routes(connect_edges)
        probe = None
        if args.probe_photo_id or args.probe_region_id:
            require(args.probe_photo_id and args.probe_region_id, "Provide both probe photo and region IDs")
            matches = [row for row in connections if row["source_region"]["photo_id"] == args.probe_photo_id and
                       row["source_region"]["region_id"] == args.probe_region_id]
            context = context_by_id.get(args.probe_photo_id)
            require(len(matches) == 1 and context is not None, "Probe must identify one current analysis region")
            connection = matches[0]
            connect_ids = {row["photo_id"] for row in connection["items"]}
            context_ids = {edge["next_photo_id"] for edge in context_edges if edge["source_photo_id"] == args.probe_photo_id}
            valid = connection["prepared"] and context["prepared"]
            probe = {"photo_id": args.probe_photo_id, "region_id": args.probe_region_id, "both_prepared": valid,
                     "connect_photo_ids": sorted(connect_ids), "context_photo_ids": sorted(context_ids),
                     "context_outside_connect": sorted(context_ids - connect_ids) if valid else None,
                     "context_beyond_connect_observed": valid and bool(context_ids - connect_ids),
                     "memberships_were_not_supplied_to_runtime": True}
        db.rollback()
        after, hashes_after = counters(db), fingerprints(db)
        readonly = before == after and hashes_before == hashes_after and runner.calls == 0 and not service.tasks
        counts_valid = len(photos) == args.expected_photos and len(anchors) == args.expected_regions and not issues
        complete = counts_valid and manifest_valid and all(row["prepared"] for row in connections + contexts)
        multiple_routes = len(routes["starts_with_three_hop_route"]) >= args.minimum_route_starts
        outside = not args.require_context_beyond_connect or bool(probe and probe["context_beyond_connect_observed"])
        report = {"schema_version": 1, "evaluated_at": datetime.now(timezone.utc).isoformat(), "synthetic": True,
            "evaluation_only": True, "metric_scope": "prepared data contracts and directed retrieval edges only",
            "agent_spec": AGENT_SPEC_VERSION, "retrieval_policy": RETRIEVAL_POLICY,
            "context_spec": CONTEXT_SPEC, "context_policy": CONTEXT_POLICY,
            "cache_model": os.environ.get("CG_MODEL", "gpt-5.4-mini"), "before": before, "after": after,
            "delta": {key: after[key] - before[key] for key in before},
            "logical_fingerprints_before": hashes_before, "logical_fingerprints_after": hashes_after,
            "read_only_verified": readonly, "execution_attempts": runner.calls, "scheduled_tasks": len(service.tasks),
            "expected_photos": args.expected_photos, "expected_regions": args.expected_regions,
            "actual_photos": len(photos), "actual_regions": len(anchors), "analysis_issues": issues,
            "manifest_ids_versions_match": manifest_valid if args.manifest else None,
            "connect": {"total": len(connections), "prepared": sum(row["prepared"] for row in connections),
                        "confirmed_empty": sum(row["confirmed_empty"] for row in connections),
                        "states": dict(Counter(row["state"] for row in connections)), "choices": connections},
            "contexts": {"total": len(contexts), "prepared": sum(row["prepared"] for row in contexts),
                         "confirmed_empty": sum(row["confirmed_empty"] for row in contexts),
                         "states": dict(Counter(row["state"] for row in contexts)), "photos": contexts},
            "capture_metadata": metadata, "connect_graph": {"edges": len(connect_edges), "three_hop_routes": routes},
            "context_graph": {"edges": context_edges, "distinct_photo_edges": len({(e["source_photo_id"],e["next_photo_id"]) for e in context_edges})},
            "probe": probe, "all_preparation_complete": complete,
            "multiple_three_hop_starts_observed": multiple_routes,
            "prepared_acceptance_passed": readonly and complete and metadata["valid"] and multiple_routes and outside,
            "ui_acceptance_verified": False, "semantic_accuracy_verified": False,
            "manual_acceptance_pending": ["Photo open automatically reveals its own context without an Organize button",
                "Every major-object choice is selectable; no fixed scenario/category routing",
                "Photo/context/Connect selections ignore stale replies",
                "Back restores selected region, result, context, expansion and scroll",
                "Failure, pending and reviewed empty have distinct visible states",
                "No Space menu, create, publish or save flow",
                "Multiple routes use meaningful subject pivots and context helps the next choice",
                "Same day is not asserted to be the same event; synthetic dates are disclosed"],
            "limitations": ["A completed empty pipeline is not a proof of exhaustive semantic absence.",
                "Graph paths do not prove meaningful semantic pivots, person identity or factual group descriptions.",
                "Stored context evidence proves recorded inspection/version/review structure, not visual truth.",
                "Read-only API data checks do not prove browser behavior, latency or Android behavior."]}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        db.close()
        if previous_model is None:
            os.environ.pop("CG_MODEL", None)
        else:
            os.environ["CG_MODEL"] = previous_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--expected-photos", type=int, default=20)
    parser.add_argument("--expected-regions", type=int, default=47)
    parser.add_argument("--minimum-route-starts", type=int, default=2)
    parser.add_argument("--probe-photo-id")
    parser.add_argument("--probe-region-id")
    parser.add_argument("--require-context-beyond-connect", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(args)
        print(json.dumps({"prepared_acceptance_passed": report["prepared_acceptance_passed"],
            "connect_prepared": report["connect"]["prepared"], "context_prepared": report["contexts"]["prepared"],
            "read_only_verified": report["read_only_verified"], "report": str(args.report)}, ensure_ascii=False))
        return 0 if report["prepared_acceptance_passed"] else 2
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, ValueError) and type(exc) is ValueError else type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
