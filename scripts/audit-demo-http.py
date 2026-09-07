"""Measure authenticated prepared lookups over loopback HTTP, without model work.

Requires an idle, marked synthetic gallery and a --prepared-only demo server.
Reads SQLite in mode=ro and reads its existing token in process only. Preflight
uses a separate connection; each anchor's first lookup uses a fresh HTTP client,
then repeated lookups reuse that client's connection. It never posts /runs.
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
from urllib.parse import urlsplit

import httpx

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "server"))
from connected_gallery.application.demo_profile import apply_demo_model


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
            "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 3),
            "max_ms": round(ordered[-1], 3)}


def result_summary(ready):
    result = ready.get("result") or {}
    if ready.get("state") not in {"ready", "pending"}:
        raise ValueError("Unexpected readiness response")
    return {"state": ready.get("state"), "revision": ready.get("revision"),
            "response_sha256": hashlib.sha256(json.dumps(ready, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            "complete": result.get("complete"), "grouping_status": result.get("grouping_status"),
            "item_count": len(result.get("items", [])), "group_count": len(result.get("groups", [])),
            "groups": [{"title": group["title"], "photo_ids": group["photo_ids"]}
                       for group in result.get("groups", [])]}


def run(args):
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
    db = sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        before = snapshot(db)
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
        with httpx.Client(base_url=origin, headers=headers, trust_env=False, follow_redirects=False, timeout=15) as client:
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
                  "transport": "loopback HTTP; authenticated JSON endpoint; image rendering excluded",
                  "method": "separate preflight client; fresh client per anchor then repeated keep-alive requests",
                  "photo_count": len(photo_ids), "agent_spec": health.get("agent_spec"),
                  "before": before, "repeats_per_anchor": args.repeat, "anchors": []}
        first_times, repeat_times, ready_repeat_times = [], [], []
        for anchor in anchors:
            if snapshot(db)["active_runs"]:
                raise ValueError("Concurrent preparation started during audit; discard these timings")
            query = {"anchor": anchor, "direction": "related", "request_revision": before["revision"]}
            times, observations = [], []
            with httpx.Client(base_url=origin, headers=headers, trust_env=False, follow_redirects=False, timeout=15) as client:
                for _ in range(args.repeat + 1):
                    start = time.perf_counter()
                    response = client.post("/explorations/ready", json=query)
                    response.raise_for_status()
                    ready = response.json()
                    times.append((time.perf_counter() - start) * 1000)
                    observations.append(result_summary(ready))
            first_times.append(times[0])
            repeat_times.extend(times[1:])
            if observations[0]["state"] == "ready":
                ready_repeat_times.extend(times[1:])
            report["anchors"].append({"photo_id": anchor["photo_id"], "region_id": anchor["region_id"],
                                      "kind": anchor["kind"], "label": anchor["label"],
                                      "first_http_ms": round(times[0], 3),
                                      "repeat_http_ms": [round(value, 3) for value in times[1:]],
                                      "stable_result": all(value == observations[0] for value in observations),
                                      **observations[0]})
        after = snapshot(db)
        report["after"] = after
        report["delta"] = {key: after[key] - before[key] for key in before}
        report["anchor_count"] = len(anchors)
        report["ready_count"] = sum(row["state"] == "ready" for row in report["anchors"])
        report["pending_count"] = len(anchors) - report["ready_count"]
        report["first_lookup_after_preflight_ms"] = round(first_times[0], 3)
        report["first_client_lookup"] = stats(first_times)
        report["repeated_lookup"] = stats(repeat_times)
        report["ready_repeated_lookup"] = stats(ready_repeat_times)
        report["zero_work_observed"] = before == after
        report["stable_results"] = all(row["stable_result"] for row in report["anchors"])
        report["lookup_audit_passed"] = report["zero_work_observed"] and report["stable_results"]
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key not in {"anchors", "before", "after"}}, ensure_ascii=False))
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
