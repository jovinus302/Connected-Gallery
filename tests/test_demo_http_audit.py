"""No models or live servers: verify the audit's transport and zero-work claims."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location("demo_http_audit", Path(__file__).resolve().parents[1] / "scripts" / "audit-demo-http.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def audit_data(tmp_path):
    root = tmp_path / "synthetic"
    root.mkdir()
    (root / "synthetic-demo.json").write_text('{"synthetic":true}')
    (root / "server-token.txt").write_text("audit-local-test-" + "a" * 32)
    db = sqlite3.connect(root / "gallery.sqlite")
    db.executescript("""
        CREATE TABLE state(key TEXT,value INTEGER);
        INSERT INTO state VALUES('revision',1);
        CREATE TABLE events(kind TEXT);
        CREATE TABLE runs(status TEXT);
        CREATE TABLE photos(id TEXT);
        INSERT INTO photos VALUES('opaque');
        CREATE TABLE analyses(photo_id TEXT,data TEXT);
    """)
    db.execute("INSERT INTO analyses VALUES(?,?)", ("opaque", json.dumps({"regions": [{
        "id": "region", "box": {"x": 0, "y": 0, "width": 1, "height": 1},
        "label": "관찰된 대상", "kind": "object"}]})))
    db.commit()
    db.close()
    return SimpleNamespace(data_dir=root, report=tmp_path / "report.json", url="http://127.0.0.1:8877", repeat=2)


def mock_transport(monkeypatch, audit_data, mutate=False):
    calls = []
    original_client = httpx.Client
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.url.host == "127.0.0.1"
        assert "authorization" in request.headers
        assert "audit-local-test" not in str(request.url)
        if request.url.path == "/health":
            return httpx.Response(200, json={"revision": 1, "agent_spec": 16})
        if request.url.path == "/demo/catalog":
            return httpx.Response(200, json={"live_enabled": False, "synthetic": True, "assets": [{"id": "opaque"}]})
        assert request.url.path == "/explorations/ready"
        assert request.method == "POST"
        if mutate and len(calls) == 5:
            with sqlite3.connect(audit_data.data_dir / "gallery.sqlite") as db:
                db.execute("INSERT INTO events VALUES('model_timing')")
        return httpx.Response(200, json={"state": "ready", "revision": 1, "result": {
            "label": "관찰된 대상", "items": [], "groups": [], "grouping_status": "ready", "complete": True}})
    def client(*args, **kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original_client(*args, **kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(audit.httpx, "Client", client)
    return calls


def test_http_audit_records_real_counter_deltas_without_secret(audit_data, monkeypatch, capsys):
    calls = mock_transport(monkeypatch, audit_data)
    assert audit.run(audit_data) == 0
    report = json.loads(audit_data.report.read_text(encoding="utf-8"))
    assert report["ready_count"] == 1
    assert report["delta"]["model_timing_events"] == 0
    assert report["delta"]["events"] == 0
    assert report["lookup_audit_passed"] is True
    assert len(report["anchors"][0]["repeat_http_ms"]) == 2
    assert calls == [("GET", "/health"), ("GET", "/demo/catalog")] + [("POST", "/explorations/ready")] * 3
    assert "audit-local-test" not in audit_data.report.read_text(encoding="utf-8") + capsys.readouterr().out


def test_http_audit_refuses_active_work_before_any_http(audit_data, monkeypatch):
    with sqlite3.connect(audit_data.data_dir / "gallery.sqlite") as db:
        db.execute("INSERT INTO runs VALUES('running')")
    monkeypatch.setattr(audit.httpx, "Client", lambda **kwargs: pytest.fail("Must refuse before network access"))
    with pytest.raises(ValueError, match="Preparation is still active"):
        audit.run(audit_data)
    assert not audit_data.report.exists()


def test_http_audit_does_not_claim_zero_models_when_events_change(audit_data, monkeypatch):
    mock_transport(monkeypatch, audit_data, mutate=True)
    assert audit.run(audit_data) == 1
    report = json.loads(audit_data.report.read_text(encoding="utf-8"))
    assert report["delta"]["model_timing_events"] == 1
    assert report["lookup_audit_passed"] is False


def test_http_audit_applies_public_marker_model_without_changing_fallback(audit_data, monkeypatch):
    (audit_data.data_dir / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    monkeypatch.setenv("CG_MODEL", "other-model")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "unchanged-fallback")
    mock_transport(monkeypatch, audit_data)
    assert audit.run(audit_data) == 0
    assert os.environ["CG_MODEL"] == "claude-sonnet-5"
    assert os.environ["CG_FALLBACK_MODEL"] == "unchanged-fallback"
    assert json.loads(audit_data.report.read_text(encoding="utf-8"))["demo_model"] == "claude-sonnet-5"


@pytest.mark.parametrize("url", ["https://example.com", "http://127.0.0.1:8765", "http://localhost:8877", "http://127.0.0.1:8877?key=secret", "http://token@127.0.0.1:8877", "http://127.0.0.1:8877/path"])
def test_http_audit_refuses_other_origins_or_credentials(url):
    with pytest.raises(ValueError):
        audit.loopback_origin(url)
