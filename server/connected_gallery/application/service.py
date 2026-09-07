from __future__ import annotations
import asyncio
import hashlib
import json
import time
import os
import sqlite3
from connected_gallery.domain.models import RunRequest, ExploreInput, ExplorationResult, SemanticAnchor, new_id
from connected_gallery.adapters.store import encoded
from connected_gallery.agent_specs.budgets import run_timeout
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
from connected_gallery.application.context import ContextService


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
        self.contexts = ContextService(self)

    def schedule(self, rid, request):
        # Retire durable legacy work without resuming model calls or deleting evidence.
        if request.role == "organizer":
            self.store.write(
                "UPDATE runs SET status='cancelled',error=? WHERE id=? "
                "AND status IN ('queued','running')",
                ("Spaces are no longer part of the MVP", rid),
            )
            return
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
        if request.role == "context":
            return self.contexts.key(request.photo_ids[0])
        if request.role == "explorer":
            explore = self._canonical_explore(request.explore)
            value = explore.model_dump()
            value.pop("request_revision", None)
            value["photo_version"] = self.store.photo(explore.anchor.photo_id).version
        else:
            value = {"role": request.role, "ids": request.photo_ids}
        return hashlib.sha256(
            encoded(
                [f"agent-spec-v{AGENT_SPEC_VERSION}", RETRIEVAL_POLICY, os.getenv("CG_MODEL", "gpt-5.4-mini"), value]
            ).encode()
        ).hexdigest()

    def context_ready(self, photo_id):
        return self.contexts.ready(photo_id)

    def prepare_context(self, photo_id):
        return self.contexts.prepare(photo_id)

    def _canonical_explore(self, explore):
        explore = ExploreInput.model_validate(explore)
        anchor = explore.anchor
        self.store.photo(anchor.photo_id)
        if anchor.region_id:
            analysis = self.store.analysis(anchor.photo_id)
            region = next((r for r in (analysis or {}).get("regions", [])
                           if r["id"] == anchor.region_id), None)
            if region is None:
                raise ValueError("Unknown anchor region")
            if anchor.box is not None and any(
                abs(value - region["box"][key]) > 0.00001
                for key, value in anchor.box.model_dump().items()
            ):
                raise ValueError("Anchor box does not match its current region")
            if anchor.kind != region["kind"]:
                raise ValueError("Anchor kind does not match its current region")
            anchor = SemanticAnchor(photo_id=anchor.photo_id, region_id=anchor.region_id,
                                    box=region["box"], label=region["label"], kind=region["kind"])
        return explore.model_copy(update={"anchor": anchor})

    def ready(self, explore):
        """Read-only prepared lookup: never creates a run, image, event or model call."""
        with self.store.lock:
            explore = self._canonical_explore(explore)
            revision = self.store.revision
            cached = self.store.cache_get(self.cache_key(RunRequest(role="explorer", explore=explore)))
            pending = {"state": "pending", "revision": revision}
            if not cached:
                return pending
            try:
                result = ExplorationResult.model_validate(cached)
            except ValueError:
                return pending
            if result.grouping_status != "ready" or not result.complete:
                return pending
            allowed = {p.id for p in self.store.photos(explore.year)} - {explore.anchor.photo_id}
            if any(item.photo_id not in allowed for item in result.items):
                return pending
            return {"state": "ready", "revision": revision, "result": result.model_dump(mode="json")}

    def start(self, request):
        if request.role == "organizer":
            raise ValueError("Spaces are no longer part of the MVP")
        if request.role == "context":
            return self.contexts.start(request.photo_ids[0])
        if request.explore:
            request = request.model_copy(update={"explore": self._canonical_explore(request.explore)})
        existing = self.store.rows(
            "SELECT id,request FROM runs WHERE key=?", (request.idempotency_key,)
        )
        if existing:
            if json.loads(existing[0]["request"]) != request.model_dump(mode="json"):
                raise ValueError("Idempotency key reused with different request")
            previous = self.get(existing[0]["id"])
            reusable = previous["status"] not in ("failed", "cancelled", "incomplete")
            if reusable:
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
        rid = new_id()
        cached = (
            self.ready(request.explore).get("result")
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
                    complete = result.get("complete", True) and result.get("grouping_status") != "failed"
                    with self.store.lock:
                        if (interactive or request.role == "context") and revision != self.store.revision:
                            raise ValueError("Gallery changed during exploration; prepare again")
                        if interactive and result.get("grouping_status") == "ready":
                            ExplorationResult.model_validate(result)
                        if request.role == "context":
                            self.contexts.validate(request.photo_ids[0], result)
                            context_cached = self.contexts.cache_value(request.photo_ids[0], result) if complete else None
                        self.store.write(
                            "UPDATE runs SET status=?,result=? WHERE id=?",
                            (
                                "completed" if complete else "incomplete",
                                encoded(result),
                                rid,
                            ),
                        )
                        if interactive and complete and result.get("grouping_status") == "ready":
                            self.store.cache_put(self.cache_key(request), result)
                        if request.role == "context" and complete:
                            self.store.cache_put(self.cache_key(request),
                                context_cached)
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
        context_claimed = set()
        for row in self.store.rows(
            "SELECT id,request FROM runs WHERE status IN ('queued','running') "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, started"
        ):
            req = RunRequest.model_validate_json(row["request"])
            if req.role == "context":
                pid = req.photo_ids[0]
                try:
                    current = req.idempotency_key.startswith(f"context:{self.contexts.key(pid)}:")
                except ValueError:
                    current = False
                if not current or pid in context_claimed:
                    self.store.write("UPDATE runs SET status='cancelled',error=? WHERE id=?",
                                     ("Context snapshot changed or superseded", row["id"]))
                    continue
                context_claimed.add(pid)
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
        pending = self.store.rows("SELECT id FROM runs WHERE status IN ('queued','running')") if preserve_pending else []
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A task cancelled before its coroutine starts never enters its finally.
        self.tasks = {rid: task for rid, task in self.tasks.items() if not task.done()}
        for row in pending:
            self.store.write("UPDATE runs SET status='queued' WHERE id=? AND status='cancelled'", (row["id"],))
