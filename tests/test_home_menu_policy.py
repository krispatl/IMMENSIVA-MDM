import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest


spec = importlib.util.spec_from_file_location(
    "home_menu_policy", Path(__file__).resolve().parents[1] / "monitor-tools/home-menu-policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
DEVICE = dict(label="Test headset", device_id="test-serial", ip="192.0.2.1", status="online")


@pytest.mark.parametrize("packages", ["", "package:org.immensiva.homecheck.other"])
def test_restore_skips_absent_helper_without_starting_service(packages):
    def command(*args, **kwargs):
        if args[0] == "connect":
            return "connected"
        if args[3:] == ("getprop", "ro.serialno"):
            return DEVICE["device_id"]
        if args[3:] == ("pm", "path", policy.PACKAGE):
            raise RuntimeError("")  # PICO returns exit 1 with no output for missing APKs.
        if args[3:] == ("pm", "list", "packages", policy.PACKAGE):
            return packages
        pytest.fail(f"Unexpected command: {args}")

    with patch.object(policy, "adb", side_effect=command):
        assert policy.apply(DEVICE, "restore") == (DEVICE["label"], "SKIPPED rollout helper is absent")


def test_restore_uses_installed_helper_and_returns_firmware_result():
    with patch.object(policy, "uuid4") as identifier, patch.object(policy, "adb") as adb:
        identifier.return_value.hex = "request-id"
        adb.side_effect = ["connected", DEVICE["device_id"], f"package:{policy.PACKAGE}",
                           "started", "RESULT request-id RESTORED original default"]
        assert policy.apply(DEVICE, "restore") == (DEVICE["label"], "RESTORED original default")
        assert adb.call_args_list[3].args[3:] == (
            "am", "start-foreground-service", "-n", policy.PACKAGE + "/.Check",
            "--es", "mode", "restore", "--es", "request", "request-id")


def test_adb_failure_without_output_has_an_explanation():
    with patch.object(policy.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
        with pytest.raises(RuntimeError, match="ADB command failed.*exit code 1"):
            policy.adb("connect", "192.0.2.1:5555")
