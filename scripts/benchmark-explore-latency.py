"""Connect exploration benchmark: runs anchor cases against the running PC
server and records per-stage timings and result quality, so the same cases
can be compared before/after a server change.

IDs, reasons, and raw events stay in work/; docs/ only gets aggregate numbers.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SERVER = "http://127.0.0.1:8765"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="docs/explore-latency-benchmark-cases.json")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--data-dir", default=".runtime")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jitter", type=float, default=0.0,
                        help="shift anchor boxes by this normalized amount so a run cannot hit the prepared cache")
    return parser.parse_args()


def api(path, payload=None, timeout=15):
    from pc_client import urlopen  # imported lazily, after CG_DATA_DIR is set
    request = urllib.request.Request(
        SERVER + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_all_events(rid):
    events, cursor = [], 0
    while True:
        page = api(f"/runs/{rid}/events?after={cursor}")
        new = page["events"]
        events.extend(new)
        if page["cursor"] == cursor or not new:
            break
        cursor = page["cursor"]
    return events


def derive_metrics(started, wall_started, events, run, expected, acceptable, forbidden):
    for e in events:
        e["_offset"] = round(e["at"] - wall_started, 3)
    queue_wait = None
    for e in events:
        if e["kind"] in ("progress", "model_timing"):
            queue_wait = e["_offset"]
            break
    model_events = [e for e in events if e["kind"] == "model_timing"]
    model_turns = len(model_events)
    model_seconds = round(sum(e["data"].get("seconds", 0.0) for e in model_events), 3)
    per_turn = [{"turn": e["data"].get("turn"), "seconds": e["data"].get("seconds"),
                 "finalizing": e["data"].get("finalizing"), "repair": e["data"].get("repair")}
                for e in model_events]

    tool_events = [e for e in events if e["kind"] == "tool_timing"]
    tool_seconds_by_name = {}
    for e in tool_events:
        name = e["data"].get("name", "unknown")
        tool_seconds_by_name[name] = round(tool_seconds_by_name.get(name, 0.0) + e["data"].get("seconds", 0.0), 3)
    ocr_calls = [e for e in tool_events if e["data"].get("name") == "recognize_text"]
    ocr_seconds = round(sum(e["data"].get("seconds", 0.0) for e in ocr_calls), 3)

    review_events = [e for e in events if e["kind"] in ("evidence_review", "empty_evidence_review")]
    review_seconds = review_events[-1]["data"].get("seconds") if review_events else None
    review_kind = review_events[-1]["kind"] if review_events else None

    initial_candidates = None
    ic_events = [e for e in events if e["kind"] == "initial_candidates"]
    if ic_events:
        data = ic_events[0]["data"]
        initial_candidates = {k: data[k] for k in ("seconds", "count", "channels") if k in data}

    results_events = [e for e in events if e["kind"] == "results"]
    results_at_seconds = round(results_events[0]["_offset"], 3) if results_events else None

    result = run.get("result") or {}
    items = [{"photo_id": x["photo_id"], "reason": x.get("reason")} for x in result.get("items", [])]
    groups = result.get("groups") or []
    item_ids = {x["photo_id"] for x in items}

    expected_set, acceptable_set, forbidden_set = set(expected), set(acceptable), set(forbidden)
    expected_hit = sorted(item_ids & expected_set)
    expected_missed = sorted(expected_set - item_ids)
    forbidden_hit = sorted(item_ids & forbidden_set)
    unexpected = sorted(item_ids - expected_set - acceptable_set - forbidden_set)
    recall = (len(expected_hit) / len(expected_set)) if expected_set else None
    empty_expected_met = (not expected_set) and (not item_ids)

    return {
        "total_seconds": round(time.monotonic() - started, 3),
        "queue_wait_seconds": queue_wait,
        "model_turns": model_turns,
        "model_seconds": model_seconds,
        "model_turn_detail": per_turn,
        "tool_seconds_by_name": tool_seconds_by_name,
        "ocr_seconds": ocr_seconds,
        "ocr_calls": len(ocr_calls),
        "review_seconds": review_seconds,
        "review_kind": review_kind,
        "initial_candidates": initial_candidates,
        "results_at_seconds": results_at_seconds,
        "status": run["status"],
        "error": run.get("error"),
        "items": items,
        "groups": groups,
        "expected_hit": expected_hit,
        "expected_missed": expected_missed,
        "forbidden_hit": forbidden_hit,
        "unexpected": unexpected,
        "recall": round(recall, 3) if recall is not None else None,
        "empty_expected_met": empty_expected_met,
    }


DRY_RUN = False
JITTER = 0.0


def run_case(tag, case, repeat_index, deadline):
    anchor = dict(case["anchor"])
    anchor.setdefault("region_id", None)
    if JITTER and anchor.get("box"):
        # A slightly different selection: same meaning, new prepared-cache key.
        box = dict(anchor["box"])
        box["x"] = round(min(box["x"] + JITTER, 1 - box["width"]), 6)
        box["y"] = round(min(box["y"] + JITTER, 1 - box["height"]), 6)
        anchor["box"] = box
    direction = case.get("direction", "related")
    revision = repeat_index + 1
    idem_key = f"bench-explore-{tag}-{case['id']}-{repeat_index}-{uuid4()}"
    payload = {
        "role": "explorer",
        "explore": {
            "anchor": anchor,
            "direction": direction,
            "year": None,
            "request_revision": revision,
        },
        "idempotency_key": idem_key,
    }
    if DRY_RUN:
        print("DRY-RUN POST /runs " + json.dumps(payload, ensure_ascii=False))
        return None, None, None

    started = time.monotonic()
    wall_started = time.time()
    run = api("/runs", payload)
    rid = run["id"]
    while run["status"] in ("queued", "running"):
        if time.monotonic() - started > deadline:
            api(f"/runs/{rid}/cancel", {})
            run = api(f"/runs/{rid}")
            break
        time.sleep(0.5)
        run = api(f"/runs/{rid}")

    raw_events = fetch_all_events(rid)
    metrics = derive_metrics(started, wall_started, raw_events, run,
                              case.get("expected", []), case.get("acceptable", []), case.get("forbidden", []))
    private_record = {"run_id": rid, "case_id": case["id"], "repeat": repeat_index,
                       "anchor": anchor, "direction": direction, "raw_events": raw_events, **metrics}
    return metrics, private_record, rid


def main():
    args = parse_args()
    global DRY_RUN, JITTER
    DRY_RUN = args.dry_run
    JITTER = args.jitter

    os.environ["CG_DATA_DIR"] = args.data_dir
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    cases_path = Path(args.cases)
    if not cases_path.exists():
        raise SystemExit(f"Cases manifest not found: {cases_path}")
    manifest = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"Unknown case ids: {sorted(missing)}")

    health = {} if DRY_RUN else api("/health")
    deadline = health.get("explore_timeout_seconds", 45) + 30

    private_path = Path(f"work/explore-latency-{args.tag}-private.json")
    private_records = []
    if private_path.exists():
        private_records = json.loads(private_path.read_text(encoding="utf-8"))

    report_path = Path("docs/explore-latency-benchmark.json")
    report = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    case_reports = []
    for case in cases:
        # Repeats continue across invocations so (id, repeat) stays unique within a tag.
        offset = sum(1 for r in private_records if r.get("case_id") == case["id"])
        for repeat_index in range(offset, offset + args.repeat):
            metrics, private_record, rid = run_case(args.tag, case, repeat_index, deadline)
            if DRY_RUN:
                continue
            private_records.append(private_record)
            summary_line = {
                "case": case["id"], "repeat": repeat_index, "status": metrics["status"],
                "total_seconds": metrics["total_seconds"], "recall": metrics["recall"],
                "forbidden_hit": len(metrics["forbidden_hit"]),
            }
            print(json.dumps(summary_line, ensure_ascii=False), flush=True)
            case_reports.append({
                "id": case["id"], "repeat": repeat_index, "status": metrics["status"],
                "prepared_cache_hit": any(e.get("kind") == "prepared_cache_hit"
                                          for e in private_record["raw_events"]),
                "total_seconds": metrics["total_seconds"],
                "model_turns": metrics["model_turns"], "model_seconds": metrics["model_seconds"],
                "ocr_seconds": metrics["ocr_seconds"], "ocr_calls": metrics["ocr_calls"],
                "review_seconds": metrics["review_seconds"],
                "review_kind": metrics["review_kind"],
                "results_at_seconds": metrics["results_at_seconds"],
                "tool_seconds_by_name": metrics["tool_seconds_by_name"],
                "recall": metrics["recall"],
                "forbidden_hit_count": len(metrics["forbidden_hit"]),
                "unexpected_count": len(metrics["unexpected"]),
                "expected_count": len(case.get("expected", [])),
                "item_count": len(metrics["items"]),
                "error": metrics["error"],
            })

    if DRY_RUN:
        print(f"DRY-RUN: {len(cases)} case(s) x {args.repeat} repeat(s); no /runs calls made.")
        return

    Path("work").mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps(private_records, ensure_ascii=False, indent=2), encoding="utf-8")

    Path("docs").mkdir(parents=True, exist_ok=True)
    # Runs under the same tag accumulate; a tag is a measurement condition, not one invocation.
    previous = report.get(args.tag, {}) if isinstance(report.get(args.tag), dict) else {}
    report[args.tag] = {
        "started_at": previous.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "server": health,
        "cases": list(previous.get("cases", [])) + case_reports,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    header = f"{'case':<20} {'total s':>8} {'turns':>6} {'model s':>8} {'ocr s':>7} {'review s':>9} {'recall':>7} {'forbid':>7} {'items':>6}"
    print(header)
    print("-" * len(header))
    for row in case_reports:
        print(f"{row['id']:<20} {row['total_seconds']:>8} {row['model_turns']:>6} {row['model_seconds']:>8} "
              f"{row['ocr_seconds']:>7} {str(row['review_seconds']):>9} {str(row['recall']):>7} "
              f"{row['forbidden_hit_count']:>7} {row['item_count']:>6}")


if __name__ == "__main__":
    main()
