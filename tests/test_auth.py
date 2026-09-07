import pytest
from fastapi.testclient import TestClient
from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.auth import server_token


class IdleRunner:
    async def execute(self, rid, request):
        return {}


def test_credentials_survive_restart_and_reject_weak_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_SERVER_TOKEN", raising=False)
    first = server_token(tmp_path)
    assert len(first) >= 32
    assert server_token(tmp_path) == first
    monkeypatch.setenv("CG_SERVER_TOKEN", "short")
    with pytest.raises(ValueError):
        server_token(tmp_path)


def test_all_routes_require_token_before_read_or_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("CG_SERVER_TOKEN", "test-credential-" + "a" * 32)
    app = create_app(tmp_path, lambda store: IdleRunner())
    with TestClient(app) as client:
        for method, path in [("GET", "/health"), ("GET", "/assets"),
                             ("GET", "/assets/private/preview"), ("GET", "/runs/private/events"),
                             ("GET", "/docs"), ("POST", "/assets/sync"),
                             ("PUT", "/assets/private/preview"), ("POST", "/runs"),
                             ("DELETE", "/assets/private")]:
            for headers in ({}, {"Authorization": "Bearer wrong"},
                            {"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "localhost"}):
                response = client.request(method, path, headers=headers)
                assert response.status_code == 401
                assert response.headers["Cache-Control"] == "no-store"
        assert app.state.store.photos() == []
        headers = {"Authorization": "Bearer " + server_token(tmp_path)}
        response = client.get("/manifest", headers=headers)
        assert response.status_code == 200
        assert response.json()["api_version"] == 1
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post("/assets/sync", headers=headers, json={"assets": []}).status_code == 200
