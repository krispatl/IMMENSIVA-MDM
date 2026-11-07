"""Start and stop only the isolated monitor's recorded process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import webbrowser

import psutil

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:7080"


def healthy():
    try:
        with urllib.request.urlopen(URL + "/health", timeout=1) as response:
            return json.load(response).get("product") == "IMMENSIVA operator monitor"
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    data = ROOT / "monitor-data"
    data.mkdir(exist_ok=True)
    record = data / "process.json"
    if args.stop:
        if record.exists():
            saved = json.loads(record.read_text())
            try:
                process = psutil.Process(saved["pid"])
                if (abs(process.create_time() - saved["created"]) < .01
                        and "immensiva_mdm.monitor" in process.cmdline()):
                    request = urllib.request.Request(
                        URL + "/api/shutdown", data=b"{}",
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(request, timeout=3):
                        pass
                    process.wait(timeout=20)
            except psutil.NoSuchProcess:
                pass
        return
    if not healthy():
        with (data / "server-output.log").open("ab") as output:
            process = subprocess.Popen(
                [str(ROOT / "runtime/python.exe"), "-m", "immensiva_mdm.monitor"],
                cwd=ROOT, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        record.write_text(json.dumps({
            "pid": process.pid, "created": psutil.Process(process.pid).create_time()
        }))
        deadline = time.monotonic() + 15
        while not healthy():
            if process.poll() is not None:
                raise RuntimeError("Monitor exited. See monitor-data/server-output.log")
            if time.monotonic() > deadline:
                raise RuntimeError("Monitor startup timed out")
            time.sleep(.2)
    if not args.no_browser:
        webbrowser.open(URL)


if __name__ == "__main__":
    main()
