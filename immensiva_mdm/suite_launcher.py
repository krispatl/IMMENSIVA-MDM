"""Start the isolated Venue Suite and manage only its own child processes."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import webbrowser

import psutil

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "suite-data"
PORTS = {"mdm": 17080, "discovery": 17081, "monitor": 17082, "touch": 17083}


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def owned_process(record):
    try:
        process = psutil.Process(record["pid"])
        if (abs(process.create_time() - record["created"]) < .01
                and process.cmdline() == record["command"]
                and Path(process.cwd()).resolve() == ROOT):
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def stop(records):
    for record in reversed(records):
        process = owned_process(record)
        if process:
            try:
                if record["port"] == PORTS["monitor"] and healthy(record):
                    request = Request(f'http://127.0.0.1:{record["port"]}/api/shutdown', data=b"{}",
                                      headers={"Content-Type": "application/json"})
                    try:
                        with urlopen(request, timeout=3):
                            pass
                        process.wait(timeout=10)
                        continue
                    except (OSError, psutil.TimeoutExpired):
                        pass
                process.terminate()
                process.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass


def check_ports(touch):
    listeners = [("MDM", "0.0.0.0", PORTS["mdm"], socket.SOCK_STREAM),
                 ("discovery", "0.0.0.0", PORTS["discovery"], socket.SOCK_DGRAM),
                 ("Live Ops", "127.0.0.1", PORTS["monitor"], socket.SOCK_STREAM)]
    if touch:
        listeners.append(("venue Wi-Fi", touch["address"], PORTS["touch"], socket.SOCK_STREAM))
    for name, address, port, protocol in listeners:
        try:
            with socket.socket(socket.AF_INET, protocol) as listener:
                if os.name == "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((address, port))
        except OSError as error:
            raise RuntimeError(f"{name} cannot bind {address}:{port}. Check the address or port conflict.") from error


def healthy(record):
    if not owned_process(record):
        return False
    try:
        with urlopen(f'http://127.0.0.1:{record["port"]}/health', timeout=1) as response:
            return json.load(response).get("instance") == record["instance"]
    except (OSError, ValueError):
        return False


def configure_touch(address, path):
    from ipaddress import ip_address

    ip = ip_address(address)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_link_local:
        raise ValueError("Enter the venue PC's private Wi-Fi IPv4 address.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((address, 0))
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    key = previous.get("key") if previous.get("address") == address else secrets.token_urlsafe(24)
    write_json(path, {"address": address, "key": key, "port": PORTS["touch"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--enable-touch", metavar="IPV4")
    parser.add_argument("--configure-touch", action="store_true")
    parser.add_argument("--disable-touch", action="store_true")
    parser.add_argument("--import-mdm", type=Path, metavar="REGISTRY_JSON")
    parser.add_argument("--import-outlines", type=Path, metavar="SESSIONS_JSON")
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    # Lock is released by the OS even if this launcher exits unexpectedly.
    import msvcrt
    with (DATA / "launcher.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        run(args)


def run(args):
    record_file = DATA / "processes.json"
    records = json.loads(record_file.read_text(encoding="utf-8")) if record_file.exists() else []
    if args.stop:
        stop(records)
        record_file.unlink(missing_ok=True)
        return

    monitor_data = DATA / "live-ops"
    monitor_data.mkdir(exist_ok=True)
    touch_file = monitor_data / "touch.json"
    if args.configure_touch:
        args.enable_touch = input("Enter the venue PC Wi-Fi IPv4 address: ").strip()
        if not args.enable_touch:
            raise ValueError("A Wi-Fi IPv4 address is required.")
    if args.enable_touch or args.disable_touch or args.import_mdm or args.import_outlines:
        if any(owned_process(record) for record in records):
            raise RuntimeError("Stop Venue Suite before changing setup or importing data.")
        if args.enable_touch:
            configure_touch(args.enable_touch, touch_file)
        if args.disable_touch:
            touch_file.unlink(missing_ok=True)
        if args.import_mdm or args.import_outlines:
            from .suite_import import import_setup
            import_setup(DATA, args.import_mdm, args.import_outlines)
        return

    if len(records) == 2 and all(healthy(record) for record in records):
        if not args.no_browser:
            webbrowser.open(f'http://127.0.0.1:{PORTS["monitor"]}/')
        return
    stop(records)
    record_file.unlink(missing_ok=True)
    touch = json.loads(touch_file.read_text(encoding="utf-8")) if touch_file.exists() else None
    check_ports(touch)
    logs = DATA / "logs"
    logs.mkdir(exist_ok=True)
    instance = secrets.token_hex(16)
    env = dict(os.environ, IMMENSIVA_SUITE_INSTANCE=instance, PYTHONUTF8="1",
               MDM_DISCOVERY_PORT=str(PORTS["discovery"]))
    python = str(ROOT / "runtime/python.exe")
    services = [
        ("mdm", "immensiva_mdm.server", ["--port", str(PORTS["mdm"]), "--data-dir", str(DATA / "mdm")]),
        ("monitor", "immensiva_mdm.monitor", ["--port", str(PORTS["monitor"]), "--data-dir", str(monitor_data),
                                             "--upstream", f'http://127.0.0.1:{PORTS["mdm"]}', "--suite"]),
    ]
    records = []
    try:
        for name, module, arguments in services:
            command = [python, "-m", module, *arguments]
            logfile = logs / (name + ".log")
            with logfile.open("ab") as output:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=output,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
            record = dict(pid=process.pid, created=psutil.Process(process.pid).create_time(),
                          command=command, port=PORTS[name], instance=instance)
            records.append(record)
            write_json(record_file, records)
            deadline = time.monotonic() + 20
            while not healthy(record):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"{name.upper()} failed to start. See {logfile}")
                time.sleep(.2)
    except BaseException:
        stop(records)
        record_file.unlink(missing_ok=True)
        raise
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{PORTS["monitor"]}/')


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, psutil.Error) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None
