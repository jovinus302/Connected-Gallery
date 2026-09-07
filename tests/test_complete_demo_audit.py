"""Acceptance auditor must distinguish incomplete evidence from reviewed empty."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from connected_gallery.adapters.store import Store
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, PhotoAsset, SemanticAnchor, RunRequest
from connected_gallery.domain.context import CONTEXT_WORDING_MODEL, context_wording_fields
from empty_proof_fixture import negative_proof

spec = importlib.util.spec_from_file_location("complete_demo_audit", Path(__file__).resolve().parents[1] / "scripts" / "audit-complete-demo.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "fixture-model")
    monkeypatch.delenv("CG_CONTEXT_MODEL", raising=False)
    monkeypatch.delenv("CG_COMPATIBLE_CONNECTION_MODELS", raising=False)
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "synthetic-demo.json").write_text('{"synthetic":true,"model":"fixture-model"}')
    store = Store(root)
    for pid in "abcd":
        store.upsert(PhotoAsset(id=pid, device_id="synthetic-demo", version="v1", width=40, height=30))
        regions = [{"id": "r" + pid, "photo_id": pid, "box": {"x": .1, "y": .1, "width": .4, "height": .4},
                    "kind": "object", "label": "Visible " + pid, "evidence": "Synthetic unit fixture"}]
        if pid == "d":
            regions.append({**regions[0], "id": "empty"})
        store.write("INSERT INTO analyses VALUES(?,?)", (pid, json.dumps({"photo_id": pid, "description": "Fixture", "regions": regions})))
    service = RunService(store, audit_module.NoExecution())
    connect_keys, context_keys = {}, {}
    for pid, target in zip("abcd", "bcda"):
        for region in store.analysis(pid)["regions"]:
            query = ExploreInput(anchor=SemanticAnchor(photo_id=pid, region_id=region["id"], box=region["box"], kind="object", label=region["label"]))
            key = service.cache_key(RunRequest(role="explorer", explore=query))
            result = {"label": "Observed", "complete": True, "grouping_status": "ready",
                      "items": [{"photo_id": target, "reason": "Stored relation"}],
                      "groups": [{"id": "g", "title": "Relation", "reason": "Stored group", "photo_ids": [target]}]}
            if region["id"] == "empty":
                result.update(items=[], groups=[], empty_evidence=negative_proof(store, query))
                key = service.empty_cache_key(query)
            store.cache_put(key, result)
            connect_keys[region["id"]] = key
        members = [] if pid == "d" else [{"a": "c", "b": "d", "c": "a"}[pid]]
        context = {"summary": "Visible context", "complete": True,
                   "groups": [{"id": "context", "title": "A relation", "reason": "Visible evidence", "photo_ids": members}] if members else [],
                   "evidence": {"gallery_revision": store.revision, "source_version": "v1",
                                "inspected_photo_ids": list("abcd"), "photo_versions": dict.fromkeys("abcd", "v1"),
                                "reviewed_members": [{"group_id": "context", "photo_id": value} for value in members],
                                "summary_reviewed": True}}
        context["evidence"].update(planned_photo_ids=members, wording_review_model=CONTEXT_WORDING_MODEL,
                                   wording_reviewed=True, wording_checked_paths=[field["path"] for field in context_wording_fields(context)])
        key = service.contexts.key(pid)
        store.cache_put(key, service.contexts.cache_value(pid, context))
        context_keys[pid] = key
    store.close()
    args = SimpleNamespace(data_dir=root, report=tmp_path / "acceptance.json", manifest=None, fixture=None,
                           expected_photos=4, expected_regions=5, minimum_route_starts=2,
                           probe_photo_id="a", probe_region_id="ra", require_context_beyond_connect=True)
    return SimpleNamespace(args=args, connect_keys=connect_keys, context_keys=context_keys)


def test_all_current_choices_and_reviewed_empty_are_read_only(dataset, monkeypatch):
    before = (dataset.args.data_dir / "gallery.sqlite").read_bytes()
    monkeypatch.setattr(RunService, "start", lambda *a: pytest.fail("Audit started a run"))
    monkeypatch.setattr(RunService, "prepare_context", lambda *a: pytest.fail("Audit started context preparation"))
    received = []
    actual_ready = RunService.ready

    def observe(self, value):
        received.append(value.model_dump())
        return actual_ready(self, value)

    monkeypatch.setattr(RunService, "ready", observe)
    report = audit_module.audit(dataset.args)
    assert report["prepared_acceptance_passed"] is True
    assert report["connect"]["prepared"] == 5 and report["connect"]["confirmed_empty"] == 1
    assert report["contexts"]["prepared"] == 4 and report["contexts"]["confirmed_empty"] == 1
    assert report["probe"]["context_outside_connect"] == ["c"]
    assert len(report["connect_graph"]["three_hop_routes"]["starts_with_three_hop_route"]) == 4
    assert report["read_only_verified"] and report["execution_attempts"] == 0
    assert set(report["delta"].values()) == {0}
    assert report["logical_fingerprints_before"] == report["logical_fingerprints_after"]
    assert (dataset.args.data_dir / "gallery.sqlite").read_bytes() == before
    assert len(received) == 5 and all(set(item) == {"anchor", "direction", "year", "request_revision"} for item in received)
    assert report["ui_acceptance_verified"] is False and report["semantic_accuracy_verified"] is False


@pytest.mark.parametrize("damage", ["corrupt_json", "stale_revision", "unreviewed_member", "empty_without_full_inspection"])
def test_invalid_context_never_becomes_confirmed_empty(dataset, damage):
    store = Store(dataset.args.data_dir)
    key = dataset.context_keys["d" if damage == "empty_without_full_inspection" else "a"]
    if damage == "corrupt_json":
        store.write("UPDATE cache SET data='broken' WHERE key=?", (key,))
    elif damage == "stale_revision":
        store.write("UPDATE cache SET revision=revision-1 WHERE key=?", (key,))
    else:
        value = json.loads(store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"])
        if damage == "unreviewed_member":
            value["evidence"]["reviewed_members"] = []
        else:
            value["evidence"]["inspected_photo_ids"] = ["d"]
            value["evidence"]["photo_versions"] = {"d": "v1"}
        store.write("UPDATE cache SET data=? WHERE key=?", (json.dumps(value), key))
    store.close()
    report = audit_module.audit(dataset.args)
    pid = "d" if damage == "empty_without_full_inspection" else "a"
    context = next(row for row in report["contexts"]["photos"] if row["photo_id"] == pid)
    assert context["prepared"] is False and context["confirmed_empty"] is False
    assert report["prepared_acceptance_passed"] is False and report["read_only_verified"] is True


def test_inspected_target_version_change_invalidates_context(dataset):
    store = Store(dataset.args.data_dir)
    photo = store.photo("c").model_copy(update={"version": "v2"})
    # Deliberately simulate a stale evidence envelope without a revision bump.
    store.write("UPDATE photos SET version=?,data=? WHERE id=?", ("v2", photo.model_dump_json(), "c"))
    store.close()
    report = audit_module.audit(dataset.args)
    context = next(row for row in report["contexts"]["photos"] if row["photo_id"] == "a")
    assert not context["evidence_valid"] and not context["prepared"]
    assert not report["all_preparation_complete"]


def test_failed_context_and_corrupt_connect_are_not_empty(dataset):
    store = Store(dataset.args.data_dir)
    key = dataset.context_keys["a"]
    store.write("DELETE FROM cache WHERE key=?", (key,))
    request = RunRequest(role="context", photo_ids=["a"], idempotency_key=f"context:{key}:failed")
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("failed", request.idempotency_key, request.model_dump_json(), "failed", None, "fixture failure", 1))
    store.write("UPDATE cache SET data='broken' WHERE key=?", (dataset.connect_keys["rb"],))
    store.close()
    report = audit_module.audit(dataset.args)
    context = next(row for row in report["contexts"]["photos"] if row["photo_id"] == "a")
    connection = next(row for row in report["connect"]["choices"] if row["source_region"]["region_id"] == "rb")
    assert context["state"] == "failed" and context["confirmed_empty"] is False
    assert connection["state"] == "pending" and connection["confirmed_empty"] is False
    assert connection["cache_diagnosis"] == "corrupt_json"
    assert not report["prepared_acceptance_passed"]


def test_active_preparation_is_refused_before_any_lookup(dataset, monkeypatch):
    store = Store(dataset.args.data_dir)
    request = RunRequest(role="analyst", photo_ids=["a"])
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("active", request.idempotency_key, request.model_dump_json(), "running", None, None, 1))
    store.close()
    monkeypatch.setattr(RunService, "ready", lambda *a: pytest.fail("Lookup during active preparation"))
    with pytest.raises(ValueError, match="Preparation is active"):
        audit_module.audit(dataset.args)
    assert not dataset.args.report.exists()


def test_aware_fixture_uses_seoul_date_unknown_and_naive_have_no_capture():
    photos = [PhotoAsset(id="aware", device_id="synthetic-demo", version="v", width=10, height=10,
                         captured_at="2026-06-13T16:00:00+00:00", time_source="demo_fixture"),
              PhotoAsset(id="unknown", device_id="synthetic-demo", version="v", width=10, height=10,
                         captured_at="2026-06-14T12:00:00+09:00", time_source="unknown"),
              PhotoAsset(id="naive", device_id="synthetic-demo", version="v", width=10, height=10,
                         captured_at="2026-06-14T12:00:00", time_source="exif")]
    result = audit_module.metadata_review(photos)
    assert result["valid"] and result["capture_present"] == 1 and result["capture_absent"] == 2
    assert result["photos"][0]["capture"]["date"] == "2026-06-14"


def test_two_photo_cycle_cannot_count_as_three_hops():
    edges = [{"source_photo_id": "a", "next_photo_id": "b"}, {"source_photo_id": "b", "next_photo_id": "a"}]
    assert audit_module.three_hop_routes(edges)["example_count"] == 0


@pytest.mark.parametrize("damage", ["missing_plan", "wording_paths", "wording_model"])
def test_context_v3_review_evidence_is_required(dataset, damage):
    store = Store(dataset.args.data_dir)
    key = dataset.context_keys["a"]
    value = store.cache_get(key)
    if damage == "missing_plan": del value["evidence"]["planned_photo_ids"]
    elif damage == "wording_paths": value["evidence"]["wording_checked_paths"] = ["/summary"]
    else: value["evidence"]["wording_review_model"] = "wrong-model"
    store.cache_put(key, value)
    store.close()
    report = audit_module.audit(dataset.args)
    context = next(row for row in report["contexts"]["photos"] if row["photo_id"] == "a")
    assert not context["prepared"] and not context["evidence_valid"] and not context["confirmed_empty"]
