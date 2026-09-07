"""Evaluation rubrics never enter retrieval; incomplete cases stay unevaluated."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from connected_gallery.adapters.store import Store
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import PhotoAsset, ExploreInput, SemanticAnchor, RunRequest

spec = importlib.util.spec_from_file_location("demo_evaluation", Path(__file__).resolve().parents[1] / "scripts" / "evaluate-demo.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_MODEL", raising=False)
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "synthetic-demo.json").write_text('{"synthetic":true}')
    originals = tmp_path / "samples"
    originals.mkdir()
    store = Store(root)
    assets = []
    for pid in ["source", "expected", "missing", "extra"]:
        payload = ("generated fixture " + pid).encode()
        (originals / (pid + ".png")).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        store.upsert(PhotoAsset(id=pid, device_id="synthetic-demo", version=digest, width=40, height=30))
        assets.append({"runtime_photo_id": pid, "sha256": digest})
    anchor = {"photo_id": "source", "region_id": "region", "kind": "object", "label": "선택 대상",
              "box": {"x": .1, "y": .1, "width": .5, "height": .5}}
    region = {"photo_id": "source", "id": "region", "kind": "object", "label": "선택 대상", "box": anchor["box"], "evidence": "visible fixture"}
    store.write("INSERT INTO analyses VALUES(?,?)", ("source", json.dumps({"regions": [region]})))
    result = {"label": "선택 대상", "complete": True, "grouping_status": "ready",
              "items": [{"photo_id": "expected", "reason": "실제 저장된 검색 근거"},
                        {"photo_id": "extra", "reason": "확정적인 동일성 주장도 자동 승인하지 않음"}],
              "groups": [{"id": "g", "title": "보이는 관계", "reason": "사람이 검토할 실제 설명", "photo_ids": ["expected", "extra"]}]}
    service = RunService(store, evaluation.NoExecution())
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(**anchor)))), result)
    case = {"id": "case", "title": "대상 선택", "source_region": anchor, "source_image_sha256": assets[0]["sha256"],
            "minimum_expected_hits": {"photo_ids": ["expected", "missing"], "minimum_count": 2},
            "manual_review_criteria": ["선택 기준이 유지되는지 사람이 검토"],
            "forbidden_identity_claims": [{"photo_ids": ["extra"], "claim": "확정적인 동일성 주장", "verification": "manual_semantic_review"}]}
    document = {"schema_version": 1, "purpose": "evaluation_only_never_runtime_input", "synthetic": True,
                "provenance": {"images": "samples"}, "analysis_snapshot_revision": store.revision,
                "assets": assets, "cases": [case]}
    case_path = tmp_path / "cases.json"
    case_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    store.close()
    return SimpleNamespace(data_dir=root, cases=case_path, report=tmp_path / "report.json")


def test_reports_minimum_hits_and_preserves_unreviewed_semantics(fixture, monkeypatch):
    original = (fixture.data_dir / "gallery.sqlite").read_bytes()
    ready = RunService.ready
    captured = []
    def observe(self, query):
        captured.append(query.model_dump())
        return ready(self, query)
    monkeypatch.setattr(RunService, "ready", observe)
    monkeypatch.setattr(RunService, "start", lambda *args: pytest.fail("Evaluation must never create work"))
    report = evaluation.evaluate(fixture)
    case = report["cases"][0]
    assert case["state"] == "ready"
    assert case["hit_ids"] == ["expected"] and case["missing_ids"] == ["missing"]
    assert case["additional_ids_for_manual_review"] == ["extra"]
    assert case["minimum_retrieval_coverage"]["fraction"] == .5
    assert case["minimum_count_reached"] is False
    assert case["items"][0]["reason"] == "실제 저장된 검색 근거"
    assert case["groups"][0]["reason"] == "사람이 검토할 실제 설명"
    assert case["manual_review_criteria"] and case["forbidden_identity_claims"]
    assert report["group_semantics_evaluated"] is False and report["overall_accuracy_evaluated"] is False
    assert report["metric_scope"] == "minimum retrieval coverage only"
    assert report["event_delta"] == report["execution_attempts"] == 0
    assert report["read_only_verified"] is True
    assert (fixture.data_dir / "gallery.sqlite").read_bytes() == original
    assert len(captured) == 1 and captured[0]["anchor"]["photo_id"] == "source"
    assert "expected" not in json.dumps(captured) and "manual_review" not in json.dumps(captured)


def test_pending_case_does_not_count_as_retrieval_failure_or_pass(fixture):
    store = Store(fixture.data_dir)
    store.write("DELETE FROM cache")
    store.close()
    case = evaluation.evaluate(fixture)["cases"][0]
    assert case["state"] == "pending"
    assert case["minimum_count_reached"] is None and case["minimum_retrieval_coverage"] is None
    assert case["missing_ids"] is None
    assert case["unevaluated_expected_ids"] == ["expected", "missing"]


def test_evaluation_uses_public_marker_model_for_prepared_lookup(fixture, monkeypatch):
    document = json.loads(fixture.cases.read_text(encoding="utf-8"))
    anchor = document["cases"][0]["source_region"]
    store = Store(fixture.data_dir)
    result = json.loads(store.rows("SELECT data FROM cache")[0]["data"])
    monkeypatch.setenv("CG_MODEL", "claude-sonnet-5")
    service = RunService(store, evaluation.NoExecution())
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(**anchor)))), result)
    store.close()
    (fixture.data_dir / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    monkeypatch.setenv("CG_MODEL", "other-model")
    report = evaluation.evaluate(fixture)
    assert report["cache_model"] == "claude-sonnet-5" and report["cases"][0]["state"] == "ready"
    assert report["read_only_verified"] is True and report["execution_attempts"] == 0


@pytest.mark.parametrize("change", ["box", "hash", "region"])
def test_stale_case_never_reaches_retrieval(fixture, monkeypatch, change):
    document = json.loads(fixture.cases.read_text(encoding="utf-8"))
    case = document["cases"][0]
    if change == "box":
        case["source_region"]["box"]["x"] = .2
    elif change == "region":
        case["source_region"]["region_id"] = "obsolete-region"
    else:
        (fixture.cases.parent / "samples" / "source.png").write_bytes(b"changed original")
    fixture.cases.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(RunService, "ready", lambda *args: pytest.fail("Stale cases must not query results"))
    result = evaluation.evaluate(fixture)["cases"][0]
    assert result["state"] == "stale_case" and result["stale_reasons"]
    assert result["minimum_count_reached"] is None


def test_foreign_case_and_private_device_refused(fixture):
    document = json.loads(fixture.cases.read_text(encoding="utf-8"))
    document["cases"][0]["source_region"]["photo_id"] = "foreign"
    fixture.cases.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="foreign photo"):
        evaluation.evaluate(fixture)
    assert not fixture.report.exists()
    document["cases"][0]["source_region"]["photo_id"] = "source"
    fixture.cases.write_text(json.dumps(document), encoding="utf-8")
    store = Store(fixture.data_dir)
    photo = store.photo("extra").model_copy(update={"device_id": "private-phone", "version": "changed"})
    store.upsert(photo)
    store.close()
    with pytest.raises(ValueError, match="synthetic-demo"):
        evaluation.evaluate(fixture)
    assert not fixture.report.exists()
