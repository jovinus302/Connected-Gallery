"""Start an authenticated PC server and an MVP HTTPS tunnel, with private logs."""
import json
import os
import re
import subprocess
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv
from connected_gallery.bootstrap.auth import server_token

project = Path(__file__).resolve().parents[1]
runtime = project / ".runtime"
network = runtime / "network"
connection_file = runtime / "pc-connection.json"


def main():
    os.chdir(project)
    load_dotenv(project / ".env")
    network.mkdir(parents=True, exist_ok=True)
    binary = runtime / "bin/cloudflared.exe"
    if not binary.exists():
        raise SystemExit("Install cloudflared from the official Cloudflare download into .runtime/bin/cloudflared.exe")
    token = server_token(Path(os.getenv("CG_DATA_DIR", ".runtime")))
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
        # Reuse only when both the private origin and public authenticated endpoint work.
        try:
            response = client.get("http://127.0.0.1:8765/health", headers=headers)
        except httpx.TransportError:
            response = None
        if response is not None and response.status_code != 200:
            raise SystemExit("Port 8765 is occupied by another or outdated server. Stop that server before starting this one.")
        if response is None:
            env = os.environ.copy()
            cuda = runtime / "torch-cuda"
            if (cuda / "torch/__init__.py").exists():
                env["PYTHONPATH"] = str(cuda) + os.pathsep + env.get("PYTHONPATH", "")
            with (network / "server.log").open("ab") as log:
                process = subprocess.Popen([str(project / ".venv/Scripts/python.exe"), "-m", "uvicorn",
                    "connected_gallery.bootstrap.api:create_app", "--factory", "--host", "127.0.0.1",
                    "--port", "8765", "--no-access-log"], cwd=project, env=env,
                    stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            (network / "server-process.json").write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
            for _ in range(45):
                if process.poll() is not None:
                    raise SystemExit("Server stopped; inspect .runtime/network/server.log")
                try:
                    if client.get("http://127.0.0.1:8765/health", headers=headers).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(1)
            else:
                raise SystemExit("Server startup timed out; inspect .runtime/network/server.log")
        if client.get("http://127.0.0.1:8765/assets").status_code != 401:
            raise SystemExit("Origin authentication is not enabled; refusing to publish")
        if connection_file.exists():
            previous = json.loads(connection_file.read_text(encoding="utf-8"))
            try:
                if (previous["token"] == token and
                    client.get(previous["url"] + "/manifest", headers=headers).status_code == 200 and
                    client.get(previous["url"] + "/assets").status_code == 401):
                    print("PC server ready: " + previous["url"])
                    print("Private connection settings: " + str(connection_file))
                    return
            except httpx.TransportError:
                pass
        stamp = str(time.time_ns())
        log_path = network / ("tunnel-" + stamp + ".log")
        with log_path.open("wb") as log:
            tunnel = subprocess.Popen([str(binary), "tunnel", "--url", "http://127.0.0.1:8765",
                "--no-autoupdate"], cwd=project,
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        (network / "tunnel-process.json").write_text(json.dumps({"pid": tunnel.pid, "log": str(log_path)}), encoding="utf-8")
        # New hostnames can take several minutes to propagate through local DNS.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if tunnel.poll() is not None:
                raise SystemExit("Tunnel stopped; inspect " + str(log_path))
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", log_path.read_text(encoding="utf-8", errors="replace"))
            if match:
                url = match.group()
                try:
                    if client.get(url + "/manifest", headers=headers).status_code == 200:
                        if client.get(url + "/assets").status_code != 401:
                            tunnel.terminate()
                            raise SystemExit("Public authentication check failed")
                        connection_file.write_text(json.dumps({"url": url, "token": token}), encoding="utf-8")
                        print("PC server ready: " + url)
                        print("Private connection settings: " + str(connection_file))
                        print("Keep the PC awake. A new tunnel can change this temporary URL.")
                        return
                except httpx.TransportError:
                    pass
            time.sleep(2)
        tunnel.terminate()
        raise SystemExit("Tunnel startup timed out; inspect " + str(log_path))


if __name__ == "__main__":
    main()
