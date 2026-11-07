"""Run the bundled STYLY NetSync server alongside the Venue Suite."""
import importlib.metadata
import json
import os
import socket
import subprocess
import time
from urllib.request import urlopen

import psutil

from .suite_launcher import DATA, ROOT, check_listeners, owned_process, stop, write_json

DEFAULT_PORTS = {"control": 5555, "pub": 5556, "transform": 5557, "rest-api": 8800, "server-discovery": 49999}
RECORD = DATA / "netsync-process.json"
LOG = DATA / "logs/netsync.log"


def ports():
    config = DATA / "netsync-ports.json"
    overrides = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    if not isinstance(overrides, dict) or overrides.keys() - DEFAULT_PORTS.keys():
        raise ValueError("Invalid NetSync ports file. Check suite-data/netsync-ports.json.")
    settings = DEFAULT_PORTS | overrides
    if (any(type(port) is not int or not 1024 <= port <= 65535 for port in settings.values())
            or len(set(settings.values())) != len(settings)):
        raise ValueError("NetSync ports must be distinct numbers between 1024 and 65535.")
    return settings


def record():
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else None


def process_ready(process, settings):
    try:
        sockets = process.net_connections(kind="inet")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    tcp = {item.laddr.port for item in sockets if item.status == psutil.CONN_LISTEN}
    udp = {item.laddr.port for item in sockets if item.type == socket.SOCK_DGRAM and item.laddr}
    discovery = settings["server-discovery"]
    return set(settings.values()) <= tcp and discovery in udp and rest_ready(settings)


def rest_ready(settings, identify=False):
    path = "/openapi.json" if identify else "/"
    try:
        with urlopen(f'http://127.0.0.1:{settings["rest-api"]}{path}', timeout=.6) as response:
            info = json.loads(response.read(256 * 1024))
        if not isinstance(info, dict):
            return False
        if identify:
            metadata = info.get("info")
            return isinstance(metadata, dict) and metadata.get("title") == "NetSync REST Bridge"
        return info.get("status") == "ok"
    except (OSError, ValueError):
        return False


def existing_server(settings):
    # REST alone is insufficient: require the same process to own the NetSync transports.
    expected = {settings[key] for key in ("rest-api", "control", "pub", "transform")}
    if not rest_ready(settings, identify=True):
        return False
    listeners = psutil.net_connections(kind="tcp4")
    rest_owners = {conn.pid for conn in listeners if conn.status == psutil.CONN_LISTEN
                   and conn.laddr.port == settings["rest-api"] and conn.laddr.ip in {"127.0.0.1", "0.0.0.0"}}
    return any(pid is not None and expected <= {conn.laddr.port for conn in listeners
               if conn.pid == pid and conn.status == psutil.CONN_LISTEN} for pid in rest_owners)


def status():
    result = {"state": "offline", "version": None, "ports": {}, "log": "suite-data/logs/netsync.log"}
    try:
        settings = ports()
        result["ports"] = settings
        try:
            result["version"] = importlib.metadata.version("styly-netsync-server")
        except importlib.metadata.PackageNotFoundError:
            pass
        saved = record()
        process = owned_process(saved) if saved else None
        if process:
            ready = process_ready(process, settings)
            return result | {"state": "running" if ready else "unresponsive", "managed": True}
        if existing_server(settings):
            return result | {"state": "external"}
        check_ports(settings)
    except (ValueError, RuntimeError, OSError, psutil.Error) as error:
        return result | {"state": "blocked", "detail": str(error)}
    if result["version"] is None:
        return result | {"state": "missing", "detail": "Use the portable Venue Suite package to start NetSync."}
    if saved:
        return result | {"state": "offline", "detail": "NetSync exited. See suite-data/logs/netsync.log."}
    return result


def check_ports(settings):
    listeners = [(f"NetSync {name}", "0.0.0.0", port, socket.SOCK_STREAM) for name, port in settings.items()]
    listeners.append(("NetSync discovery (UDP)", "0.0.0.0", settings["server-discovery"], socket.SOCK_DGRAM))
    check_listeners(listeners)


def start():
    current = status()
    if current["state"] in {"external", "running"}:
        return
    if current["state"] != "offline":
        raise RuntimeError(current.get("detail", "NetSync is unresponsive. Stop it and start it again."))
    settings = current["ports"]
    check_ports(settings)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    command = [str(ROOT / "runtime/python.exe"), "-m", "styly_netsync"]
    for name, port in settings.items():
        command.extend(("--" + name + "-port", str(port)))
    with LOG.open("ab") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                                   stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        created = psutil.Process(process.pid).create_time()
    except psutil.NoSuchProcess:
        raise RuntimeError("NetSync exited during startup. See suite-data/logs/netsync.log.") from None
    saved = dict(pid=process.pid, created=created, command=command, port=settings["rest-api"])
    try:
        write_json(RECORD, saved)
        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            owner = owned_process(saved)
            if owner and process_ready(owner, settings):
                return
            time.sleep(.2)
        raise RuntimeError("NetSync did not start. See suite-data/logs/netsync.log.")
    except BaseException:
        stop([saved])
        raise


def stop_managed():
    saved = record()
    if saved:
        stop([saved])
        RECORD.unlink(missing_ok=True)
