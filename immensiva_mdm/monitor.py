"""Separate, local operator monitor. Reads the existing MDM admin feed."""
import argparse
import asyncio
import base64
from contextlib import suppress
from contextvars import ContextVar
import json
from html import escape
from ipaddress import ip_address
import math
import os
import re
from secrets import compare_digest
from urllib.parse import urlencode
from pathlib import Path
import sys
import time
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

from .catalog import PACKAGES

ROOT = Path(__file__).resolve().parent.parent
GROUP_COMMAND = ContextVar("group_command", default=False)
# Temporary hold while the PICO storage issue is investigated. Keep stop actions available.
DISABLED_ACTIONS = {
    "track": "Room positioning is temporarily unavailable.",
    "view": "Live view is temporarily unavailable.",
}


def require_action_enabled(action):
    reason = DISABLED_ACTIONS.get(action)
    if reason:
        raise web.HTTPForbidden(text=json.dumps({"error": reason}), content_type="application/json")


def decode_sample(text, run, pending):
    if "SAMPLE " in text:
        sample = json.loads(text.split("SAMPLE ", 1)[1])
        return sample if sample.get("run") == run else None
    if "PACKET " not in text:
        return None
    packet_run, sequence, index, count, chunk = text.split("PACKET ", 1)[1].strip().split(" ", 4)
    if packet_run != run:
        return None
    index, count = int(index), int(count)
    if not 0 <= index < count <= 1024:
        return None
    if pending.get("sequence") != sequence:
        pending.clear()
        pending.update(sequence=sequence, count=count, chunks={})
    if pending["count"] != count:
        return None
    pending["chunks"][index] = chunk
    if len(pending["chunks"]) != count:
        return None
    encoded = "".join(pending["chunks"][part] for part in range(count))
    pending.clear()
    sample = json.loads(base64.b64decode(encoded, validate=True))
    return sample if sample.get("run") == run else None


def equivalent_outline(first, second, tolerance=.01):
    def near(a, b):
        return math.hypot(a["x"] - b["x"], a["z"] - b["z"]) <= tolerance

    first = first[:-1] if len(first) > 3 and near(first[0], first[-1]) else first
    second = second[:-1] if len(second) > 3 and near(second[0], second[-1]) else second
    if len(first) != len(second) or not first:
        return False
    for start, point in enumerate(second):
        if near(first[0], point):
            for direction in (1, -1):
                if all(near(vertex, second[(start + direction * i) % len(second)])
                       for i, vertex in enumerate(first)):
                    return True
    return False


