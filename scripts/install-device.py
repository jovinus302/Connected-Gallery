"""Install an APK through a base64 shell stream, verifying it before installation."""
import argparse
import base64
import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path


def install(apk: Path, adb: str, serial: str | None = None) -> None:
    payload = apk.read_bytes()
    expected = hashlib.sha256(payload).hexdigest()
    command = [adb] + (["-s", serial] if serial else [])
    # Refuse ambiguous device selection before creating a remote file.
    subprocess.run([*command, "get-state"], check=True, capture_output=True)
    remote = f"/data/local/tmp/connected-gallery-{uuid.uuid4().hex}.apk"
    try:
        subprocess.run(
            [*command, "shell", f"base64 -d > {remote}"],
            input=base64.b64encode(payload), check=True, timeout=180,
        )
        digest = subprocess.run(
            [*command, "shell", "sha256sum", remote],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.split()
        if not digest or digest[0].lower() != expected:
            raise RuntimeError("APK checksum mismatch; installation was not attempted")
        print(f"APK SHA-256 verified: {expected}", flush=True)
        result = subprocess.run(
            [*command, "shell", "pm", "install", "-r", remote],
            check=True, capture_output=True, text=True, timeout=180,
        )
        if result.stdout.strip() != "Success":
            raise RuntimeError(f"APK installation failed: {result.stdout} {result.stderr}")
        print("APK installed successfully; existing app data preserved.")
    finally:
        cleanup = subprocess.run(
            [*command, "shell", "rm", "-f", remote],
            capture_output=True, timeout=30,
        )
        if cleanup.returncode:
            print(f"Temporary APK cleanup failed: {remote}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=Path(__file__).resolve().parents[1] /
                        "android/app/build/outputs/apk/debug/app-debug.apk")
    parser.add_argument("--adb", default=shutil.which("adb") or "adb")
    parser.add_argument("--serial", help="ADB serial when more than one device is connected")
    args = parser.parse_args()
    install(args.apk, args.adb, args.serial)
