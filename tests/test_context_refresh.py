"""Explicit context refresh, old-result preservation, and opaque-ID display guards."""
import asyncio
import hashlib
import json
import os

import pytest

from connected_gallery.application.service import RunService
from connected_gallery.domain.context import CONTEXT_WORDING_MODEL, context_wording_fields
from connected_gallery.domain.models import RunRequest
from test_context_model_profile import synthetic
from test_contracts import asset, store
from test_demo_profile_scripts import script
from test_photo_context import context


OPAQUE = "0123456789abcdef0123456789abcdef"


def proved(store, value, source="a"):
    ids = [p.id for p in store.photos()]
    return {**value, "evidence": {
        "gallery_revision": store.revision, "source_version": store.photo(source).version,
        "inspected_photo_ids": ids, "photo_versions": {p.id: p.version for p in store.photos()},
        "reviewed_members": [{"group_id": g["id"], "photo_id": pid} for g in value["groups"] for pid in g["photo_ids"]],
        "summary_reviewed": True, "planned_photo_ids": [pid for pid in ids if pid != source],
        "wording_review_model": CONTEXT_WORDING_MODEL, "wording_reviewed": True,
        "wording_checked_paths": [f["path"] for f in context_wording_fields(value)]}}


def seed(service, *, empty=False):
    key = service.contexts.key("a")
    value = {**context(() if empty else ("b",)), "summary": "기존 사진의 맥락입니다."}
    payload = json.dumps(service.contexts.cache_value("a", proved(service.store, value)), ensure_ascii=False, indent=3)
    service.store.write("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, service.store.revision, payload))
    return key, payload


class FixtureRunner:
    def __init__(self, store, *, fail=False, complete=True, invalid=False, block=False):
        self.store, self.fail, self.complete, self.invalid = store, fail, complete, invalid
        self.calls = 0
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def execute(self, rid, request):
        self.calls += 1
        await self.release.wait()
        if self.fail:
            raise RuntimeError("Controlled fixture failure")
        value = {**context(("b",), complete=self.complete), "summary": "새로 검토한 사진 맥락입니다."}
        result = proved(self.store, value, request.photo_ids[0])
        if self.invalid:
            result["evidence"]["wording_reviewed"] = False
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_refresh_preserves_visible_cache_deduplicates_active_and_replaces_after_validation(store, empty):
    runner = FixtureRunner(store, block=True)
    service = RunService(store, runner)
    key, before = seed(service, empty=empty)
    assert service.contexts.start("a")["status"] == "completed" and runner.calls == 0
    run = service.contexts.start("a", refresh_prepared=True)
    assert run["status"] == "queued"
    assert service.context_ready("a")["state"] == ("empty" if empty else "ready")
    assert service.contexts.start("a", refresh_prepared=True)["id"] == run["id"]
    assert service.contexts.start("a")["id"] == run["id"]
    assert service.prepare_context("a")["run_id"] is None  # Public prepare retains its prior behavior.
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == before
    event = json.loads(store.rows("SELECT data FROM events WHERE run_id=? AND kind='context_refresh_requested'", (run["id"],))[0]["data"])
    assert event["cache_key"] == key and event["previous_cache_sha256"] == hashlib.sha256(before.encode()).hexdigest()
    assert event["previous_cache_revision"] == store.revision and "기존 사진" not in json.dumps(event)
    task = service.tasks[run["id"]]
    runner.release.set()
    await task
    assert runner.calls == 1 and service.get(run["id"])["status"] == "completed"
    assert service.context_ready("a")["context"]["summary"] == "새로 검토한 사진 맥락입니다."
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] != before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "incomplete", "invalid_evidence", "cancel"])
async def test_failed_refresh_never_overwrites_original_result(store, failure):
    runner = FixtureRunner(store, fail=failure == "exception", complete=failure != "incomplete",
                           invalid=failure == "invalid_evidence", block=failure == "cancel")
    service = RunService(store, runner)
    key, before = seed(service)
    run = service.contexts.start("a", refresh_prepared=True)
    task = service.tasks[run["id"]]
    if failure == "cancel":
        await asyncio.sleep(0)
        service.cancel(run["id"])
    await asyncio.gather(task, return_exceptions=True)
    assert service.get(run["id"])["status"] in ("failed", "incomplete", "cancelled")
    assert service.context_ready("a")["state"] == "ready"
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == before


