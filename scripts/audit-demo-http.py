"""Measure authenticated prepared lookups over loopback HTTP, without model work.

Requires an idle, marked synthetic gallery and a --prepared-only demo server.
Reads SQLite in mode=ro and reads its existing token in process only. Preflight
uses a separate connection; each Connect/context lookup starts a fresh client,
then repeated lookups reuse that client's connection. Context uses GET only.
It never consumes a browser launch key or posts preparation, /runs or session.
Latency/read-only success is separate from prepared coverage and semantic quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from urllib.parse import quote, urlsplit

import httpx

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import apply_demo_model, effective_context_model, connection_models


def loopback_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in {"", "/"}):
        raise ValueError("Use an explicit http://127.0.0.1:<demo-port> origin only")
    port = parsed.port
    if port is None or port == 8765 or not 1024 <= port <= 65535:
        raise ValueError("A separate unprivileged demo port is required")
    return f"http://127.0.0.1:{port}"


def snapshot(db):
    return {
        "revision": db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0],
        "events": db.execute("SELECT count(*) FROM events").fetchone()[0],
        "model_timing_events": db.execute("SELECT count(*) FROM events WHERE kind='model_timing'").fetchone()[0],
        "runs": db.execute("SELECT count(*) FROM runs").fetchone()[0],
        "active_runs": db.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0],
    }


def stats(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {"count": len(values), "min_ms": round(ordered[0], 3),
            "median_ms": round(statistics.median(ordered), 3),
            "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 3),
            "max_ms": round(ordered[-1], 3)}


def fingerprints(db):
    """Detect in-place cache/evidence edits even when row counts do not change."""
    result = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        # Only digests leave this function; stored images, private history and
        # provider payloads never become report text or HTTP input.
        rows = sorted(hashlib.sha256(repr(tuple(row)).encode()).hexdigest()
                      for row in db.execute("SELECT * FROM " + quoted))
        result[name] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    return result


def response_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def result_summary(ready):
    result = ready.get("result") or {}
    if ready.get("state") not in {"ready", "pending"}:
        raise ValueError("Unexpected readiness response")
    return {"state": ready.get("state"), "revision": ready.get("revision"),
            "cache_model": ready.get("cache_model"),
            "response_sha256": response_digest(ready),
            "complete": result.get("complete"), "grouping_status": result.get("grouping_status"),
            "item_count": len(result.get("items", [])), "group_count": len(result.get("groups", [])),
            "groups": [{"title": group["title"], "photo_ids": group["photo_ids"]}
                       for group in result.get("groups", [])]}


def context_summary(value, photo_id):
    state = value.get("state")
    if value.get("photo_id") != photo_id or state not in {"ready", "empty", "pending", "running", "failed"}:
        raise ValueError("Unexpected photo context response")
    context = value.get("context")
    if state in {"ready", "empty"}:
        from connected_gallery.domain.context import PhotoContext
        try:
            parsed = PhotoContext.model_validate({**context, "complete": True}) if isinstance(context, dict) else None
        except ValueError:
            raise ValueError("Prepared photo context contents do not match the API contract") from None
        if parsed is None or (state == "ready") != bool(parsed.groups):
            raise ValueError("Prepared photo context state does not match its contents")
    elif context is not None:
        raise ValueError("Unprepared photo context must not claim prepared contents")
    groups = (context or {}).get("groups", [])
    return {"photo_id": photo_id, "state": state, "revision": value.get("revision"),
            "response_sha256": response_digest(value), "group_count": len(groups),
            "member_count": len({pid for group in groups for pid in group["photo_ids"]}),
            "summary_length": len((context or {}).get("summary", ""))}


def run(args, *, client_factory=None):
    origin = loopback_origin(args.url)
    if not 1 <= args.repeat <= 50:
        raise ValueError("Repeat count must be between 1 and 50")
    root = args.data_dir.resolve()
    marker = root / "synthetic-demo.json"
    if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("synthetic") is not True:
        raise ValueError("Only a marked synthetic gallery may be audited")
    demo_model = apply_demo_model(root)
    if args.report.suffix.lower() != ".json" or args.report.resolve() == marker:
        raise ValueError("Use a separate JSON report path")
    token = (root / "server-token.txt").read_text(encoding="utf-8").strip()
    if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
        raise ValueError("Existing demo token is invalid")
    headers = {"Authorization": "Bearer " + token}
    client_factory = client_factory or httpx.Client
    def new_client():
        return client_factory(base_url=origin, headers=headers, trust_env=False, follow_redirects=False, timeout=15)
    db = sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    try:
        before = snapshot(db)
        hashes_before = fingerprints(db)
        if before["active_runs"]:
            raise ValueError("Preparation is still active; audit only after queued/running work finishes")
        photo_ids = {row[0] for row in db.execute("SELECT id FROM photos")}
        anchors = []
        for pid, data in db.execute("SELECT photo_id,data FROM analyses ORDER BY photo_id"):
            if pid not in photo_ids:
                continue
            for region in json.loads(data).get("regions", []):
                anchors.append({"photo_id": pid, "region_id": region["id"], "box": region["box"],
                                "label": region["label"], "kind": region["kind"]})
        if not anchors:
            raise ValueError("No analyzed sample regions are available")
        # Preflight cannot read private credentials from any other endpoint and
        # cannot follow a redirect to another origin. It starts no work.
        with new_client() as client:
            health_response = client.get("/health")
            health_response.raise_for_status()
            health = health_response.json()
            catalog_response = client.get("/demo/catalog")
            catalog_response.raise_for_status()
            catalog = catalog_response.json()
        if catalog.get("live_enabled") is not False:
            raise ValueError("Launch the browser server with --prepared-only before auditing")
        if (catalog.get("synthetic") is not True or {p["id"] for p in catalog["assets"]} != photo_ids or
                health.get("revision") != before["revision"]):
            raise ValueError("HTTP server and local synthetic gallery do not match")
        report = {"synthetic": True, "origin": origin, "prepared_only": True, "demo_model": demo_model,
                  "context_model": effective_context_model(),
                  "compatible_connection_models": connection_models()[1:],
                  "model_profile_source": "local public marker; not independent proof of the server's model configuration",
                  "transport": "loopback HTTP; authenticated JSON endpoint; image rendering excluded",
                  "method": "separate preflight client; fresh client per Connect anchor and photo context, then repeated keep-alive requests",
                  "photo_count": len(photo_ids), "agent_spec": health.get("agent_spec"),
                  "before": before, "repeats_per_anchor": args.repeat, "repeats_per_context": args.repeat,
                  "anchors": [], "contexts": []}

        def measure(send, summarize):
            if snapshot(db)["active_runs"]:
                raise ValueError("Concurrent preparation started during audit; discard these timings")
            times, observations = [], []
            with new_client() as client:
                for _ in range(args.repeat + 1):
                    start = time.perf_counter()
                    response = send(client)
                    response.raise_for_status()
                    value = response.json()
                    times.append((time.perf_counter() - start) * 1000)
                    observed = summarize(value)
                    if type(observed["revision"]) is not int or observed["revision"] != before["revision"]:
                        raise ValueError("Lookup revision differs from the audited gallery snapshot")
                    observations.append(observed)
            return times, {"first_http_ms": round(times[0], 3),
                           "repeat_http_ms": [round(value, 3) for value in times[1:]],
                           "repeat_lookup": stats(times[1:]),
                           "stable_result": all(value == observations[0] for value in observations),
                           **observations[0]}

        first_times, repeat_times, ready_repeat_times = [], [], []
        for anchor in anchors:
            query = {"anchor": anchor, "direction": "related", "request_revision": before["revision"]}
            times, observed = measure(lambda client: client.post("/explorations/ready", json=query), result_summary)
            first_times.append(times[0])
            repeat_times.extend(times[1:])
            if observed["state"] == "ready":
                ready_repeat_times.extend(times[1:])
            report["anchors"].append({"photo_id": anchor["photo_id"], "region_id": anchor["region_id"],
                                      "kind": anchor["kind"], "label": anchor["label"],
                                      **observed})
        context_first_times, context_repeat_times, context_prepared_times = [], [], []
        for photo_id in sorted(photo_ids):
            times, observed = measure(lambda client: client.get(f"/assets/{quote(photo_id, safe='')}/context"),
                                      lambda value: context_summary(value, photo_id))
            context_first_times.append(times[0])
            context_repeat_times.extend(times[1:])
            if observed["state"] in {"ready", "empty"}:
                context_prepared_times.extend(times[1:])
            report["contexts"].append(observed)
        after = snapshot(db)
        hashes_after = fingerprints(db)
        report["after"] = after
        report["delta"] = {key: after[key] - before[key] for key in before}
        report["anchor_count"] = len(anchors)
        report["ready_count"] = sum(row["state"] == "ready" for row in report["anchors"])
        report["pending_count"] = len(anchors) - report["ready_count"]
        report["first_lookup_after_preflight_ms"] = round(first_times[0], 3)
        report["first_client_lookup"] = stats(first_times)
        report["repeated_lookup"] = stats(repeat_times)
        report["ready_repeated_lookup"] = stats(ready_repeat_times)
        report["context_count"] = len(report["contexts"])
        report["context_states"] = {state: sum(row["state"] == state for row in report["contexts"])
                                    for state in ("ready", "empty", "pending", "running", "failed")}
        report["context_first_client_lookup"] = stats(context_first_times)
        report["context_repeated_lookup"] = stats(context_repeat_times)
        report["context_prepared_repeated_lookup"] = stats(context_prepared_times)
        report["logical_fingerprints_before"] = hashes_before
        report["logical_fingerprints_after"] = hashes_after
        report["zero_work_observed"] = before == after and hashes_before == hashes_after
        report["stable_results"] = all(row["stable_result"] for row in report["anchors"] + report["contexts"])
        report["lookup_audit_passed"] = report["zero_work_observed"] and report["stable_results"]
        report["all_lookups_prepared"] = (report["ready_count"] == report["anchor_count"] and
            sum(report["context_states"][s] for s in ("ready", "empty")) == report["context_count"])
        report["semantic_accuracy_verified"] = False
        report["metric_scope"] = "HTTP latency and observed non-mutation only; readiness counts are not semantic or UI acceptance"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key not in {
            "anchors", "contexts", "before", "after", "logical_fingerprints_before", "logical_fingerprints_after"}}, ensure_ascii=False))
        return 0 if report["lookup_audit_passed"] else 1
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / ".runtime" / "demo")
    parser.add_argument("--url", default="http://127.0.0.1:8877")
    parser.add_argument("--repeat", type=int, default=5, help="Repeated requests after each fresh client's first lookup")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except (ValueError, OSError, sqlite3.Error, httpx.HTTPError) as exc:
        # Avoid transport reprs/request headers: an auth key must never be printed.
        if isinstance(exc, ValueError):
            raise SystemExit(str(exc)) from None
        raise SystemExit(f"HTTP audit failed ({type(exc).__name__}); no credential details were logged") from None


if __name__ == "__main__":
    main()
