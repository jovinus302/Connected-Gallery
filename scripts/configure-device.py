"""One-time USB provisioning for a debug APK; ordinary usage needs no USB."""
import os
import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
import httpx

project = Path(__file__).resolve().parents[1]
settings = project / ".runtime/pc-connection.json"
sdk = Path(os.getenv("ANDROID_HOME", str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk")))
adb = str(sdk / "platform-tools/adb.exe")
app = "com.connectedgallery.app"


def run(*args, **kwargs):
    return subprocess.run([adb, *args], check=True, **kwargs)


def verify_connection(data):
    value = json.loads(data)
    address = value["url"].rstrip("/")
    parsed = urlsplit(address)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")):
        raise ValueError("Use HTTPS or a loopback USB endpoint")
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.get(address + "/manifest", headers={"Authorization": "Bearer " + value["token"]})
        response.raise_for_status()
        if response.json().get("api_version") != 1:
            raise ValueError("Incompatible Gallery server")
    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb", action="store_true", help="Use the running local server over USB instead of a temporary HTTPS tunnel")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.usb:
        from dotenv import load_dotenv
        from connected_gallery.bootstrap.auth import server_token
        load_dotenv(project / ".env")
        data = json.dumps({"url": f"http://127.0.0.1:{args.port}",
                           "token": server_token(Path(os.getenv("CG_DATA_DIR", str(project / ".runtime"))))}).encode()
    else:
        data = settings.read_bytes()
    # Never replace the device's settings with an unverified or expired endpoint.
    parsed = verify_connection(data)
    run("get-state", stdout=subprocess.DEVNULL)
    if parsed.scheme == "http":
        port = parsed.port or 80
        run("reverse", f"tcp:{port}", f"tcp:{port}")
    run("shell", "am", "force-stop", app)
    run("shell", "run-as", app, "mkdir", "-p", "files")
    # stdin delivers the key only into app-private storage, never command arguments/logs.
    run("shell", "run-as", app, "sh", "-c", "'cat > files/server-connection.json'", input=data)
    run("shell", "am", "start", "-n", app + "/.MainActivity", stdout=subprocess.DEVNULL)
    print("Verified server connection configured" + (" over USB; keep the cable connected." if parsed.scheme == "http" else " over HTTPS."))
