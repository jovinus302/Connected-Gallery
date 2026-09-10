import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

spec = importlib.util.spec_from_file_location("device_configuration", Path(__file__).resolve().parents[1] / "scripts/configure-device.py")
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)


@pytest.mark.parametrize("status,version,valid", [(200, 1, True), (401, 1, False), (200, 2, False), (503, 1, False)])
def test_configuration_checks_authenticated_manifest(status, version, valid):
    def respond(request):
        assert request.headers["Authorization"] == "Bearer " + "x" * 32
        assert request.url.path == "/manifest"
        return httpx.Response(status, json={"api_version": version})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with patch.object(configuration.httpx, "Client", return_value=client):
            data = json.dumps({"url": "http://127.0.0.1:8765", "token": "x" * 32})
            if valid:
                assert configuration.verify_connection(data).port == 8765
            else:
                with pytest.raises((httpx.HTTPStatusError, ValueError)):
                    configuration.verify_connection(data)


def test_configuration_rejects_remote_plaintext():
    with pytest.raises(ValueError):
        configuration.verify_connection(json.dumps({"url": "http://example.com", "token": "x" * 32}))
