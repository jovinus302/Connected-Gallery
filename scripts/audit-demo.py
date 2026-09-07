"""Read-only audit of a prepared synthetic gallery. No answer keys enter retrieval."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from connected_gallery.application.demo_profile import apply_demo_model, connection_models


class NoExecution:
    async def execute(self, *args):
        raise AssertionError("Ready audit must not execute a model")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_dir.resolve()
    if not (root / "synthetic-demo.json").exists():
        raise SystemExit("Only a marked synthetic gallery may be audited")
    apply_demo_model(root)
    from connected_gallery.adapters.store import Store
    from connected_gallery.application.service import RunService
    from connected_gallery.domain.models import ExploreInput, SemanticAnchor
    store = Store(root)
    service = RunService(store, NoExecution())
    before = store.rows("SELECT count(*) AS n FROM events")[0]["n"]
    report = {"synthetic": True, "photos": len(store.photos()), "revision": store.revision, "anchors": []}
    report["connection_model"] = connection_models()[0]
    report["compatible_connection_models"] = connection_models()[1:]
    try:
        for p in store.photos():
            analysis = store.analysis(p.id) or {}
            for region in analysis.get("regions", []):
                anchor = SemanticAnchor.model_validate({k: region[k] for k in ("photo_id", "box", "kind", "label")} | {"region_id": region["id"]})
                query = ExploreInput(anchor=anchor)
                times = []
                for _ in range(10):
                    start = time.perf_counter()
                    ready = service.ready(query)
                    times.append((time.perf_counter() - start) * 1000)
                report["anchors"].append({"photo_id": p.id, "region_id": region["id"],
                    "label": region["label"], "kind": region["kind"], "box": region["box"],
                    "state": ready["state"], "lookup_ms": times,
                    "cache_model": ready.get("cache_model"),
                    "result": ready.get("result")})
        after = store.rows("SELECT count(*) AS n FROM events")[0]["n"]
        report["event_delta"] = after - before
        report["model_calls_during_lookup"] = 0
        report["ready_count"] = sum(a["state"] == "ready" for a in report["anchors"])
        report["anchor_count"] = len(report["anchors"])
        report["index"] = store.rows("SELECT space,count(*) AS count FROM vectors GROUP BY space")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("anchors", "index")}, ensure_ascii=False))
    finally:
        store.close()


if __name__ == "__main__":
    main()
