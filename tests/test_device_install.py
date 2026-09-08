import base64
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "device_install", Path(__file__).resolve().parents[1] / "scripts/install-device.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DeviceInstallTest(unittest.TestCase):
    def exercise(self, mismatch=False, transfer_failure=False, install_failure=False):
        calls = []
        payload = b"APK\x00\xff\r\n"

        def run(command, **kwargs):
            calls.append(command)
            if "input" in kwargs:
                self.assertEqual(base64.b64decode(kwargs["input"]), payload)
                if transfer_failure:
                    raise subprocess.CalledProcessError(1, command)
            output = ""
            if "sha256sum" in command:
                output = ("0" * 64 if mismatch else hashlib.sha256(payload).hexdigest()) + "  app.apk"
            if "install" in command:
                output = "Failure [INSTALL_FAILED_TEST]" if install_failure else "Success\n"
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "app.apk"
            apk.write_bytes(payload)
            with patch.object(installer.subprocess, "run", side_effect=run):
                if mismatch or transfer_failure or install_failure:
                    with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                        installer.install(apk, "adb", "emulator-5554")
                else:
                    installer.install(apk, "adb", "emulator-5554")
        self.assertTrue(all(command[:3] == ["adb", "-s", "emulator-5554"] for command in calls))
        self.assertIn("rm", calls[-1])
        self.assertEqual(any("install" in command for command in calls), not (mismatch or transfer_failure))

    def test_verified_binary_reaches_install(self):
        self.exercise()

    def test_mismatch_prevents_install(self):
        self.exercise(mismatch=True)

    def test_transfer_failure_prevents_install(self):
        self.exercise(transfer_failure=True)

    def test_pm_failure_is_not_reported_as_success(self):
        self.exercise(install_failure=True)
