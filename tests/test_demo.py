"""The local browser cannot acquire photo access through an arbitrary web origin."""
import io
import json
import secrets
import sqlite3

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.demo import DemoSession, COOKIE
from connected_gallery.bootstrap.auth import server_token
from connected_gallery.domain.models import PhotoAsset, RunRequest, ExploreInput, SemanticAnchor
from empty_proof_fixture import negative_proof


class IdleRunner:
    calls = 0

    async def execute(self, rid, request):
        self.calls += 1
        return {"label": "fixture", "items": [], "groups": [], "grouping_status": "ready", "complete": True}


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_SERVER_TOKEN", raising=False)
    monkeypatch.setenv("CG_AUTO_ORGANIZE", "0")
    key = secrets.token_urlsafe(32)
    session = DemoSession(key)
    runner = IdleRunner()
    app = create_app(tmp_path, lambda store: runner, demo=session)
    app.state.service.auto_enabled = False
    store = app.state.store
    store.upsert(PhotoAsset(id="opaque_A", device_id="synthetic", version="v1", width=60, height=40))
    store.upsert(PhotoAsset(id="opaque_B", device_id="synthetic", version="v1", width=60, height=40))
    image = io.BytesIO()
    Image.new("RGB", (60, 40), "green").save(image, "JPEG")
    for pid in ["opaque_A", "opaque_B"]:
        store.put_image(pid, image.getvalue())
    for pid, description in [("opaque_A", "절벽과 바다가 보이는 풍경"), ("opaque_B", "테이블 위의 와인 병")]:
        store.write("INSERT INTO analyses VALUES (?,?)", (pid, json.dumps({
            "photo_id": pid, "description": description, "ocr": "", "regions": []})))
    with TestClient(app, base_url=session.origin) as client:
        yield client, app, session, key, runner, tmp_path


def login(client, session, key):
    return client.post("/demo/session", json={"key": key}, headers={"Origin": session.origin})


def test_public_shell_contains_no_credential_or_photo_data(demo):
    client, app, session, key, runner, root = demo
    for path in ["/demo", "/demo/app.js", "/demo/style.css"]:
        response = client.get(path)
        assert response.status_code == 200
        assert key not in response.text
        assert server_token(root) not in response.text
        assert "opaque_A" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Frame-Options"] == "DENY"
    for path in ["/demo/catalog", "/assets/opaque_A/preview", "/assets/opaque_A/analysis"]:
        assert client.get(path).status_code == 401


def test_one_use_key_grants_only_scoped_browser_session(demo):
    client, app, session, key, runner, root = demo
    response = login(client, session, key)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert login(client, session, key).status_code == 401
    assert client.get("/demo/catalog").status_code == 200
    assert client.get("/assets/opaque_A/preview").headers["content-type"] == "image/jpeg"
    assert client.get("/assets/opaque_A/analysis").status_code == 200
    assert client.get("/assets").status_code == 401
    for method, path, payload in [("POST", "/assets/sync", {"deleted_ids": ["opaque_A"]}),
                                  ("DELETE", "/assets/opaque_A", None),
                                  ("POST", "/feedback", {}), ("GET", "/spaces", None)]:
        assert client.request(method, path, json=payload, headers={"Origin": session.origin}).status_code == 401
    for role in ["organizer", "analyst"]:
        req = {"role": role, "photo_ids": ["opaque_A"] if role == "analyst" else []}
        assert client.post("/runs", json=req, headers={"Origin": session.origin}).status_code == (410 if role == "organizer" else 403)
    assert len(app.state.store.photos()) == 2


def test_local_file_bootstrap_and_host_origin_guards(demo):
    client, app, session, key, runner, root = demo
    assert client.post("/demo/session", json={"key": key}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/demo", headers={"Host": "attacker.example", "X-Forwarded-Host": session.host}).status_code == 403
    assert client.get("/demo", headers={"Host": "localhost:8877"}).status_code == 403
    response = client.post("/demo/session", data={"key": key},
                           headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/demo"
    assert client.get("/demo", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    for headers in [{"Origin": "https://evil.example"}, {"Origin": "null"},
                    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}]:
        assert client.get("/demo/catalog", headers=headers).status_code == 403
    assert client.post("/runs", json={"role": "organizer"}).status_code == 401


def test_catalog_search_reads_stored_observations(demo):
    client, app, session, key, runner, root = demo
    login(client, session, key)
    data = client.get("/demo/catalog", params={"q": "바다"}).json()
    assert [p["id"] for p in data["assets"]] == ["opaque_A"]
    assert data["total"] == 2 and data["synthetic"] is True
    assert client.get("/demo/catalog", params={"q": "wine"}).json()["assets"] == []
    app.state.store.write("UPDATE analyses SET data=? WHERE photo_id=?", (
        json.dumps({"photo_id": "opaque_B", "description": "새로 기록한 단서", "regions": []}), "opaque_B"))
    assert client.get("/demo/catalog", params={"q": "와인"}).json()["assets"] == []
    assert client.get("/demo/catalog", params={"q": "새로 기록"}).json()["assets"][0]["id"] == "opaque_B"
    assert runner.calls == 0


def test_ready_endpoint_returns_cached_empty_without_run_or_model_call(demo):
    client, app, session, key, runner, root = demo
    login(client, session, key)
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="opaque_A"))
    origin = {"Origin": session.origin}
    assert client.post("/explorations/ready", json=explore.model_dump(), headers=origin).json()["state"] == "pending"
    result = {"label": "관련 사진", "items": [], "groups": [], "grouping_status": "ready", "complete": True}
    app.state.store.cache_put(app.state.service.cache_key(RunRequest(role="explorer", explore=explore)), result)
    assert client.post("/explorations/ready", json=explore.model_dump(), headers=origin).json()["state"] == "pending"
    result["empty_evidence"] = negative_proof(app.state.store, explore)
    app.state.store.cache_put(app.state.service.empty_cache_key(explore), result)
    response = client.post("/explorations/ready", json=explore.model_dump(), headers=origin)
    assert response.status_code == 200 and response.json()["state"] == "ready"
    assert response.json()["result"]["items"] == []
    assert app.state.store.rows("SELECT id FROM runs") == [] and runner.calls == 0
    app.state.store.bump()
    assert client.post("/explorations/ready", json=explore.model_dump(), headers=origin).json()["state"] == "pending"


