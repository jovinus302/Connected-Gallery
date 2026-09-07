"""No models or live servers: verify the audit's transport and zero-work claims."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.demo import DemoSession
from test_complete_demo_audit import dataset as prepared_dataset

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
        CREATE TABLE cache(key TEXT,data TEXT);
        INSERT INTO cache VALUES('prepared','private cached evidence');
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
        if request.url.path == "/assets/opaque/context":
            assert request.method == "GET"
            return httpx.Response(200, json={"photo_id": "opaque", "state": "empty", "revision": 1,
                                           "context": {"summary": "확인한 관련 사진이 없어요.", "groups": []}})
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
    assert calls == [("GET", "/health"), ("GET", "/demo/catalog")] + [("POST", "/explorations/ready")] * 3 + [("GET", "/assets/opaque/context")] * 3
    assert report["context_count"] == 1 and report["context_states"]["empty"] == 1
    assert report["context_prepared_repeated_lookup"]["count"] == 2
    assert report["context_repeated_lookup"]["p50_ms"] <= report["context_repeated_lookup"]["p95_ms"]
    assert report["logical_fingerprints_before"] == report["logical_fingerprints_after"]
    assert report["all_lookups_prepared"] is True and report["semantic_accuracy_verified"] is False
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
    (audit_data.data_dir / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5","context_model":"gpt-5.4-mini"}')
    monkeypatch.setenv("CG_MODEL", "other-model")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "other-context")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "unchanged-fallback")
    mock_transport(monkeypatch, audit_data)
    assert audit.run(audit_data) == 0
    assert os.environ["CG_MODEL"] == "claude-sonnet-5"
    assert os.environ["CG_FALLBACK_MODEL"] == "unchanged-fallback"
    assert json.loads(audit_data.report.read_text(encoding="utf-8"))["demo_model"] == "claude-sonnet-5"
    assert json.loads(audit_data.report.read_text(encoding="utf-8"))["context_model"] == "gpt-5.4-mini"


def test_context_get_in_place_cache_mutation_cannot_pass_zero_work_check(audit_data, monkeypatch):
    original_client = httpx.Client
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"revision": 1})
        if request.url.path == "/demo/catalog":
            return httpx.Response(200, json={"live_enabled": False, "synthetic": True, "assets": [{"id": "opaque"}]})
        if request.url.path == "/explorations/ready":
            return httpx.Response(200, json={"state": "pending", "revision": 1})
        assert request.method == "GET" and request.url.path == "/assets/opaque/context"
        with sqlite3.connect(audit_data.data_dir / "gallery.sqlite") as db:
            db.execute("UPDATE cache SET data='changed cached evidence' WHERE key='prepared'")
        return httpx.Response(200, json={"photo_id": "opaque", "state": "pending", "revision": 1, "context": None})

    factory = lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler))
    assert audit.run(audit_data, client_factory=factory) == 1
    report = json.loads(audit_data.report.read_text(encoding="utf-8"))
    assert set(report["delta"].values()) == {0}
    assert report["logical_fingerprints_before"]["cache"] != report["logical_fingerprints_after"]["cache"]
    assert report["zero_work_observed"] is False and report["lookup_audit_passed"] is False
    assert "private cached evidence" not in audit_data.report.read_text(encoding="utf-8")


def test_twenty_photos_forty_seven_choices_and_no_prepared_context_are_reported_as_partial(audit_data):
    with sqlite3.connect(audit_data.data_dir / "gallery.sqlite") as db:
        db.execute("DELETE FROM photos")
        db.execute("DELETE FROM analyses")
        photos, number = [], 0
        for index in range(20):
            pid = f"p{index}"
            photos.append({"id": pid})
            db.execute("INSERT INTO photos VALUES(?)", (pid,))
            regions = []
            for _ in range(3 if index < 7 else 2):
                regions.append({"id": f"r{number}", "kind": "object", "label": "fixture subject",
                                "box": {"x": 0, "y": 0, "width": 1, "height": 1}})
                number += 1
            db.execute("INSERT INTO analyses VALUES(?,?)", (pid, json.dumps({"regions": regions})))
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/health":
            value = {"revision": 1}
        elif request.url.path == "/demo/catalog":
            value = {"live_enabled": False, "synthetic": True, "assets": photos}
        elif request.url.path == "/explorations/ready":
            region = json.loads(request.content)["anchor"]["region_id"]
            value = {"state": "ready" if int(region[1:]) < 25 else "pending", "revision": 1}
            if value["state"] == "ready":
                source = json.loads(request.content)["anchor"]["photo_id"]
                target = "p1" if source == "p0" else "p0"
                value["result"] = {"label": "fixture relation", "complete": True, "grouping_status": "ready",
                                   "items": [{"photo_id": target, "reason": "fixture evidence"}],
                                   "groups": [{"id": "g", "title": "Fixture", "reason": "fixture evidence", "photo_ids": [target]}]}
        else:
            assert request.method == "GET" and request.url.path.endswith("/context")
            value = {"photo_id": request.url.path.split("/")[2], "state": "pending", "revision": 1, "context": None}
        return httpx.Response(200, json=value)

    factory = lambda **kwargs: httpx.Client(**kwargs, transport=httpx.MockTransport(handler))
    assert audit.run(audit_data, client_factory=factory) == 0
    report = json.loads(audit_data.report.read_text(encoding="utf-8"))
    assert report["photo_count"] == report["context_count"] == 20 and report["anchor_count"] == 47
    assert report["ready_count"] == 25 and report["pending_count"] == 22
    assert report["context_states"] == {"ready": 0, "empty": 0, "pending": 20, "running": 0, "failed": 0}
    assert report["lookup_audit_passed"] is True and report["all_lookups_prepared"] is False
    assert report["ready_repeated_lookup"]["count"] == 25 * audit_data.repeat
    assert report["context_prepared_repeated_lookup"] == {"count": 0}
    assert report["context_repeated_lookup"]["count"] == 20 * audit_data.repeat
    assert len(calls) == 2 + (47 + 20) * (audit_data.repeat + 1)
    assert not any(path in {"/runs", "/demo/session"} or path.endswith("/prepare") for _, path in calls)


@pytest.mark.parametrize("change", ["photo_id", "revision", "state"])
def test_context_http_must_match_the_current_source_revision_and_state(audit_data, change):
    def handler(request):
        if request.url.path == "/health":
            value = {"revision": 1}
        elif request.url.path == "/demo/catalog":
            value = {"live_enabled": False, "synthetic": True, "assets": [{"id": "opaque"}]}
        elif request.url.path == "/explorations/ready":
            value = {"state": "pending", "revision": 1}
        else:
            value = {"photo_id": "opaque", "state": "pending", "revision": 1, "context": None}
            value[change] = {"photo_id": "foreign", "revision": 2, "state": "ready"}[change]
        return httpx.Response(200, json=value)

    factory = lambda **kwargs: httpx.Client(**kwargs, transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        audit.run(audit_data, client_factory=factory)
    assert not audit_data.report.exists()


def test_actual_prepared_only_api_testclient_reads_context_without_consuming_launch_key_or_starting_work(prepared_dataset, monkeypatch, tmp_path):
    root = prepared_dataset.args.data_dir
    token = "http-audit-test-only-" + "a" * 32
    (root / "server-token.txt").write_text(token)
    monkeypatch.setenv("CG_SERVER_TOKEN", token)
    monkeypatch.delenv("CG_CONTEXT_MODEL", raising=False)
    launch_key = "untouched-test-launch-" + "b" * 32
    demo = DemoSession(launch_key, port=8877, live_enabled=False)
    calls = []

    class NoExecution:
        calls = 0

        async def execute(self, *args):
            self.calls += 1
            raise AssertionError("HTTP lookup must never execute a model")

    runner = NoExecution()
    app = create_app(root, runner_factory=lambda store: runner, demo=demo, recover_runs=False)
    monkeypatch.setattr(app.state.service, "start", lambda *args: pytest.fail("Lookup started a run"))
    monkeypatch.setattr(app.state.service.contexts, "prepare", lambda *args: pytest.fail("GET started context preparation"))
    # Make one real context pending; the audit must still measure it and must
    # not automatically submit the missing context for preparation.
    app.state.store.write("DELETE FROM cache WHERE key=?", (prepared_dataset.context_keys["a"],))
    args = SimpleNamespace(data_dir=root, report=tmp_path / "http-asgi-fixture-report.json", url=demo.origin, repeat=2)
    with TestClient(app, base_url=demo.origin) as web:
        @contextmanager
        def factory(**options):
            assert options["trust_env"] is False and options["follow_redirects"] is False

            class Requests:
                def get(self, path):
                    calls.append(("GET", path))
                    return web.get(path, headers=options["headers"], follow_redirects=False)

                def post(self, path, **kwargs):
                    assert path == "/explorations/ready"
                    calls.append(("POST", path))
                    return web.post(path, headers=options["headers"], follow_redirects=False, **kwargs)

            yield Requests()

        assert audit.run(args, client_factory=factory) == 0
        assert runner.calls == 0 and not app.state.service.tasks
        assert demo.launch_key == launch_key and demo.session is None
    report = json.loads(args.report.read_text(encoding="utf-8"))
    assert report["ready_count"] == 5 and report["context_count"] == 4
    assert report["context_states"] == {"ready": 2, "empty": 1, "pending": 1, "running": 0, "failed": 0}
    assert report["zero_work_observed"] and report["lookup_audit_passed"] and not report["all_lookups_prepared"]
    assert set(report["delta"].values()) == {0}
    assert report["logical_fingerprints_before"] == report["logical_fingerprints_after"]
    assert len([path for method, path in calls if path.endswith("/context")]) == 4 * 3
    assert token not in args.report.read_text(encoding="utf-8") and launch_key not in args.report.read_text(encoding="utf-8")


def test_p50_and_p95_keep_first_client_and_prepared_repeated_samples_comparable():
    value = audit.stats([10, 1, 3, 4, 5, 6, 7, 8, 9, 2])
    assert value["p50_ms"] == value["median_ms"] == 5.5 and value["p95_ms"] == 10
    assert audit.stats([]) == {"count": 0}


@pytest.mark.parametrize("url", ["https://example.com", "http://127.0.0.1:8765", "http://localhost:8877", "http://127.0.0.1:8877?key=secret", "http://token@127.0.0.1:8877", "http://127.0.0.1:8877/path"])
def test_http_audit_refuses_other_origins_or_credentials(url):
    with pytest.raises(ValueError):
        audit.loopback_origin(url)
