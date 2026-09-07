"""Local ports share a browser cookie jar but must keep separate demo sessions."""
from contextlib import ExitStack
import secrets

from fastapi.testclient import TestClient

from connected_gallery.bootstrap.api import create_app
from connected_gallery.bootstrap.demo import DemoSession
from connected_gallery.domain.models import PhotoAsset


class NoExecution:
    async def execute(self, *args):
        raise AssertionError("Session isolation must not run a model")


def test_two_demo_ports_share_cookie_jar_without_logging_each_other_out(tmp_path, monkeypatch):
    monkeypatch.delenv("CG_SERVER_TOKEN", raising=False)
    with ExitStack() as stack:
        clients, sessions = [], []
        for port in (8879, 8880):
            key = secrets.token_urlsafe(32)
            session = DemoSession(key, port, live_enabled=False)
            app = create_app(tmp_path / str(port), lambda store: NoExecution(), demo=session, recover_runs=False)
            app.state.store.upsert(PhotoAsset(id=f"photo_{port}", device_id="synthetic-demo", version="v1", width=40, height=30))
            client = stack.enter_context(TestClient(app, base_url=session.origin))
            assert client.post("/demo/session", json={"key": key}, headers={"Origin": session.origin}).status_code == 200
            clients.append(client)
            sessions.append(session)

        jar = {}
        for client in clients:
            jar.update(dict(client.cookies.items()))
        for client in clients:
            for name, value in jar.items():
                client.cookies.set(name, value, domain="127.0.0.1", path="/")
        for client, session in zip(clients, sessions):
            response = client.get("/demo/catalog")
            assert response.status_code == 200
            assert response.json()["assets"][0]["id"] == "photo_" + session.host.split(":")[-1]

        first, second = sessions
        assert clients[0].get("/demo/catalog", headers={"Cookie": f"{second.cookie_name}={second.session}"}).status_code == 401
        assert clients[1].post("/demo/logout", headers={"Origin": second.origin}).status_code == 200
        assert clients[1].get("/demo/catalog").status_code == 401
        assert clients[0].get("/demo/catalog").status_code == 200
