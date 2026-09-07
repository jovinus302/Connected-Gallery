from __future__ import annotations
import hashlib
import io
import json
import sqlite3
import threading
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
from connected_gallery.domain.models import PhotoAsset, PhotoAnalysis, Box


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Store:
    """One connection, serialized transactions; artifacts and vectors share deletion lifetime."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "images").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "gallery.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, version TEXT, year INTEGER, data TEXT);
          CREATE TABLE IF NOT EXISTS analyses(photo_id TEXT PRIMARY KEY, data TEXT);
          CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(photo_id UNINDEXED, text);
          CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY, photo_id TEXT, space TEXT, data BLOB);
          CREATE TABLE IF NOT EXISTS artifacts(key TEXT PRIMARY KEY, photo_id TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, key TEXT UNIQUE, request TEXT, status TEXT, result TEXT, error TEXT, started REAL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, data TEXT, at REAL);
          CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, revision INTEGER, data TEXT);
          CREATE TABLE IF NOT EXISTS spaces(id TEXT PRIMARY KEY, data TEXT);
          CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, data TEXT);
          CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value INTEGER);
          INSERT OR IGNORE INTO state VALUES('revision', 0);
        """)
        self.db.commit()

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def write(self, sql, args=()):
        with self.lock, self.db:
            self.db.execute(sql, args)

    @property
    def revision(self):
        return self.rows("SELECT value FROM state WHERE key='revision'")[0]["value"]

    def bump(self):
        self.write("UPDATE state SET value=value+1 WHERE key='revision'")
        self.write("DELETE FROM cache")

    def photo(self, photo_id):
        rows = self.rows("SELECT data FROM photos WHERE id=?", (photo_id,))
        if not rows:
            raise ValueError("Unknown photo ID")
        return PhotoAsset.model_validate_json(rows[0]["data"])

    def photos(self, year=None):
        q, a = (
            ("SELECT data FROM photos ORDER BY id", ())
            if year is None
            else ("SELECT data FROM photos WHERE year=? ORDER BY id", (year,))
        )
        return [PhotoAsset.model_validate_json(r["data"]) for r in self.rows(q, a)]

    def upsert(self, asset):
        with self.lock:
            old = self.rows("SELECT version FROM photos WHERE id=?", (asset.id,))
            if old and old[0]["version"] == asset.version:
                return
            if old:
                self.delete(asset.id)
            self.write(
                "INSERT OR REPLACE INTO photos VALUES(?,?,?,?)",
                (asset.id, asset.version, asset.year, asset.model_dump_json()),
            )
            self.bump()

    def image_path(self, photo_id):
        # IDs are validated by the repository; hash keeps all paths under images/.
        self.photo(photo_id)
        return (
            self.root
            / "images"
            / (hashlib.sha256(photo_id.encode()).hexdigest() + ".jpg")
        )

    def put_image(self, photo_id, data):
        with self.lock:
            path = self.image_path(photo_id)
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2048, 2048))
                out = io.BytesIO()
                image.save(out, "JPEG", quality=90)
            payload = out.getvalue()
            if path.exists() and path.read_bytes() == payload:
                return
            temp = path.with_suffix(".tmp")
            temp.write_bytes(payload)
            temp.replace(path)
            self.clear_analysis(photo_id)
            self.bump()

    def put_region_image(self, photo_id, box, data):
        self.photo(photo_id)
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=90)
        import base64

        key = (
            "region-preview:"
            + hashlib.sha256(encoded([photo_id, box.model_dump()]).encode()).hexdigest()
        )
        value = encoded({"jpeg": base64.b64encode(out.getvalue()).decode()})
        old = self.rows("SELECT data FROM artifacts WHERE key=?", (key,))
        if old and old[0]["data"] == value:
            return
        self.write(
            "INSERT OR REPLACE INTO artifacts VALUES(?,?,?)", (key, photo_id, value)
        )
        self.bump()

    def read_image(self, photo_id, box: Box | None = None):
        self.photo(photo_id)
        if box:
            key = (
                "region-preview:"
                + hashlib.sha256(
                    encoded([photo_id, box.model_dump()]).encode()
                ).hexdigest()
            )
            rows = self.rows("SELECT data FROM artifacts WHERE key=?", (key,))
            if rows:
                import base64

                return Image.open(
                    io.BytesIO(base64.b64decode(json.loads(rows[0]["data"])["jpeg"]))
                ).convert("RGB")
        with Image.open(self.image_path(photo_id)) as im:
            image = im.convert("RGB")
        if box:
            w, h = image.size
            image = image.crop(
                (
                    int(box.x * w),
                    int(box.y * h),
                    max(int((box.x + box.width) * w), int(box.x * w) + 1),
                    max(int((box.y + box.height) * h), int(box.y * h) + 1),
                )
            )
        return image

    def clear_analysis(self, photo_id):
        for table in ("analyses", "evidence_fts", "vectors", "artifacts"):
            self.write(f"DELETE FROM {table} WHERE photo_id=?", (photo_id,))

    def delete(self, photo_id):
        with self.lock:
            try:
                path = self.image_path(photo_id)
            except ValueError:
                return
            path.unlink(missing_ok=True)
            self.clear_analysis(photo_id)
            self.write("DELETE FROM photos WHERE id=?", (photo_id,))
            for row in self.rows("SELECT id,data FROM spaces"):
                space = json.loads(row["data"])
                space["items"] = [
                    x for x in space["items"] if x["photo_id"] != photo_id
                ]
                self.write(
                    "UPDATE spaces SET data=? WHERE id=?", (encoded(space), row["id"])
                )
            # Historical run results may contain deleted photo metadata; purge their contents.
            self.write("UPDATE runs SET result=NULL WHERE result IS NOT NULL")
            self.write("DELETE FROM events")
            self.write("DELETE FROM runs WHERE json_extract(request,'$.explore.anchor.photo_id')=? "
                       "OR EXISTS(SELECT 1 FROM json_each(runs.request,'$.photo_ids') WHERE value=?)",
                       (photo_id, photo_id))
            self.write("DELETE FROM feedback WHERE json_extract(data,'$.photo_id')=?", (photo_id,))
            self.bump()

    def analysis(self, photo_id):
        rows = self.rows("SELECT data FROM analyses WHERE photo_id=?", (photo_id,))
        return json.loads(rows[0]["data"]) if rows else None

    def has_vector(self, key):
        return bool(self.rows("SELECT key FROM vectors WHERE key=?", (key,)))

    def analysis_snapshot(self):
        with self.lock:
            return (self.photos(), [json.loads(r["data"]) for r in self.rows("SELECT data FROM analyses")],
                    {r["key"] for r in self.rows("SELECT key FROM vectors")})

    def save_analysis(self, analysis: PhotoAnalysis, vectors=(), expected_version=None, expected_analysis=None, run_id=None):
        with self.lock:
            photo = self.photo(analysis.photo_id)
            if expected_version is not None and photo.version != expected_version:
                raise ValueError("Photo changed during indexing")
            if expected_analysis is not None and self.analysis(analysis.photo_id) != expected_analysis:
                raise ValueError("Analysis changed during indexing; retry with current evidence")
            for region in analysis.regions:
                if region.photo_id != analysis.photo_id:
                    raise ValueError("Region belongs to another photo")
            encoded_vectors = []
            for key, pid, space, vector in vectors:
                if pid != analysis.photo_id:
                    raise ValueError("Index belongs to another photo")
                arr = np.asarray(vector, dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(arr))
                if not arr.size or not np.isfinite(arr).all() or not np.isfinite(norm) or norm <= 1e-12:
                    raise ValueError("Embedding must be finite and nonzero")
                encoded_vectors.append((key, pid, space, (arr / norm).tobytes()))
            # A single transaction publishes evidence and its mandatory indexes.
            # No inference or nested auto-committing Store.write calls belong here.
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO analyses VALUES(?,?)", (analysis.photo_id, analysis.model_dump_json()))
                self.db.execute("DELETE FROM evidence_fts WHERE photo_id=?", (analysis.photo_id,))
                self.db.execute("INSERT INTO evidence_fts VALUES(?,?)", (analysis.photo_id, analysis.description + " " + analysis.ocr))
                self.db.executemany("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)", encoded_vectors)
                self.db.execute("UPDATE state SET value=value+1 WHERE key='revision'")
                self.db.execute("DELETE FROM cache")
                if run_id is not None:
                    updated = self.db.execute(
                        "UPDATE runs SET status='completed',result=?,error=NULL WHERE id=? AND status='running'",
                        (analysis.model_dump_json(), run_id),
                    )
                    if updated.rowcount != 1:
                        raise ValueError("Analysis run is no longer active")

    def vector(self, key, photo_id, space, vector):
        self.photo(photo_id)
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
        arr = arr / max(float(np.linalg.norm(arr)), 1e-12)
        self.write(
            "INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)",
            (key, photo_id, space, arr.tobytes()),
        )

    def search(self, space, query, allowed, limit=20):
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        scored = []
        for row in self.rows(
            "SELECT key,photo_id,data FROM vectors WHERE space=?", (space,)
        ):
            if row["photo_id"] not in allowed:
                continue
            v = np.frombuffer(row["data"], dtype=np.float32)
            if v.shape != q.shape:
                raise ValueError("Embedding dimension mismatch")
            scored.append(
                {
                    "photo_id": row["photo_id"],
                    "artifact": row["key"],
                    "similarity": float(v @ q),
                }
            )
        return sorted(scored, key=lambda x: x["similarity"], reverse=True)[:limit]

    def cache_get(self, key):
        rows = self.rows(
            "SELECT data FROM cache WHERE key=? AND revision=?", (key, self.revision)
        )
        return json.loads(rows[0]["data"]) if rows else None

    def cache_put(self, key, value):
        self.write(
            "INSERT OR REPLACE INTO cache VALUES(?,?,?)",
            (key, self.revision, encoded(value)),
        )

    def event(self, run_id, kind, data):
        self.write(
            "INSERT INTO events(run_id,kind,data,at) VALUES(?,?,?,?)",
            (run_id, kind, encoded(data), time.time()),
        )

    def spaces(self):
        return [
            json.loads(r["data"])
            for r in self.rows("SELECT data FROM spaces ORDER BY id")
        ]

    def close(self):
        self.db.close()
