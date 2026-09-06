"""Synthetic vectors benchmark storage/retrieval only, not model or user latency."""

import json, time, statistics
from pathlib import Path
import numpy as np
from connected_gallery.adapters.store import Store
from connected_gallery.domain.models import PhotoAsset

s = Store(Path("work/index-benchmark"))
rng = np.random.default_rng(17)
for i in range(1000):
    pid = str(i)
    s.upsert(
        PhotoAsset(
            id=pid,
            device_id="synthetic",
            version="1",
            width=1,
            height=1,
            captured_at=f"{2010 + i % 10}-01-01T12:00:00Z",
            time_source="exif",
        )
    )
    s.vector(pid, pid, "synthetic-768", rng.normal(size=768))
allowed = {p.id for p in s.photos(2015)}
query = rng.normal(size=768)
times = []
for _ in range(30):
    start = time.perf_counter()
    hits = s.search("synthetic-768", query, allowed, 20)
    times.append((time.perf_counter() - start) * 1000)
    assert all(h["photo_id"] in allowed for h in hits)
report = {
    "source": "synthetic-index-only",
    "photos": 1000,
    "vectors": 1000,
    "eligible_year_photos": len(allowed),
    "queries": len(times),
    "p50_ms": round(statistics.median(times), 2),
    "p95_ms": round(float(np.percentile(times, 95)), 2),
    "excludes": ["model inference", "network", "Android rendering", "user evaluation"],
}
Path("docs/index-benchmark.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
s.close()