@pytest.mark.asyncio
async def test_refresh_joins_only_current_model_namespace(store, monkeypatch):
    monkeypatch.setenv("CG_CONTEXT_MODEL", "old-context")
    service = RunService(store, FixtureRunner(store))
    old_key = service.contexts.key("a")
    request = RunRequest(role="context", photo_ids=["a"], idempotency_key=f"context:{old_key}:old-active")
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("old-active", request.idempotency_key,
                request.model_dump_json(), "running", None, None, 1))
    monkeypatch.setenv("CG_CONTEXT_MODEL", "new-context")
    run = service.contexts.start("a", refresh_prepared=True)
    assert run["id"] != "old-active"
    await service.tasks[run["id"]]
    assert service.context_ready("a")["state"] == "ready"


@pytest.mark.parametrize("field", ["summary", "title", "reason"])
@pytest.mark.parametrize("identifier", [OPAQUE, "12345678-abcd-1234-abcd-1234567890ef", "cloud-photo-00012345"])
def test_known_opaque_identifier_in_any_display_field_is_rejected(store, field, identifier):
    store.upsert(asset(identifier))
    service = RunService(store, None)
    value = context(("b",))
    if field == "summary":
        value[field] = f"사진 {identifier}와 비교해 보세요."
    else:
        value["groups"][0][field] = f"사진 [{identifier}]"
    with pytest.raises(ValueError, match="internal photo identifier"):
        service.contexts.validate("a", value)


def test_short_numeric_and_ordinary_word_ids_do_not_reject_natural_prose(store):
    for identifier in ("1", "2026", "source", "other", "documentation"):
        store.upsert(asset(identifier))
    service = RunService(store, None)
    value = context(("b",))
    value["summary"] = "A source and other documentation show 1 scene in 2026. A cabinet is visible."
    assert service.contexts.validate("a", value).summary == value["summary"]
    store.upsert(asset(OPAQUE))
    value["summary"] = f"Unrelated complete token x{OPAQUE}x and unknown {'f' * 32}."
    assert service.contexts.validate("a", value).summary == value["summary"]


def test_leaked_cached_identifier_is_invalid_without_rewriting_it(store):
    store.upsert(asset(OPAQUE))
    service = RunService(store, None)
    key, before = seed(service)
    cached = json.loads(before)
    cached["context"]["groups"][0]["reason"] = f"참조 [{OPAQUE}]"
    raw = json.dumps(cached)
    store.write("UPDATE cache SET data=? WHERE key=?", (raw, key))
    changes = store.db.total_changes
    assert service.context_ready("a")["state"] == "pending"
    assert store.db.total_changes == changes
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw


@pytest.mark.asyncio
async def test_context_refresh_cli_requires_explicit_photo_before_any_setup(tmp_path, monkeypatch):
    monkeypatch.setattr("connected_gallery.adapters.store.Store", lambda *a: pytest.fail("No setup allowed"))
    preparation = script("prepare-contexts.py")
    args = preparation.parser().parse_args(["--data-dir", str(tmp_path), "--refresh"])
    with pytest.raises(ValueError, match="explicit --photo-id"):
        await preparation.main(args)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,exit_code", [("success", 0), ("failure", 2), ("incomplete", 2), ("retry_then_success", 0)])
async def test_cli_distinguishes_new_refresh_result_from_old_readiness(synthetic, monkeypatch, mode, exit_code):
    root, _ = synthetic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-fixture")
    for name in ("CG_AUTO_ORGANIZE", "CG_ANALYSIS_CONCURRENCY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, os.getenv(name, ""))
    monkeypatch.setattr("connected_gallery.adapters.models.LocalModels", lambda *a: None)
    called = []

    class NoModelRunner:
        def __init__(self, store, *args, **kwargs):
            self.store = store

        async def execute(self, rid, request):
            called.append(request.photo_ids)
            if mode == "failure" or mode == "retry_then_success" and len(called) == 1:
                raise RuntimeError("Controlled fixture failure")
            value = {**context(("b",), complete=mode != "incomplete"), "summary": "새로 검토한 사진 맥락입니다."}
            return proved(self.store, value)

    monkeypatch.setattr("connected_gallery.agent_runtime.runner.GraphAgentRunner", NoModelRunner)
    preparation = script("prepare-contexts.py")
    args = preparation.parser().parse_args(["--data-dir", str(root), "--photo-id", "a", "--refresh",
        "--passes", "3" if mode == "retry_then_success" else "1"])
    assert await preparation.main(args) == exit_code
    report = json.loads((root / "context-preparation-report.json").read_text())
    assert called == [["a"]] * (2 if mode == "retry_then_success" else 1)
    assert report["counts"]["ready"] == 2  # Old readable cache alone is not refresh success.
    latest = report["attempts"][-1]
    assert latest["new_result_prepared"] is (exit_code == 0)
    assert latest["previous_result_still_available"] is (exit_code != 0)
    assert report["current_invocation"]["selected_refresh_completed"] is (exit_code == 0)
