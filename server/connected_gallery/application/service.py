from __future__ import annotations
import asyncio
import hashlib
import json
import time
import os
import sqlite3
from connected_gallery.domain.models import RunRequest, new_id
from connected_gallery.adapters.store import encoded
from connected_gallery.agent_specs.budgets import run_timeout


class RunService:
    def __init__(self, store, runner):
        self.store = store
        self.runner = runner
        self.tasks = {}
        concurrency = int(os.getenv("CG_ANALYSIS_CONCURRENCY", "3"))
        if not 1 <= concurrency <= 8:
            raise ValueError("CG_ANALYSIS_CONCURRENCY must be between 1 and 8")
        self.analysis_concurrency = concurrency
        self.explore_timeout = run_timeout("explorer")
        self.background = asyncio.Semaphore(concurrency)
        self.interactive = asyncio.Semaphore(1)
        self.exploring = 0
        self.auto_enabled = True

    def schedule(self, rid, request):
        task = asyncio.create_task(self._execute(rid, request))
        self.tasks[rid] = task
        def finished(completed):
            if self.tasks.get(rid) is completed:
                self.tasks.pop(rid, None)
        task.add_done_callback(finished)

    def get(self, run_id):
        rows = self.store.rows("SELECT * FROM runs WHERE id=?", (run_id,))
        if not rows:
            raise ValueError("Unknown run")
        row = rows[0]
        return {
            "id": row["id"],
            "status": row["status"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "error": row["error"],
        }

    def cache_key(self, request):
        if request.role == "explorer":
            value = request.explore.model_dump()
            value.pop("request_revision", None)
        else:
            value = {"role": request.role, "ids": request.photo_ids}
        return hashlib.sha256(
            encoded(
                ["agent-spec-v7", "retrieval-policy-v5-anchor-reminder", os.getenv("CG_MODEL", "gpt-5.4-mini"), value]
            ).encode()
        ).hexdigest()

    def start(self, request):
        existing = self.store.rows(
            "SELECT id,request FROM runs WHERE key=?", (request.idempotency_key,)
        )
        if existing:
            if json.loads(existing[0]["request"]) != request.model_dump(mode="json"):
                raise ValueError("Idempotency key reused with different request")
            previous = self.get(existing[0]["id"])
            if previous["status"] not in ("failed", "cancelled", "incomplete"):
                return previous
            self.store.write(
                "UPDATE runs SET key=? WHERE id=?", (new_id(), previous["id"])
            )
        for pid in request.photo_ids:
            self.store.photo(pid)
        if request.role == "analyst":
            active = self.store.rows(
                "SELECT id FROM runs WHERE status IN ('queued','running') "
                "AND json_extract(request,'$.role')='analyst' "
                "AND json_extract(request,'$.photo_ids[0]')=? ORDER BY started LIMIT 1",
                (request.photo_ids[0],),
            )
            if active:
                return self.get(active[0]["id"])
        if request.explore:
            self.store.photo(request.explore.anchor.photo_id)
            if request.explore.anchor.region_id:
                a = self.store.analysis(request.explore.anchor.photo_id)
                if not a or request.explore.anchor.region_id not in {
                    r["id"] for r in a["regions"]
                }:
                    raise ValueError("Unknown anchor region")
        rid = new_id()
        cached = (
            self.store.cache_get(self.cache_key(request))
            if request.role == "explorer"
            else None
        )
        status = "completed" if cached else "queued"
        self.store.write(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
            (
                rid,
                request.idempotency_key,
                request.model_dump_json(),
                status,
                encoded(cached) if cached else None,
                None,
                time.time(),
            ),
        )
        if cached:
            self.store.event(rid, "results", cached)
        else:
            self.schedule(rid, request)
        return self.get(rid)

    async def _execute(self, rid, request):
        interactive = request.role == "explorer"
        sem = self.interactive if interactive else self.background
        try:
            if request.role == "organizer":
                while self.store.rows(
                    "SELECT id FROM runs WHERE status IN ('queued','running') AND id != ? AND json_extract(request,'$.role')='analyst'",
                    (rid,),
                ):
                    await asyncio.sleep(1)
            async with sem:
                while not interactive and self.exploring:
                    await asyncio.sleep(0.1)
                if interactive:
                    self.exploring += 1
                try:
                    self.store.write(
                        "UPDATE runs SET status='running' WHERE id=?", (rid,)
                    )
                    revision = self.store.revision
                    timeout = (
                        self.explore_timeout
                        if interactive
                        else run_timeout(request.role)
                    )
                    result = await asyncio.wait_for(
                        self.runner.execute(rid, request), timeout
                    )
                    if self.get(rid)["status"] == "cancelled":
                        return
                    complete = result.get("complete", True)
                    self.store.write(
                        "UPDATE runs SET status=?,result=? WHERE id=?",
                        (
                            "completed" if complete else "incomplete",
                            encoded(result),
                            rid,
                        ),
                    )
                    if interactive and complete and revision == self.store.revision:
                        self.store.cache_put(self.cache_key(request), result)
                    self.store.event(
                        rid,
                        "finished",
                        {"status": "completed" if complete else "incomplete"},
                    )
                finally:
                    if interactive:
                        self.exploring -= 1
        except asyncio.CancelledError:
            self.store.write("UPDATE runs SET status='cancelled' WHERE id=? AND status IN ('queued','running')", (rid,))
        except Exception as e:
            # Never log model inputs or raw SQL. SQLite's code and source frames
            # identify infrastructure failures without copying private evidence.
            import traceback
            detail = {"error": type(e).__name__,
                      "frames": [{"file": os.path.basename(f.filename), "function": f.name, "line": f.lineno}
                                 for f in traceback.extract_tb(e.__traceback__)[-8:]]}
            if isinstance(e, sqlite3.Error):
                detail.update(sqlite_errorcode=getattr(e, "sqlite_errorcode", None),
                              sqlite_errorname=getattr(e, "sqlite_errorname", None))
            self.store.event(rid, "execution_error", detail)
            if self.get(rid)["status"] == "completed":
                # Analyst evidence, indexes and result already committed together.
                # A subsequent checkpoint failure cannot undo that valid result.
                return
            partial = self.store.rows(
                "SELECT data FROM events WHERE run_id=? AND kind='results' ORDER BY seq DESC LIMIT 1",
                (rid,),
            )
            self.store.write(
                "UPDATE runs SET status=?,result=?,error=? WHERE id=?",
                (
                    "incomplete" if partial else "failed",
                    partial[0]["data"] if partial else None,
                    type(e).__name__ + ": " + str(e)[:160]
                    if isinstance(e, RuntimeError)
                    else type(e).__name__,
                    rid,
                ),
            )
        finally:
            self.tasks.pop(rid, None)
            if request.role == "analyst" and self.auto_enabled:
                states = self.store.rows("SELECT status FROM runs WHERE id=?", (rid,))
                active = self.store.rows(
                    "SELECT id FROM runs WHERE status IN ('queued','running') AND json_extract(request,'$.role') IN ('analyst','organizer')"
                )
                if states and states[0]["status"] == "completed" and not active:
                    self.start(
                        RunRequest(
                            role="organizer",
                            idempotency_key=f"auto-organize-{self.store.revision}",
                        )
                    )

    def cancel(self, rid):
        run = self.get(rid)
        if run["status"] in ("queued", "running"):
            self.store.write("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
            task = self.tasks.get(rid)
            if task is not None:
                task.cancel()
        return self.get(rid)

    async def recover(self):
        claimed = set()
        for row in self.store.rows(
            "SELECT id,request FROM runs WHERE status IN ('queued','running') "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, started"
        ):
            req = RunRequest.model_validate_json(row["request"])
            if req.role == "analyst":
                pid = req.photo_ids[0]
                if pid in claimed:
                    self.store.write("UPDATE runs SET status='cancelled',error=? WHERE id=?",
                                     ("Superseded by active analysis for the same photo", row["id"]))
                    continue
                claimed.add(pid)
            self.schedule(row["id"], req)

    def cancel_analysis_for_photo(self, photo_id):
        for row in self.store.rows(
            "SELECT id FROM runs WHERE status IN ('queued','running') "
            "AND json_extract(request,'$.role')='analyst' "
            "AND json_extract(request,'$.photo_ids[0]')=?", (photo_id,),
        ):
            self.cancel(row["id"])

    async def stop(self, preserve_pending=False):
        self.auto_enabled = False
        pending = self.store.rows("SELECT id FROM runs WHERE status IN ('queued','running')") if preserve_pending else []
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A task cancelled before its coroutine starts never enters its finally.
        self.tasks = {rid: task for rid, task in self.tasks.items() if not task.done()}
        for row in pending:
            self.store.write("UPDATE runs SET status='queued' WHERE id=? AND status='cancelled'", (row["id"],))
        self.auto_enabled = True
