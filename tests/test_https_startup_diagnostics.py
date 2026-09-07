import json
import runpy
from pathlib import Path

import httpx


probe_manifest = runpy.run_path(str(Path(__file__).parents[1] / "scripts/start-pc-server.py"))["probe_manifest"]


def test_cloudflare_failure_records_status_without_response_body(tmp_path):
    path = tmp_path / "probe.jsonl"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        530, headers={"server": "cloudflare", "cf-ray": "test-ray"},
        text="error code: 1033 private gallery metadata"))) as client:
        assert not probe_manifest(client, "https://example.test", {"Authorization": "Bearer secret"}, path)
    record = json.loads(path.read_text())
    assert record["status"] == 530
    assert record["cloudflare_error"] == "1033"
    assert "private gallery" not in path.read_text()
    assert "secret" not in path.read_text()


def test_transport_failure_records_type_and_redacts_credentials(tmp_path, capsys):
    path = tmp_path / "probe.jsonl"

    def fail(request):
        raise httpx.ConnectError("getaddrinfo failed; Bearer sensitive-token sensitive-token")

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        assert not probe_manifest(client, "https://example.test", {"Authorization": "Bearer sensitive-token"}, path)
    record = json.loads(path.read_text())
    assert record["error"] == "ConnectError"
    assert "getaddrinfo failed" in record["detail"]
    assert "sensitive-token" not in path.read_text() + capsys.readouterr().out


def test_success_does_not_log_manifest_data(tmp_path):
    path = tmp_path / "probe.jsonl"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"private": "gallery details"}))) as client:
        assert probe_manifest(client, "https://example.test", {"Authorization": "Bearer secret"}, path)
    assert json.loads(path.read_text())["status"] == 200
    assert "gallery details" not in path.read_text()
