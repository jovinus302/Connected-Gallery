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
from connected_gallery.application.attempt_feedback import exploration_cache_key, record_execution_identity
from connected_gallery.application.demo_profile import connection_models
from connected_gallery.domain.empty_evidence import EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY, validate_empty_evidence


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
        self.auto_organize = os.getenv("CG_AUTO_ORGANIZE", "0") == "1"
        self.contexts = ContextService(self)

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

    def cache_key(self, request, *, model=None):
        if request.role == "context":
            return self.contexts.key(request.photo_ids[0])
        if request.role == "explorer":
            explore = self._canonical_explore(request.explore)
            return exploration_cache_key(self.store, explore, model=model)
        else:
            value = {"role": request.role, "ids": request.photo_ids}
        return hashlib.sha256(
            encoded(
                [f"agent-spec-v{AGENT_SPEC_VERSION}", RETRIEVAL_POLICY,
                 model if model is not None else os.getenv("CG_MODEL", "gpt-5.4-mini"), value]
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
            _, result, model = self._prepared_entry(explore)
            if result is None:
                return {"state": "pending", "revision": revision}
            return {"state": "ready", "revision": revision, "cache_model": model,
                    "result": result.model_dump(mode="json")}

    def empty_cache_key(self, explore, *, model=None):
        base = self.cache_key(RunRequest(role="explorer", explore=explore), model=model)
        return hashlib.sha256(encoded(["empty-evidence", EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY,
                                       base, self.store.revision]).encode()).hexdigest()

    def prepared_cache_key(self, explore):
        """Actual current ready row for read-only audits/staging, including a negative proof row."""
        with self.store.lock:
            return self._prepared_entry(self._canonical_explore(explore))[0]

    def _prepared_entry(self, explore):
        # Capture the explicit ordered profile once. Namespace selection never
        # changes process environment, copies rows or changes execution models.
        for model in connection_models():
            key, result = self._prepared_entry_for_model(explore, model)
            if result is not None:
                return key, result, model
        return None, None, None

    def _prepared_entry_for_model(self, explore, model):
        base = self.cache_key(RunRequest(role="explorer", explore=explore), model=model)
        for key in (base, self.empty_cache_key(explore, model=model)):
            cached = None
            try:
                cached = self.store.cache_get(key)
                if not cached:
                    continue
                result = ExplorationResult.model_validate(cached)
                if result.grouping_status != "ready" or not result.complete:
                    if key == base and result.items:
                        return None, None
                    continue
                allowed = {p.id for p in self.store.photos(explore.year)} - {explore.anchor.photo_id}
                if any(item.photo_id not in allowed for item in result.items):
                    return None, None
                if not result.items:
                    validate_empty_evidence(self.store, explore, result.empty_evidence, model=model)
                elif key != base:
                    continue
            except (ValueError, TypeError, KeyError):
                # A malformed current positive must not be hidden by an older
                # negative proof. Only recognizable legacy empty rows permit
                # the separate proof lookup; their stored values stay intact.
                if key == base and (not isinstance(cached, dict) or cached.get("items") != []):
                    return None, None
                continue
            return key, result
        return None, None

    def start(self, request, *, refresh_prepared=False):
        # Internal offline preparation only; the public request schema has no
        # refresh field. Fresh retrieval still writes the current primary key.
        if refresh_prepared and request.role != "explorer":
            raise ValueError("Prepared refresh is only supported for exploration")
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
            if refresh_prepared and previous["status"] == "completed":
                reusable = False
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
        prepared_key, prepared_result, prepared_model = None, None, None
        if request.role == "explorer" and not refresh_prepared:
            with self.store.lock:
                prepared_key, prepared_result, prepared_model = self._prepared_entry(request.explore)
        cached = prepared_result.model_dump(mode="json") if prepared_result is not None else None
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
            self.store.event(rid, "prepared_cache_hit", {"cache_key": prepared_key, "cache_model": prepared_model})
            self.store.event(rid, "results", cached)
        else:
            self.schedule(rid, request)
        return self.get(rid)

    def start_prepared_revision(self, explore, *, feedback="", feedback_source=None,
                                expected_cache_sha256=None, expected_revision=None):
        """Offline-only entry: deliberately bypasses start()'s prepared cache hit."""
        from connected_gallery.application.prepared_revision import start_prepared_revision
        return start_prepared_revision(self, explore, feedback=feedback, feedback_source=feedback_source,
                                       expected_cache_sha256=expected_cache_sha256, expected_revision=expected_revision)

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
                    with self.store.lock:
                        revision = self.store.revision
                        if interactive:
                            request = request.model_copy(update={"explore": self._canonical_explore(request.explore)})
                            record_execution_identity(self.store, rid, request)
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
                            if not result["items"]:
                                validate_empty_evidence(self.store, request.explore, result.get("empty_evidence"))
                        if request.role == "context":
                            self.contexts.validate(request.photo_ids[0], result)
                            context_cached = self.contexts.cache_value(request.photo_ids[0], result) if complete else None
                        from connected_gallery.application.prepared_revision import SOURCE_EVENT, finish_prepared_revision
                        revising_prepared = interactive and bool(self.store.rows(
                            "SELECT 1 FROM events WHERE run_id=? AND kind=?", (rid, SOURCE_EVENT)))
                        if revising_prepared:
                            finish_prepared_revision(self, rid, request, result, complete)
                        else:
                            self.store.write(
                                "UPDATE runs SET status=?,result=? WHERE id=?",
                                (
                                    "completed" if complete else "incomplete",
                                    encoded(result),
                                    rid,
                                ),
                            )
                            if interactive and complete and result.get("grouping_status") == "ready":
                                key = self.cache_key(request) if result["items"] else self.empty_cache_key(request.explore)
                                self.store.cache_put(key, result)
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
            if request.role == "analyst" and self.auto_enabled and self.auto_organize:
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
        context_claimed = set()
        for row in self.store.rows(
            "SELECT id,request FROM runs WHERE status IN ('queued','running') "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, started"
        ):
            from connected_gallery.application.prepared_revision import SOURCE_EVENT
            if self.store.rows("SELECT 1 FROM events WHERE run_id=? AND kind=?", (row["id"], SOURCE_EVENT)):
                # An offline revision must never resume as ordinary retrieval.
                # Its source cache is left intact; the CLI can start a fresh,
                # explicitly selected revision after rechecking its hash.
                self.store.write("UPDATE runs SET status='incomplete',error=? WHERE id=?", (
                    "Interrupted offline prepared revision; rerun explicitly", row["id"]))
                continue
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