def test_logout_expiration_and_bearer_remain_independent(demo):
    client, app, session, key, runner, root = demo
    login(client, session, key)
    cookie = client.cookies.get(COOKIE)
    session.session_until = 0
    assert client.get("/demo/catalog").status_code == 401
    token = {"Authorization": "Bearer " + server_token(root)}
    assert client.get("/assets", headers=token).status_code == 200
    assert client.post("/explorations/ready", headers=token, json={"anchor": {"photo_id": "opaque_A"}}).status_code == 200
    session.session_until = float("inf")
    assert client.post("/demo/logout", headers={"Origin": session.origin}).status_code == 200
    assert client.get("/demo/catalog", headers={"Cookie": f"{COOKIE}={cookie}"}).status_code == 401


def test_invalid_session_inputs_do_not_grant_access(demo):
    client, app, session, key, runner, root = demo
    for payload in [{"key": "wrong"}, {"key": "한글"}, {"key": 42}, {}]:
        assert client.post("/demo/session", json=payload, headers={"Origin": session.origin}).status_code == 401
    assert client.get("/demo/catalog").status_code == 401
    session.launch_until = 0
    assert login(client, session, key).status_code == 401


def test_demo_refuses_production_port():
    with pytest.raises(ValueError):
        DemoSession("k" * 40, port=8765)


def test_prepared_only_lifespan_does_not_take_over_external_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_SERVER_TOKEN", raising=False)
    key = secrets.token_urlsafe(32)
    session = DemoSession(key, live_enabled=False)
    runner = IdleRunner()
    app = create_app(tmp_path, lambda store: runner, demo=session, recover_runs=False)
    store = app.state.store
    store.upsert(PhotoAsset(id="source", device_id="synthetic", version="v1", width=60, height=40))
    request = RunRequest(role="analyst", photo_ids=["source"], idempotency_key="external-worker")
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "external_running", "external-worker", request.model_dump_json(), "running", None, None, 123.0))
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        "external_queued", "external-worker-queued", request.model_dump_json(), "queued", None, None, 124.0))
    before = store.rows("SELECT * FROM runs ORDER BY id")
    revision = store.revision
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="source"))
    result = {"label": "관련 사진", "items": [], "groups": [], "grouping_status": "ready", "complete": True}
    result["empty_evidence"] = negative_proof(store, explore)
    store.cache_put(app.state.service.empty_cache_key(explore), result)
    bearer = {"Authorization": "Bearer " + server_token(tmp_path)}
    with TestClient(app, base_url=session.origin) as client:
        login(client, session, key)
        assert client.get("/demo/catalog").json()["live_enabled"] is False
        assert client.post("/explorations/ready", json=explore.model_dump(), headers={"Origin": session.origin}).json()["state"] == "ready"
        for headers in [bearer, {"Origin": session.origin}]:
            for method, path, payload in [
                ("POST", "/runs", {"role": "explorer", "explore": explore.model_dump()}),
                ("POST", "/runs/external_running/cancel", {}),
                ("POST", "/assets/sync", {"deleted_ids": ["source"]}),
                ("DELETE", "/assets/source", None),
                ("POST", "/assets/source/reindex", {}),
            ]:
                assert client.request(method, path, json=payload, headers=headers).status_code == 403
        assert store.rows("SELECT * FROM runs ORDER BY id") == before
        assert app.state.service.tasks == {}
    db = sqlite3.connect(tmp_path / "gallery.sqlite")
    db.row_factory = sqlite3.Row
    assert [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY id")] == before
    assert db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0] == revision
    db.close()
    assert runner.calls == 0


def test_live_cookie_can_cancel_only_its_own_demo_exploration(demo):
    client, app, session, key, runner, root = demo
    login(client, session, key)
    origin = {"Origin": session.origin}
    result = client.post("/runs", headers=origin, json={"role": "explorer", "explore": {"anchor": {"photo_id": "opaque_A"}}})
    assert result.status_code == 200
    assert client.post(f"/runs/{result.json()['id']}/cancel", headers=origin, json={}).status_code == 200
    assert client.post("/runs/external-worker/cancel", headers=origin, json={}).status_code == 401