class Monitor:
    def __init__(self, data, adb, scrcpy, upstream):
        self.data = data
        self.adb = adb
        self.scrcpy = scrcpy
        self.upstream = upstream
        self.devices = []
        self.connected = False
        self.poses = {}
        self.tracking = {}
        self.tasks = {}
        self.locks = {}
        self.viewer = None
        self.viewer_device = None
        self.viewer_lock = asyncio.Lock()
        self.data.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data / "sessions.json"
        self.sessions = {}
        self.events = []
        self.inventory = {}
        self.displays = {}
        self.rooms = {}
        self.measured_rooms = {}
        self.foreground = {}
        self.heads_up_seen = -math.inf
        self.home_menu_lock = asyncio.Lock()
        self.home_menu_result = None
        self.suite = None
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.sessions = saved.get("sessions", {})
            self.events = saved.get("events", [])
            self.displays = saved.get("displays", {})
            self.rooms = saved.get("rooms", {})
            self.measured_rooms = saved.get("measured_rooms", {})
            for display in self.displays.values():
                display["state"] = "unknown"
        inventory = self.data / "inventory.json"
        if inventory.exists():
            self.inventory = {d["device_id"]: d for d in json.loads(inventory.read_text())}

    def save(self):
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "sessions": self.sessions, "events": self.events[-200:],
            "displays": self.displays, "rooms": self.rooms, "measured_rooms": self.measured_rooms
        }), encoding="utf-8")
        temporary.replace(self.state_path)

    def event(self, device, message, kind="activity"):
        if not GROUP_COMMAND.get():
            self.events.append(dict(at=time.time(), device=device, message=message, kind=kind))
            self.events = self.events[-200:]
        self.save()

    def device(self, device_id):
        device = next((d for d in self.devices if d["device_id"] == device_id), None)
        if not self.connected or not device or device["status"] != "online":
            raise web.HTTPConflict(text="Headset is offline or the MDM feed is disconnected.")
        return device

    async def command(self, *args, timeout=15):
        process = await asyncio.create_subprocess_exec(
            str(self.adb), *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        text = output.decode(errors="replace").strip()
        if process.returncode:
            raise RuntimeError(text[-1000:])
        return text

    async def address(self, device_id, require_online=True, timeout=15):
        if require_online:
            device = self.device(device_id)
        else:
            device = next((d for d in self.devices if d["device_id"] == device_id),
                          self.inventory.get(device_id))
            if not device:
                raise ValueError("No known address for this headset")
        address = device["ip"] + ":5555"
        await self.command("connect", address, timeout=timeout)
        serial = await self.command("-s", address, "shell", "getprop", "ro.serialno", timeout=timeout)
        if serial != device_id:
            raise RuntimeError("ADB identity does not match the selected headset.")
        return address

    async def read_display(self, address, timeout=15):
        output = await self.command("-s", address, "shell", "dumpsys", "SurfaceFlinger", timeout=timeout)
        modes = []
        physical = False
        for line in output.splitlines():
            text = line.strip()
            if re.fullmatch(r"Display [0-9]+", text):
                physical = True
            elif text.startswith("Virtual Display "):
                physical = False
            elif physical and text.startswith("powerMode="):
                modes.append(text.split("=", 1)[1])
                physical = False
        if modes and all(mode == "Off" for mode in modes):
            return "off"
        if modes and all(mode == "On" for mode in modes):
            return "on"
        return "unknown"

    async def set_display(self, device_id, on):
        desired = "on" if on else "off"
        record = dict(state="unknown", requested=desired, checked_at=0)
        self.displays[device_id] = record
        try:
            address = await self.address(device_id, require_online=not on)
            tools = ROOT / "monitor-tools"
            await self.command("-s", address, "push", str(tools / "display-control.jar"),
                               "/data/local/tmp/immensiva-display.jar")
            await self.command("-s", address, "push", str(self.scrcpy.parent / "scrcpy-server"),
                               "/data/local/tmp/immensiva-display-server.jar")
            result = await self.command(
                "-s", address, "shell",
                "CLASSPATH=/data/local/tmp/immensiva-display.jar:/data/local/tmp/immensiva-display-server.jar",
                "app_process", "/", "org.immensiva.monitorprobe.DisplayPower", desired)
            if "IMMENSIVA_DISPLAY " + desired not in result:
                raise RuntimeError("Display helper did not acknowledge the command")
            record["state"] = await self.read_display(address)
            record["checked_at"] = time.time()
            if record["state"] != desired:
                raise RuntimeError("Physical display state could not be confirmed")
            self.event(device_id, "Display restored" if on else "Blackout confirmed")
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, web.HTTPException) as error:
            record["error"] = str(error)
            self.event(device_id, ("Restore failed. " if on else "Blackout failed. ") + str(error)[:180], "problem")
            raise

    async def stop_experience(self, device_id):
        address = await self.address(device_id)
        processes = await self.command("-s", address, "shell", "ps", "-A", "-o", "NAME")
        running = {line.strip().split(":", 1)[0] for line in processes.splitlines()}
        packages = sorted(running.intersection(PACKAGES))
        for package in packages:
            await self.command("-s", address, "shell", "am", "force-stop", package)
            remaining = await self.command("-s", address, "shell", "ps", "-A", "-o", "NAME")
            names = {line.strip().split(":", 1)[0] for line in remaining.splitlines()}
            if package in names:
                raise RuntimeError("An experience process is still running after the stop command")
            session = self.sessions.get(device_id)
            if session and session["package"] == package:
                if session["status"] == "running":
                    session["elapsed"] += max(0, time.time() - session["started"])
                session["status"] = "finished"
            self.event(device_id, "Stopped " + PACKAGES[package])
        if not packages:
            self.event(device_id, "No registered experience is running")
        return packages

    async def group_action(self, action):
        on = action == "display_on"
        targets = {d["device_id"] for d in self.devices
                   if self.connected and d["status"] == "online"}
        if on:
            targets.update(self.displays)
        if not targets:
            raise ValueError("No reachable or previously controlled headsets")
        limit = asyncio.Semaphore(4)

        async def apply(device_id):
            async with limit:
                async with self.locks.setdefault(device_id, asyncio.Lock()):
                    try:
                        if action == "stop_experience":
                            stopped = await self.stop_experience(device_id)
                            return dict(device_id=device_id, ok=True, stopped=stopped)
                        await self.set_display(device_id, on)
                        return dict(device_id=device_id, ok=True)
                    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, web.HTTPException) as error:
                        if action == "stop_experience":
                            self.event(device_id, "Stop experience failed. " + str(error)[:180], "problem")
                        return dict(device_id=device_id, ok=False, error=str(error))

        results = await asyncio.gather(*(apply(device_id) for device_id in sorted(targets)))
        return dict(results=results, succeeded=sum(result["ok"] for result in results),
                    failed=sum(not result["ok"] for result in results),
                    skipped=sum(d["device_id"] not in targets for d in self.devices))

    async def refresh_displays(self):
        limit = asyncio.Semaphore(4)

        async def refresh(device_id):
            lock = self.locks.setdefault(device_id, asyncio.Lock())
            if lock.locked():
                return
            async with limit:
                async with lock:
                    record = self.displays[device_id]
                    try:
                        address = await self.address(device_id, require_online=False, timeout=3)
                        actual = await self.read_display(address, timeout=3)
                        previous = record["state"]
                        changed = record["state"] != actual
                        record["state"] = actual
                        record["checked_at"] = time.time()
                        if changed:
                            if previous in {"on", "off"} and actual in {"on", "off"}:
                                self.event(device_id, "Physical display changed to " + actual)
                            else:
                                self.save()
                    except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
                        record["state"] = "unknown"
        while True:
            await asyncio.gather(*(refresh(device_id) for device_id in list(self.displays)))
            await asyncio.sleep(5)

    async def feed(self):
        async with ClientSession(timeout=ClientTimeout(total=None, sock_connect=5)) as client:
            while True:
                try:
                    async with client.ws_connect(self.upstream + "/ws/admin", heartbeat=30) as ws:
                        self.connected = True
                        if self.suite:
                            self.suite.ws = ws
                        async for message in ws:
                            if message.type != WSMsgType.TEXT:
                                continue
                            payload = json.loads(message.data)
                            kind = payload.get("type")
                            if self.suite:
                                self.suite.receive(payload)
                            if kind == "DEVICE_LIST":
                                previous = {d["device_id"]: d["status"] for d in self.devices}
                                self.devices = payload["devices"]
                                for d in self.devices:
                                    if d["device_id"] in previous and previous[d["device_id"]] != d["status"]:
                                        self.event(d["device_id"], d["status"],
                                                   "problem" if d["status"] == "offline" else "activity")
                            elif not self.suite and kind in {"INSTALL_DEVICE_STATE", "PUSH_DEVICE_STATE"}:
                                detail = " · ".join(str(value) for value in (
                                    payload.get("apk_filename") or payload.get("dest_path"),
                                    payload.get("state"), payload.get("detail")) if value)
                                for device_id in payload.get("device_ids", []):
                                    self.event(device_id, detail,
                                               "problem" if payload.get("state") == "fail" else "activity")
                            elif not self.suite and kind in {"LAUNCH_RESULT", "INSTALL_RESULT", "PUSH_FILES_RESULT"}:
                                detail = payload.get("message") or payload.get("status") or kind
                                filename = payload.get("apk_filename") or payload.get("package_name") or ""
                                self.event(payload.get("device_id", ""), (filename + " · " + str(detail)).strip(" ·"),
                                           "problem" if "fail" in str(payload).lower() else "activity")
                except (ClientError, OSError, ValueError, asyncio.TimeoutError) as error:
                    # The existing console may restart independently.
                    if self.connected:
                        self.event("", "MDM connection lost. " + str(error)[:120], "problem")
                finally:
                    self.connected = False
                    if self.suite:
                        self.suite.ws = None
                        self.suite.interrupt("MDM disconnected before confirmation.")
                await asyncio.sleep(3)

    async def collect(self, device_id, address, run):
        process = None
        pending = {}
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.adb), "-s", address, "logcat", "-T", "1", "-v", "brief",
                "-s", "IMMENSIVA_PROBE:I", "*:S",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == "nt" else 0)
            deadline = time.monotonic() + 1810
            while time.monotonic() < deadline:
                line = await asyncio.wait_for(process.stdout.readline(), 12)
                if not line:
                    break
                text = line.decode(errors="replace")
                sample = decode_sample(text, run, pending)
                if sample is None:
                    continue
                pose = sample["pose"]["global"]
                values = {k: float(pose[k]) for k in ("x", "y", "z", "rx", "ry", "rz", "rw")}
                if not all(math.isfinite(v) for v in values.values()):
                    continue
                self.poses[device_id] = dict(
                    pose=values, map=sample["map"], boundary=sample.get("boundary", {}),
                    received=time.time())
                boundary = sample.get("boundary", {})
                points = boundary.get("points", [])
                fingerprint = sample["map"].get("md5")
                if fingerprint and boundary.get("result_code") == 0 and len(points) >= 3:
                    outline = [{"x": float(point["x"]), "z": float(point["z"])} for point in points]
                    if all(math.isfinite(value) for point in outline for value in point.values()):
                        existing = self.rooms.get(fingerprint)
                        if not existing or not equivalent_outline(existing["points"], outline):
                            self.rooms[fingerprint] = dict(
                                points=outline, name=sample["map"].get("name", "LBE room"),
                                source=device_id, captured=time.time())
                            self.save()
                self.tracking[device_id] = "Receiving · alignment unverified"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.event(device_id, "Position feed stopped. " + str(error)[:160], "problem")
        finally:
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            with suppress(Exception):
                await self.command("-s", address, "shell", "am", "stopservice",
                                   "-n", "org.immensiva.monitorprobe/.ProbeService")
            self.tracking[device_id] = "Stopped"

    async def start_tracking(self, device_id):
        require_action_enabled("track")
        address = await self.address(device_id)
        current = self.tasks.get(device_id)
        if current and not current.done():
            return
        self.tracking[device_id] = "Starting"
        apk = ROOT / "monitor-tools" / "monitor-probe.apk"
        result = await self.command("-s", address, "install", "--no-incremental", "-r", str(apk), timeout=60)
        if "Success" not in result:
            raise RuntimeError(result)
        run = uuid.uuid4().hex
        self.tasks[device_id] = asyncio.create_task(self.collect(device_id, address, run))
        try:
            await self.command("-s", address, "shell", "am", "start-foreground-service",
                               "-n", "org.immensiva.monitorprobe/.ProbeService", "--es", "run", run)
        except Exception:
            self.tasks[device_id].cancel()
            with suppress(asyncio.CancelledError):
                await self.tasks[device_id]
            raise
        self.event(device_id, "Position service started for up to 30 minutes")

    async def stop_tracking(self, device_id):
        task = self.tasks.get(device_id)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.event(device_id, "Position service stopped")

    async def view(self, device_id):
        require_action_enabled("view")
        address = await self.address(device_id)
        async with self.viewer_lock:
            if self.viewer and self.viewer.returncode is None:
                if self.viewer_device == device_id:
                    return
                self.viewer.terminate()
                await self.viewer.wait()
            output = (self.data / "viewer.log").open("ab")
            try:
                self.viewer = await asyncio.create_subprocess_exec(
                    str(self.scrcpy), "-s", address, "--no-control", "--no-audio", "--no-power-on",
                    "--max-size=1024", "--max-fps=20", "--video-bit-rate=2M",
                    "--window-title=IMMENSIVA · " + self.device(device_id)["label"],
                    stdout=output, stderr=output,
                    creationflags=0x08000000 if os.name == "nt" else 0)
            finally:
                output.close()
            self.viewer_device = device_id
            await asyncio.sleep(1)
            if self.viewer.returncode is not None:
                raise RuntimeError("Viewer exited. See monitor-data/viewer.log.")
            self.event(device_id, "Live viewer opened on this PC")

    async def cleanup(self, app):
        self.feed_task.cancel()
        self.timer_task.cancel()
        self.display_task.cancel()
        self.foreground_task.cancel()
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(self.feed_task, self.timer_task, self.display_task, self.foreground_task,
                             *self.tasks.values(), return_exceptions=True)
        if self.viewer and self.viewer.returncode is None:
            self.viewer.terminate()
            await self.viewer.wait()

    async def refresh_foreground(self):
        limit = asyncio.Semaphore(4)

        async def check(device_id):
            async with limit:
                try:
                    address = await self.address(device_id, timeout=3)
                    output = await self.command(
                        "-s", address, "shell", "dumpsys", "activity", "top-resumed", timeout=3)
                    match = re.search(r"(?m)^\s*packageName=([\w.]+)(?:\s|$)", output)
                    if match:
                        self.foreground[device_id] = dict(package=match[1], checked_at=time.time())
                        return
                except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, web.HTTPConflict):
                    pass
                self.foreground.pop(device_id, None)

        while True:
            if self.connected and time.monotonic() - self.heads_up_seen < 12:
                await asyncio.gather(*(check(d["device_id"]) for d in self.devices
                                       if d["status"] == "online"))
            await asyncio.sleep(3)

    async def set_home_menu(self, mode):
        if not self.connected or not any(d["status"] == "online" for d in self.devices):
            raise web.HTTPConflict(text="Connect a headset before changing the Home menu.")
        if self.home_menu_lock.locked():
            raise web.HTTPConflict(text="A Home menu change is already in progress.")
        async with self.home_menu_lock:
            script = ROOT / "monitor-tools/home-menu-policy.py"
            if not script.is_file() or (mode == "lock" and not script.with_name("home-lock.apk").is_file()):
                raise web.HTTPServiceUnavailable(text="The Home menu rollout helper is missing.")
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(script), mode, "--json-stdin",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            payload = json.dumps({"connected": self.connected, "devices": self.devices}).encode()
            try:
                output, errors = await process.communicate(payload)
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            if process.returncode:
                raise RuntimeError(errors.decode(errors="replace").strip() or "Home menu helper failed.")
            results = json.loads(output)
            summary = {"mode": mode, "confirmed": 0, "skipped": 0, "failed": 0, "results": results}
            for item in results:
                status = item["result"].split(" ", 1)[0]
                if status in {"LOCKED", "RESTORED", "ALREADY"}:
                    summary["confirmed"] += 1
                elif status == "SKIPPED":
                    summary["skipped"] += 1
                else:
                    summary["failed"] += 1
                self.event(item["device_id"], "Home menu · " + item["result"],
                           "problem" if status == "FAILED" else "activity")
            self.home_menu_result = summary
            return summary

    async def timers(self):
        while True:
            now = time.time()
            if self.suite:
                self.suite.expire()
            for device_id, session in self.sessions.items():
                elapsed = session["elapsed"] + max(0, now - session["started"])
                if (session["status"] == "running" and elapsed >= session["duration"]
                        and not session.get("announced")):
                    session["announced"] = True
                    self.event(device_id, PACKAGES[session["package"]] + " duration reached", "session")
            await asyncio.sleep(1)


