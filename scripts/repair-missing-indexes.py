"""Backfill derived indexes through the live API, preserving existing analysis.

Reads local state without changing it. Repeating after an interrupted request is
safe: the API materializes only missing representations and checks photo/evidence
versions before committing. Outputs aggregate counts, never photo identifiers.
"""
import json
import sqlite3
import time
import urllib.request
from pc_client import urlopen
from pathlib import Path

from connected_gallery.adapters.models import LocalModels
from connected_gallery.application.indexing import AnalysisIndexing
from connected_gallery.domain.models import PhotoAnalysis


def main():
    base = "http://127.0.0.1:8765"
    with urlopen(base + "/health", timeout=15) as response:
        if json.load(response).get("agent_spec", 0) < 12:
            raise RuntimeError("Start the server with selected-region indexing first")
    db = sqlite3.connect("file:.runtime/gallery.sqlite?mode=ro", uri=True)
    db.execute("BEGIN")
    versions = dict(db.execute("SELECT id,version FROM photos"))
    keys = {r[0] for r in db.execute("SELECT key FROM vectors")}
    index = AnalysisIndexing(None, LocalModels(Path(".runtime")))
    todo = []
    for raw, in db.execute("SELECT data FROM analyses"):
        analysis = PhotoAnalysis.model_validate_json(raw)
        if not all(key in keys for key in index.keys(analysis, versions[analysis.photo_id])):
            todo.append(analysis.photo_id)
    db.close()
    print(json.dumps({"photos_to_repair": len(todo)}), flush=True)
    added, errors, consecutive_errors = 0, 0, 0
    started = time.monotonic()
    for n, pid in enumerate(todo, 1):
        for attempt in range(3):
            try:
                request = urllib.request.Request(base + f"/assets/{pid}/reindex", data=b"{}",
                                                 headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=20) as response:
                    added += json.load(response)["indexes_added"]
                consecutive_errors = 0
                break
            except Exception:
                if attempt == 2:
                    errors += 1
                    consecutive_errors += 1
                else:
                    time.sleep(1)
        if consecutive_errors >= 3:
            raise RuntimeError("Repeated API failures; resume after the server is available")
        if n % 50 == 0 or n == len(todo):
            print(json.dumps({"processed": n, "total": len(todo), "indexes_added": added,
                              "errors": errors, "seconds": round(time.monotonic() - started, 2)}), flush=True)


if __name__ == "__main__":
    main()
