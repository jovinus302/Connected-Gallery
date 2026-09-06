"""Aggregate explicit human evaluation rows; do not infer success or intent from model scores."""

import csv, json, statistics, sys
from pathlib import Path

rows = list(
    csv.DictReader(
        Path(sys.argv[1] if len(sys.argv) > 1 else "docs/evaluation-template.csv").open(
            encoding="utf-8-sig"
        )
    )
)
if not rows:
    print(
        json.dumps(
            {"status": "not_measured", "reason": "No human evaluation rows"}, indent=2
        )
    )
    raise SystemExit(0)


def values(key):
    return [float(r[key]) for r in rows if r.get(key, "").strip()]


def median(key):
    xs = values(key)
    return statistics.median(xs) if xs else None


def ratio(num, den):
    a, b = sum(values(num)), sum(values(den))
    return a / b if b else None


reuse = values("reuse_1_to_5")
find = values("success")
report = {
    "tasks": len(rows),
    "participants": len({r["participant_id"] for r in rows}),
    "find_success_rate": sum(find) / len(find) if find else None,
    "find_median_ms": median("find_ms"),
    "baseline_median_ms": median("baseline_ms"),
    "object_tap_rate": ratio("object_taps", "eligible_views"),
    "median_hops": median("hops"),
    "reuse_ge_4": sum(v >= 4 for v in reuse) / len(reuse) if reuse else None,
    "p_at_5_mean": statistics.mean(values("p_at_5")) if values("p_at_5") else None,
    "first_result_median_ms": median("first_result_ms"),
}
print(json.dumps(report, indent=2))
