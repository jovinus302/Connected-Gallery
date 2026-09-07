"""Explicit old-model reuse preserves provenance; fresh work writes only primary."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os

import pytest

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
from connected_gallery.application.attempt_feedback import exploration_cache_key
from connected_gallery.application.prepared_revision import validate_current_source
from connected_gallery.application.service import RunService
from connected_gallery.domain.empty_evidence import EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY, validate_empty_evidence
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from empty_proof_fixture import negative_proof
from test_contracts import store
from test_result_groups import prepared


PRIMARY = "gpt-5.4"
OLD = "claude-sonnet-5"


@pytest.fixture(autouse=True)
def profile(monkeypatch):
    monkeypatch.setenv("CG_MODEL", PRIMARY)
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", json.dumps([OLD]))


def request(pid="a", **kwargs):
    return RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id=pid)), **kwargs)


def negative(store, query, model):
    proof = negative_proof(store, query)
    proof["cache_model"] = model
    return {**prepared(()), "empty_evidence": proof}


def snapshot(store):
    return {table: store.rows("SELECT * FROM " + table) for table in ("cache", "runs", "events")}


def test_old_positive_and_proof_keys_are_byte_identical_to_original_scheme(store):
    service, req = RunService(store, None), request()
    value = req.explore.model_dump(mode="json", exclude={"request_revision"})
    value["photo_version"] = store.photo("a").version
    base = hashlib.sha256(encoded([f"agent-spec-v{AGENT_SPEC_VERSION}", RETRIEVAL_POLICY, OLD, value]).encode()).hexdigest()
    proof = hashlib.sha256(encoded(["empty-evidence", EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY, base, store.revision]).encode()).hexdigest()
    assert service.cache_key(req, model=OLD) == exploration_cache_key(store, req.explore, model=OLD) == base
    assert service.empty_cache_key(req.explore, model=OLD) == proof
    assert service.cache_key(req) != base


def test_compatible_lookup_is_read_only_and_primary_is_preferred(store):
    service, req = RunService(store, None), request()
    old_key, primary_key = service.cache_key(req, model=OLD), service.cache_key(req)
    old = {**prepared(("b",)), "label": "Original Claude wording"}
    raw = json.dumps(old, ensure_ascii=False, indent=3)
    store.write("INSERT INTO cache VALUES(?,?,?)", (old_key, store.revision, raw))
    before = snapshot(store)
    assert service.ready(req.explore)["cache_model"] == OLD
    assert service.ready(req.explore)["result"] == old
    assert service.prepared_cache_key(req.explore) == old_key
    assert snapshot(store) == before
    primary = {**prepared(("c",)), "label": "New GPT wording"}
    store.cache_put(primary_key, primary)
    assert service.ready(req.explore)["cache_model"] == PRIMARY
    assert service.ready(req.explore)["result"] == primary
    assert service.prepared_cache_key(req.explore) == primary_key
    assert store.rows("SELECT data FROM cache WHERE key=?", (old_key,))[0]["data"] == raw


@pytest.mark.parametrize("damage", ["wrong_model", "version", "revision", "legacy_empty"])
def test_compatible_negative_requires_its_exact_original_model_and_evidence(store, damage):
    service, req = RunService(store, None), request()
    old = negative(store, req.explore, OLD)
    if damage == "wrong_model": old["empty_evidence"]["cache_model"] = PRIMARY
    if damage == "version": old["empty_evidence"]["photo_versions"]["b"] = "changed"
    if damage == "revision": old["empty_evidence"]["gallery_revision"] -= 1
    if damage == "legacy_empty": del old["empty_evidence"]
    key = service.empty_cache_key(req.explore, model=OLD)
    store.cache_put(key, old)
    before = snapshot(store)
    assert service.ready(req.explore)["state"] == "pending"
    assert service.prepared_cache_key(req.explore) is None
    assert snapshot(store) == before


def test_valid_negative_reuses_old_proof_namespace_but_primary_proof_takes_priority(store):
    service, req = RunService(store, None), request()
    old = negative(store, req.explore, OLD)
    old_key = service.empty_cache_key(req.explore, model=OLD)
    store.cache_put(old_key, old)
    assert service.ready(req.explore)["cache_model"] == OLD
    assert service.ready(req.explore)["result"] == old
    assert service.prepared_cache_key(req.explore) == old_key
    with pytest.raises(ValueError):
        validate_empty_evidence(store, req.explore, old["empty_evidence"])
    assert validate_empty_evidence(store, req.explore, old["empty_evidence"], model=OLD).cache_model == OLD
    primary = negative(store, req.explore, PRIMARY)
    primary_key = service.empty_cache_key(req.explore)
    store.cache_put(primary_key, primary)
    assert service.ready(req.explore)["cache_model"] == PRIMARY
    assert service.prepared_cache_key(req.explore) == primary_key


def test_corrupt_primary_cannot_use_its_own_old_negative_but_can_use_explicit_compatible(store):
    service, req = RunService(store, None), request()
    store.write("INSERT INTO cache VALUES(?,?,?)", (service.cache_key(req), store.revision, "broken positive"))
    store.cache_put(service.empty_cache_key(req.explore), negative(store, req.explore, PRIMARY))
    assert service.ready(req.explore)["state"] == "pending"
    old_key = service.cache_key(req, model=OLD)
    store.cache_put(old_key, prepared())
    assert service.ready(req.explore)["cache_model"] == OLD
    assert service.prepared_cache_key(req.explore) == old_key


@pytest.mark.parametrize("damage", ["unlisted", "stale", "source_version", "foreign", "incomplete"])
def test_unlisted_or_invalid_positive_is_not_selected(store, monkeypatch, damage):
    service, req = RunService(store, None), request()
    old = prepared(("not-in-gallery",)) if damage == "foreign" else prepared()
    if damage == "incomplete": old["complete"] = False
    store.cache_put(service.cache_key(req, model=OLD), old)
    if damage == "unlisted": monkeypatch.delenv("CG_COMPATIBLE_CONNECTION_MODELS")
    if damage == "stale": store.bump()
    if damage == "source_version":
        changed = store.photo("a").model_dump(mode="json")
        changed["version"] = "other"
        store.write("UPDATE photos SET data=? WHERE id='a'", (encoded(changed),))
    assert service.ready(req.explore)["state"] == "pending"


def test_concurrent_positive_and_negative_lookups_never_write_process_environment(store, monkeypatch):
    service = RunService(store, None)
    positive_req, negative_req = request("a"), request("b")
    store.cache_put(service.cache_key(positive_req, model=OLD), prepared(("c",)))
    old_negative = negative(store, negative_req.explore, OLD)
    store.cache_put(service.empty_cache_key(negative_req.explore, model=OLD), old_negative)
    before, environment = snapshot(store), dict(os.environ)
    def no_environment_write(*args, **kwargs):
        raise AssertionError("A read-only cache lookup changed process environment")
    with monkeypatch.context() as guard:
        guard.setattr(type(os.environ), "__setitem__", no_environment_write)
        guard.setattr(type(os.environ), "__delitem__", no_environment_write)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: service.ready((positive_req if i % 2 else negative_req).explore), range(32)))
    assert all(result["state"] == "ready" and result["cache_model"] == OLD for result in results)
    assert results[0]["result"] == old_negative and results[1]["result"] == prepared(("c",))
    assert snapshot(store) == before and dict(os.environ) == environment


def test_start_compatible_hit_records_origin_without_copying_cache_or_running_model(store):
    service, req = RunService(store, None), request()
    old_key = service.cache_key(req, model=OLD)
    store.cache_put(old_key, prepared())
    before_cache = store.rows("SELECT * FROM cache")
    service.schedule = lambda *args: pytest.fail("A compatible hit scheduled a model")
    run = service.start(req)
    assert run["status"] == "completed" and run["result"] == prepared()
    assert store.rows("SELECT * FROM cache") == before_cache
    hit = json.loads(store.rows("SELECT data FROM events WHERE run_id=? AND kind='prepared_cache_hit'", (run["id"],))[0]["data"])
    assert hit == {"cache_key": old_key, "cache_model": OLD}
    assert service.start(req)["id"] == run["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_empty", [False, True])
async def test_offline_refresh_keeps_old_rows_and_writes_only_current_primary(store, as_empty):
    req = request(idempotency_key="explicit-offline-refresh")
    value = negative(store, req.explore, PRIMARY) if as_empty else {**prepared(("c",)), "label": "Fresh primary"}
    gate = asyncio.Event()
    class Runner:
        calls = 0
        async def execute(self, *args):
            self.calls += 1
            assert os.environ["CG_MODEL"] == PRIMARY
            await gate.wait()
            return value
    runner, service = Runner(), None
    service = RunService(store, runner)
    old_key = service.cache_key(req, model=OLD)
    store.cache_put(old_key, prepared())
    old_row = store.rows("SELECT * FROM cache WHERE key=?", (old_key,))[0]
    cached_run = service.start(req)
    fresh = service.start(req, refresh_prepared=True)
    assert fresh["id"] != cached_run["id"] and fresh["status"] == "queued"
    assert service.start(req, refresh_prepared=True)["id"] == fresh["id"]  # join queued
    await asyncio.sleep(0)
    assert service.start(req, refresh_prepared=True)["id"] == fresh["id"]  # join running
    gate.set()
    await asyncio.gather(*list(service.tasks.values()))
    assert runner.calls == 1 and service.get(fresh["id"])["status"] == "completed"
    assert service.get(cached_run["id"])["result"] == prepared()
    assert store.rows("SELECT * FROM cache WHERE key=?", (old_key,))[0] == old_row
    new_key = service.empty_cache_key(req.explore) if as_empty else service.cache_key(req)
    assert new_key != old_key and store.cache_get(new_key) == value
    assert service.ready(req.explore)["cache_model"] == PRIMARY
    identity = json.loads(store.rows("SELECT data FROM events WHERE run_id=? AND kind='exploration_attempt_identity'", (fresh["id"],))[0]["data"])
    assert identity["logical_model"] == PRIMARY and identity["cache_key"] == service.cache_key(req)


@pytest.mark.asyncio
async def test_failed_refresh_cannot_replace_compatible_success(store):
    class Runner:
        async def execute(self, *args):
            return {**prepared(), "complete": False}
    service, req = RunService(store, Runner()), request()
    old_key = service.cache_key(req, model=OLD)
    store.cache_put(old_key, prepared())
    rows = store.rows("SELECT * FROM cache")
    run = service.start(req, refresh_prepared=True)
    await asyncio.gather(*list(service.tasks.values()))
    assert service.get(run["id"])["status"] == "incomplete"
    assert store.rows("SELECT * FROM cache") == rows
    assert service.ready(req.explore)["cache_model"] == OLD


def test_offline_revision_cannot_overwrite_compatible_model_namespace(store):
    class Runner:
        supports_prepared_revision = True
    service, req = RunService(store, Runner()), request()
    old_key = service.cache_key(req, model=OLD)
    store.cache_put(old_key, prepared())
    service.schedule = lambda *args: pytest.fail("A cross-model revision scheduled work")
    before = snapshot(store)
    with pytest.raises(ValueError, match="primary model"):
        service.start_prepared_revision(req.explore)
    assert snapshot(store) == before
    with pytest.raises(ValueError, match="primary model"):
        validate_current_source(service, req, {"original_cache_key": old_key})
    assert snapshot(store) == before


def test_refresh_is_not_a_public_request_field_or_non_explorer_option(store):
    assert "refresh_prepared" not in RunRequest.model_json_schema()["properties"]
    with pytest.raises(ValueError, match="only supported"):
        RunService(store, None).start(RunRequest(role="analyst", photo_ids=["a"]), refresh_prepared=True)