def create_app(monitor, touch=None, touch_only=False):
    touch_port = touch.get("port", 7081) if touch else None
    @web.middleware
    async def local_requests(request, handler):
        allowed_host = (request.host == f'{touch["address"]}:{touch_port}' if touch_only else
                        request.host.split(":", 1)[0] in {"127.0.0.1", "localhost"})
        if not allowed_host:
            raise web.HTTPForbidden()
        if touch_only and request.path.startswith("/api/"):
            supplied = request.headers.get("Authorization", "").encode()
            if not compare_digest(supplied, ("Bearer " + touch["key"]).encode()):
                raise web.HTTPUnauthorized(text="Enter the venue access key.")
        if request.method == "POST":
            upload = (monitor.suite and not touch_only and request.path in {
                "/api/suite/operation/install", "/api/suite/operation/files"})
            if request.content_type != ("multipart/form-data" if upload else "application/json"):
                raise web.HTTPUnsupportedMediaType()
            if request.headers.get("Origin", "http://" + request.host) != "http://" + request.host:
                raise web.HTTPForbidden()
        return await handler(request)

    app = web.Application(middlewares=[local_requests])

    async def index(request):
        return web.FileResponse(ROOT / "immensiva_mdm/web/monitor.html",
                                headers={"Cache-Control": "no-store"})

    async def health(request):
        return web.json_response({"product": "IMMENSIVA operator monitor",
                                  "instance": os.environ.get("IMMENSIVA_SUITE_INSTANCE")})

    async def shutdown(request):
        def stop():
            raise web.GracefulExit()
        asyncio.get_running_loop().call_later(.2, stop)
        return web.json_response({"ok": True})

    async def snapshot(request):
        suite = monitor.suite
        if suite:
            monitor.heads_up_seen = time.monotonic()
        return web.json_response(dict(
            connected=monitor.connected, devices=monitor.devices,
            sessions=monitor.sessions, poses=monitor.poses, tracking=monitor.tracking,
            disabled_actions=DISABLED_ACTIONS,
            inventory=monitor.inventory, events=monitor.events,
            displays=monitor.displays,
            rooms=monitor.rooms,
            measured_rooms=monitor.measured_rooms,
            home_menu=monitor.home_menu_result, home_menu_busy=monitor.home_menu_lock.locked(),
            foreground=monitor.foreground, suite=bool(suite),
            groups=suite.groups if suite else {}, durations=suite.durations if suite else {},
            operations=suite.jobs if suite else [], mdm_url=monitor.upstream,
            touch_enabled=bool(touch), touch_port=touch_port,
            packages=PACKAGES, now=time.time()), headers={"Cache-Control": "no-store"})

    async def netsync_status(request):
        from . import netsync

        return web.json_response(await asyncio.to_thread(netsync.status),
                                 headers={"Cache-Control": "no-store"})

    async def netsync_action(request):
        import subprocess

        from .suite import json_object

        data = await json_object(request)
        action = data.get("action")
        if action not in ("start", "stop"):
            raise web.HTTPBadRequest(text="Choose Start or Stop NetSync.")
        command = [sys.executable, "-m", "immensiva_mdm.suite_launcher", "--netsync-action", action]
        try:
            result = await asyncio.to_thread(subprocess.run, command, cwd=ROOT, capture_output=True,
                                             encoding="utf-8", errors="replace", timeout=35,
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise web.HTTPServiceUnavailable(text="NetSync command failed. See suite-data/logs/netsync.log.") from None
        if result.returncode:
            raise web.HTTPConflict(text=result.stderr.strip() or "NetSync command failed.")
        return await netsync_status(request)

    async def heads_up_state(request):
        monitor.heads_up_seen = time.monotonic()
        return web.json_response(dict(
            connected=monitor.connected, devices=monitor.devices, sessions=monitor.sessions,
            displays=monitor.displays, foreground=monitor.foreground, packages=PACKAGES,
            now=time.time()), headers={"Cache-Control": "no-store"})

    async def measure_room(request):
        data = await request.json()
        fingerprint = data.get("fingerprint")
        points = data.get("points")
        if not isinstance(fingerprint, str) or fingerprint not in monitor.rooms:
            raise web.HTTPBadRequest(text="Select a room with a PICO boundary first.")
        if points is None:
            monitor.measured_rooms.pop(fingerprint, None)
        else:
            try:
                if not isinstance(points, list) or not 3 <= len(points) <= 256:
                    raise ValueError
                outline = [{axis: float(point[axis]) for axis in ("x", "z")} for point in points]
                if not all(math.isfinite(value) and abs(value) <= 10000
                           for point in outline for value in point.values()):
                    raise ValueError
                area = sum(a["x"] * b["z"] - b["x"] * a["z"]
                           for a, b in zip(outline, outline[1:] + outline[:1]))
                if len({(point["x"], point["z"]) for point in outline}) != len(outline) or abs(area) < .02:
                    raise ValueError
            except (TypeError, KeyError, ValueError, OverflowError):
                raise web.HTTPBadRequest(text="Capture at least three distinct corners in perimeter order.")
            monitor.measured_rooms[fingerprint] = outline
        monitor.save()
        return web.json_response({"ok": True})

    async def heads_up(request):
        return web.FileResponse(ROOT / "immensiva_mdm/web/heads-up.html",
                                headers={"Cache-Control": "no-store"})

    async def touch_setup(request):
        if not touch:
            return web.Response(text="Venue Wi-Fi is off. Stop the suite, run Configure Venue Wi-Fi.cmd, then start the suite.")
        url = f'http://{touch["address"]}:{touch_port}/'
        firewall = "Allow Venue Suite on Wi-Fi.cmd" if monitor.suite else "Enable Venue Wi-Fi.cmd"
        invite = url + "#" + urlencode({"key": touch["key"]})
        try:
            import qrcode
            from qrcode.image.svg import SvgPathFillImage
        except ImportError:
            qr = '<p>Open the venue link or use manual entry below.</p>'
        else:
            svg = qrcode.make(invite, image_factory=SvgPathFillImage).to_string(encoding="unicode")
            qr = f'<div class="qr" role="img" aria-label="Venue pairing QR code">{svg}</div>'
        return web.Response(
            content_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            text=(
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>Phone &amp; tablet · IMMENSIVA</title>'
                '<link rel="stylesheet" href="/monitor-assets/heads-up.css">'
                '<main class="pairing-page"><p class="eyebrow">IMMENSIVA · VENUE CONTROLS</p>'
                '<h1>Scan to connect</h1><p>Join venue Wi-Fi and scan with your phone or tablet camera.</p>'
                f'{qr}<p><a href="{escape(invite)}">Open venue controls</a></p>'
                '<details><summary>Enter manually</summary>'
                f'<p>Address <code>{escape(url)}</code></p>'
                f'<p>Access key <code>{escape(touch["key"])}</code></p></details>'
                f'<p class="pairing-note">First time on this PC? Right-click <strong>{firewall}</strong> '
                'in the package folder and choose <strong>Run as administrator</strong>.</p>'
                '<p><a href="/">Back to Live Ops</a></p></main></html>'
            ),
        )

    async def touch_view(request):
        return web.FileResponse(ROOT / "immensiva_mdm/web/touch.html",
                                headers={"Cache-Control": "no-store"})

    async def action(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        name = data.get("action")
        if touch_only and name not in ("display_off", "display_on", "stop_experience"):
            raise web.HTTPForbidden()
        device_id = data.get("device_id")
        if not isinstance(device_id, str):
            raise web.HTTPBadRequest()
        if (not any(d["device_id"] == device_id for d in monitor.devices)
                and not (data.get("action") == "display_on" and device_id in monitor.inventory)):
            raise web.HTTPNotFound(text="Unknown headset")
        lock = monitor.locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            try:
                if name in {"display_off", "display_on"}:
                    await monitor.set_display(device_id, on=name == "display_on")
                elif name == "stop_experience":
                    await monitor.stop_experience(device_id)
                elif name == "track":
                    await monitor.start_tracking(device_id)
                elif name == "stop_tracking":
                    await monitor.stop_tracking(device_id)
                elif name == "view":
                    await monitor.view(device_id)
                elif name == "start":
                    monitor.device(device_id)
                    package = data.get("package")
                    if not isinstance(package, str) or package not in PACKAGES:
                        raise ValueError("Choose a registered experience.")
                    default = monitor.suite.durations.get(package, 0) if monitor.suite else 0
                    try:
                        minutes = float(data.get("minutes", default))
                    except (TypeError, ValueError):
                        minutes = 0
                    if not math.isfinite(minutes) or not 0 < minutes <= 240:
                        raise ValueError("Choose an experience and a duration between 0 and 240 minutes.")
                    monitor.sessions[device_id] = dict(
                        package=package, duration=minutes * 60, elapsed=0,
                        started=time.time(), status="running")
                    monitor.event(device_id, PACKAGES[package] + " operator timer started", "session")
                elif name in {"pause", "resume", "finish", "reset"}:
                    session = monitor.sessions.get(device_id)
                    if not session:
                        raise ValueError("No session timer for this headset")
                    if name == "pause" and session["status"] != "running":
                        raise ValueError("Only a running timer can be paused")
                    if name == "resume" and session["status"] != "paused":
                        raise ValueError("Only a paused timer can be resumed")
                    now = time.time()
                    if session["status"] == "running":
                        session["elapsed"] += max(0, now - session["started"])
                    session["started"] = now
                    session["status"] = {"pause": "paused", "resume": "running",
                                         "finish": "finished", "reset": "ready"}[name]
                    if name == "reset":
                        del monitor.sessions[device_id]
                    monitor.event(device_id, "Operator timer " + (
                        "reset" if name == "reset" else session["status"]), "session")
                else:
                    raise ValueError("Unknown action")
            except (ValueError, RuntimeError, OSError, asyncio.TimeoutError) as error:
                if name not in {"display_off", "display_on"}:
                    monitor.event(device_id, str(error)[:200], "problem")
                return web.json_response({"error": str(error)}, status=400)
        return web.json_response({"ok": True})

    async def fleet_action(action, title):
        token = GROUP_COMMAND.set(bool(monitor.suite))
        try:
            result = await monitor.group_action(action)
        finally:
            GROUP_COMMAND.reset(token)
        if monitor.suite:
            items = [dict(device_id=item["device_id"], status="Confirmed" if item["ok"] else "Failed",
                          detail=(", ".join(PACKAGES[p] for p in item["stopped"]) or "No registered experience running")
                          if "stopped" in item else item.get("error", "")) for item in result["results"]]
            handled = {item["device_id"] for item in items}
            items.extend(dict(device_id=device["device_id"], status="Skipped", detail="Offline")
                         for device in monitor.devices if device["device_id"] not in handled)
            monitor.suite.record_fleet(title, items)
        return web.json_response(result)

    async def display_group(request):
        data = await request.json()
        if not isinstance(data, dict) or data.get("action") not in ("off", "on"):
            raise web.HTTPBadRequest(text="Expected off or on")
        try:
            return await fleet_action("display_" + data["action"],
                                      "Restore fleet displays" if data["action"] == "on" else "Blackout fleet")
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)

    async def stop_group(request):
        try:
            return await fleet_action("stop_experience", "Stop fleet experiences")
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)

    async def home_menu_group(request):
        try:
            data = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid Home menu request.") from None
        if not isinstance(data, dict) or data.get("mode") not in ("lock", "restore"):
            raise web.HTTPBadRequest(text="Choose Enable or Disable Home menu.")
        token = GROUP_COMMAND.set(bool(monitor.suite))
        try:
            result = await monitor.set_home_menu(data["mode"])
            if monitor.suite:
                outcomes = {"LOCKED": "Confirmed", "RESTORED": "Confirmed", "ALREADY": "Confirmed",
                            "SKIPPED": "Skipped", "FAILED": "Failed"}
                monitor.suite.record_fleet("Enable fleet Home menu" if data["mode"] == "restore" else "Disable fleet Home menu", [
                    dict(device_id=item["device_id"], status=outcomes.get(item["result"].split()[0], "Unverified"),
                         detail=item["result"]) for item in result["results"]])
            return web.json_response(result)
        except (OSError, RuntimeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=500)
        finally:
            GROUP_COMMAND.reset(token)

    async def assets(request):
        name = request.match_info["name"]
        if name not in {"monitor.css", "monitor.js", "heads-up.css", "heads-up.js", "fleet-status.js", "suite.js"}:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / "immensiva_mdm/web" / name,
                                headers={"Cache-Control": "no-store"})

    async def startup(app):
        monitor.feed_task = asyncio.create_task(monitor.feed())
        monitor.timer_task = asyncio.create_task(monitor.timers())
        monitor.display_task = asyncio.create_task(monitor.refresh_displays())
        monitor.foreground_task = asyncio.create_task(monitor.refresh_foreground())

    if touch_only:
        app.router.add_get("/", touch_view)
    else:
        app.router.add_get("/", index)
        app.router.add_get("/heads-up", heads_up)
        app.router.add_get("/touch-setup", touch_setup)
        app.router.add_get("/health", health)
        app.router.add_post("/api/shutdown", shutdown)
        app.router.add_get("/api/state", snapshot)
        app.router.add_post("/api/room-outline", measure_room)
        app.router.add_post("/api/home-menu", home_menu_group)
        if monitor.suite:
            app.router.add_get("/api/suite/netsync", netsync_status)
            app.router.add_post("/api/suite/netsync", netsync_action)
            app.router.add_post("/api/suite/operation/{kind}", monitor.suite.operation)
            app.router.add_post("/api/suite/durations", monitor.suite.duration_settings)
            app.router.add_post("/api/suite/group", monitor.suite.room_group)
        app.on_startup.append(startup)
        app.on_cleanup.append(monitor.cleanup)
        if touch:
            async def touch_listener(_app):
                runner = web.AppRunner(create_app(monitor, touch, touch_only=True))
                await runner.setup()
                try:
                    await web.TCPSite(runner, touch["address"], touch_port).start()
                    yield
                finally:
                    await runner.cleanup()
            app.cleanup_ctx.append(touch_listener)
    app.router.add_get("/api/heads-up", heads_up_state)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/display-group", display_group)
    app.router.add_post("/api/stop-group", stop_group)
    app.router.add_get("/monitor-assets/{name}", assets)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7080)
    parser.add_argument("--upstream", default="http://127.0.0.1:7070")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "monitor-data")
    parser.add_argument("--suite", action="store_true")
    args = parser.parse_args()
    tools = ROOT / "monitor-tools"
    scrcpy = tools / "scrcpy-win64-v5.0.1"
    monitor = Monitor(args.data_dir, scrcpy / "adb.exe",
                      scrcpy / "scrcpy.exe", args.upstream.rstrip("/"))
    if args.suite:
        from .suite import Suite
        monitor.suite = Suite(monitor, PACKAGES)
    config = monitor.data / "touch.json"
    touch = json.loads(config.read_text(encoding="utf-8")) if config.exists() else None
    if touch:
        address = ip_address(touch["address"])
        if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError("Venue touch requires a private LAN IPv4 address.")
        if not isinstance(touch["key"], str) or len(touch["key"]) < 16:
            raise ValueError("Venue touch requires an access key of at least 16 characters.")
    web.run_app(create_app(monitor, touch), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
