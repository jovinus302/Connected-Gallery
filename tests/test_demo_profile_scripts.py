import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from connected_gallery.adapters.store import Store
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import PhotoAsset, RunRequest, ExploreInput, SemanticAnchor


def script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_profile_overrides_envfile_before_app_construction(tmp_path, monkeypatch):
    from connected_gallery.bootstrap import api
    launcher = script("start-demo.py")
    (tmp_path / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    (tmp_path / "gallery.sqlite").touch()
    env_file = tmp_path / "model.env"
    env_file.write_text("CG_MODEL=other-public-model\nCG_FALLBACK_MODEL=unchanged-fallback\n")
    monkeypatch.setenv("CG_MODEL", "original-model")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "original-fallback")
    for name in ["CG_MODEL_DIR", "CG_DATA_DIR", "CG_AUTO_ORGANIZE", "CG_ANALYSIS_CONCURRENCY", "CG_SERVER_TOKEN"]:
        monkeypatch.delenv(name, raising=False)
    class ReachedConstruction(Exception):
        pass
    def create_app(root, **kwargs):
        assert os.environ["CG_MODEL"] == "claude-sonnet-5"
        assert os.environ["CG_FALLBACK_MODEL"] == "unchanged-fallback"
        assert kwargs["recover_runs"] is False
        raise ReachedConstruction
    monkeypatch.setattr(api, "create_app", create_app)
    monkeypatch.setattr(sys, "argv", ["start-demo.py", "--data-dir", str(tmp_path), "--env-file", str(env_file), "--prepared-only"])
    with pytest.raises(ReachedConstruction):
        launcher.main()
    assert not (tmp_path / "demo-launch.html").exists()


def test_service_audit_reads_cache_for_marker_model(tmp_path, monkeypatch):
    audit = script("audit-demo.py")
    root = tmp_path / "demo"
    root.mkdir()
    (root / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    monkeypatch.setenv("CG_MODEL", "claude-sonnet-5")
    store = Store(root)
    store.upsert(PhotoAsset(id="sample", device_id="synthetic-demo", version="v1", width=40, height=30))
    store.upsert(PhotoAsset(id="related", device_id="synthetic-demo", version="v1", width=40, height=30))
    region = {"id": "region", "photo_id": "sample", "box": {"x": 0, "y": 0, "width": 1, "height": 1},
              "kind": "object", "label": "선택 대상", "evidence": "visible fixture"}
    store.write("INSERT INTO analyses VALUES(?,?)", ("sample", json.dumps({"regions": [region]})))
    query = ExploreInput(anchor=SemanticAnchor(photo_id="sample", region_id="region", box=region["box"], kind="object", label="선택 대상"))
    service = RunService(store, audit.NoExecution())
    store.cache_put(service.cache_key(RunRequest(role="explorer", explore=query)), {
        "label": "대상", "items": [{"photo_id": "related", "reason": "verified fixture"}], "complete": True,
        "groups": [{"id": "g", "title": "Related", "reason": "verified fixture", "photo_ids": ["related"]}],
        "grouping_status": "ready"})
    store.close()
    monkeypatch.setenv("CG_MODEL", "wrong-model")
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["audit-demo.py", "--data-dir", str(root), "--report", str(report)])
    audit.main()
    assert json.loads(report.read_text(encoding="utf-8"))["ready_count"] == 1
    assert os.environ["CG_MODEL"] == "claude-sonnet-5"
