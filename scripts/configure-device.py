"""One-time USB provisioning for a debug APK; ordinary usage needs no USB."""
import os
import subprocess
from pathlib import Path

project = Path(__file__).resolve().parents[1]
settings = project / ".runtime/pc-connection.json"
sdk = Path(os.getenv("ANDROID_HOME", str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk")))
adb = str(sdk / "platform-tools/adb.exe")
app = "com.connectedgallery.app"


def run(*args, **kwargs):
    return subprocess.run([adb, *args], check=True, **kwargs)


if __name__ == "__main__":
    data = settings.read_bytes()
    run("shell", "am", "force-stop", app)
    run("shell", "run-as", app, "mkdir", "-p", "files")
    # stdin delivers the key only into app-private storage, never command arguments/logs.
    run("shell", "run-as", app, "sh", "-c", "'cat > files/server-connection.json'", input=data)
    subprocess.run([adb, "reverse", "--remove", "tcp:8765"], capture_output=True)
    run("shell", "am", "start", "-n", app + "/.MainActivity", stdout=subprocess.DEVNULL)
    print("HTTPS connection configured. USB forwarding removed.")
