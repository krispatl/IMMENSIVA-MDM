"""Apply or restore the PICO single-press Home policy on connected headsets."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

TOOLS = Path(__file__).resolve().parent
ADB = TOOLS / "scrcpy-win64-v5.0.1" / "adb.exe"
PACKAGE = "org.immensiva.homecheck"


def adb(*args, timeout=12):
    result = subprocess.run([str(ADB), *args], capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def apply(device, mode):
    label = device["label"]
    if device["status"] != "online":
        return label, "SKIPPED offline"
    address = device["ip"] + ":5555"
    target = ("-s", address)
    try:
        adb("connect", address)
        if adb(*target, "shell", "getprop", "ro.serialno") != device["device_id"]:
            raise RuntimeError("ADB identity does not match the MDM headset")
        if mode == "lock":
            output = adb(*target, "install", "--no-incremental", "-r",
                         str(TOOLS / "home-lock.apk"), timeout=45)
            if "Success" not in output:
                raise RuntimeError(output)
        elif not adb(*target, "shell", "pm", "path", PACKAGE):
            return label, "SKIPPED rollout helper is absent"
        request = uuid4().hex
        adb(*target, "shell", "am", "start-foreground-service", "-n", PACKAGE + "/.Check",
            "--es", "mode", mode, "--es", "request", request)
        prefix = "RESULT " + request + " "
        for _ in range(16):
            logs = adb(*target, "logcat", "-d", "-s", "IMMENSIVA_HOME_CHECK:I", "*:S")
            for line in reversed(logs.splitlines()):
                if prefix in line:
                    return label, line.split(prefix, 1)[1]
            time.sleep(.5)
        return label, "FAILED firmware result unavailable"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return label, "FAILED " + str(error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("lock", "restore"))
    parser.add_argument("--device", action="append", help="Restrict to this headset label")
    parser.add_argument("--json-stdin", action="store_true", help="Read a device snapshot and return JSON results")
    args = parser.parse_args()
    if args.json_stdin:
        state = json.load(sys.stdin)
    else:
        with urlopen("http://127.0.0.1:7080/api/state", timeout=5) as response:
            state = json.load(response)
    if not state["connected"]:
        parser.error("The operator monitor has no live MDM connection.")
    devices = [d for d in state["devices"] if not args.device or d["label"] in args.device]
    if not devices:
        parser.error("No matching headsets.")
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for device, (label, result) in zip(devices, executor.map(lambda device: apply(device, args.mode), devices)):
            results.append({"device_id": device["device_id"], "label": label, "result": result})
            if not args.json_stdin:
                print(label, result, flush=True)
    if args.json_stdin:
        print(json.dumps(results))
        return 0
    return int(any(item["result"].startswith("FAILED") for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
