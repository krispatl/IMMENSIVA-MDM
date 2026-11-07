"""Desktop preparation commands and their operator-visible results."""
import asyncio
from ipaddress import ip_address
import json
import math
import os
import socket
import time
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from yarl import URL

PENDING = {"Dispatched", "Queued", "Uploading", "Transferring", "Installing", "Applying"}
OPERATIONS = {
    "launch": ("Open app", "LAUNCH_APP", "LAUNCH_SENT", "LAUNCH_RESULT", "package_name"),
    "install": ("Install APK", "INSTALL_APK", "INSTALL_SENT", "INSTALL_RESULT", "apk_filename"),
    "files": ("Send files", "PUSH_FILES", "PUSH_FILES_SENT", "PUSH_FILES_RESULT", "dest_path"),
}


def download_origin(devices, upstream):
    addresses = set()
    for device in devices:
        try:
            destination = ip_address(device["ip"])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                if destination.version != 4 or destination.is_loopback:
                    raise ValueError("Headset address is not on the venue network")
                route.connect((str(destination), 9))
                addresses.add(route.getsockname()[0])
        except (OSError, ValueError, KeyError):
            raise web.HTTPBadRequest(text="Check the selected headsets' LAN addresses before transferring files.") from None
    if len(addresses) != 1:
        raise web.HTTPBadRequest(text="Select headsets on one venue network for this transfer.")
    address = ip_address(addresses.pop())
    if address.is_loopback or address.is_unspecified or address.is_link_local:
        raise web.HTTPBadRequest(text="No usable venue download address. Check the PC network connection.")
    return URL(upstream).with_host(str(address)).origin()


class Suite:
    def __init__(self, monitor, packages):
        self.monitor = monitor
        self.packages = packages
        self.path = monitor.data / "suite.json"
        saved = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.durations = saved.get("durations", {})
        self.jobs = saved.get("jobs", [])
        self.groups = {}
        self.ws = None
        self.ack = None
        self.dispatch_lock = asyncio.Lock()
        self.interrupt("Suite restarted before a result was received.")

    def save(self):
        from .suite_launcher import write_json

        # Keep active jobs even when the recent history window fills up.
        recent = {job["id"] for job in self.jobs[-80:]}
        self.jobs[:] = [job for job in self.jobs if job["id"] in recent or self.pending(job)]
        write_json(self.path, {"durations": self.durations, "jobs": self.jobs})

    @staticmethod
    def pending(job):
        return any(result["status"] in PENDING for result in job["results"].values())

    def interrupt(self, detail):
        changed = False
        for job in self.jobs:
            for result in job["results"].values():
                if result["status"] in PENDING:
                    result.update(status="Unverified", detail=detail)
                    changed = True
        if changed:
            self.save()

    def expire(self):
        changed = False
        for job in self.jobs:
            timeout = 60 if job["kind"] == "launch" else 3600
            if time.time() - job["at"] < timeout:
                continue
            for result in job["results"].values():
                if result["status"] in PENDING:
                    result.update(status="Unverified", detail="No final headset result received.")
                    changed = True
        if changed:
            self.save()

    def receive(self, message):
        kind = message.get("type")
        if kind == "GROUP_LIST":
            self.groups = message["groups"]
        if self.ack:
            expected, future = self.ack
            if not future.done() and kind in {expected, "ERROR"}:
                future.set_result(message)
        for job in reversed(self.jobs):
            if not self.pending(job) or job["kind"] not in OPERATIONS or not job.get("match"):
                continue
            _, _, _, result_type, key = OPERATIONS[job["kind"]]
            progress = {"install": "INSTALL_DEVICE_STATE", "files": "PUSH_DEVICE_STATE"}.get(job["kind"])
            if kind not in {result_type, progress} or message.get(key) != job["match"]:
                continue
            if job["kind"] == "files" and message.get("delete_extras") is True:
                continue
            ids = [message.get("device_id")] if kind == result_type else message.get("device_ids", [])
            changed = False
            for device_id in ids:
                entry = job["results"].get(device_id)
                if not entry or entry["status"] not in PENDING:
                    continue
                detail = str(message.get("error") or message.get("detail") or message.get("message") or "")[:350]
                if kind == result_type:
                    succeeded = message.get("status") == "success"
                    entry.update(status="Confirmed" if succeeded else "Failed", detail=detail)
                    if succeeded and progress:
                        entry["transfer"] = "Complete"
                else:
                    status = {"queued": "Queued", "transferring": "Transferring", "installing": "Installing",
                              "applying": "Applying", "fail": "Failed"}.get(message.get("state"))
                    if not status:
                        continue
                    entry.update(status=status, detail=detail)
                    if status in {"Installing", "Applying"}:
                        entry["transfer"] = "Complete"
                    elif status == "Failed" and entry.get("transfer") != "Complete":
                        entry["transfer"] = "Failed"
                    elif status != "Failed":
                        entry["transfer"] = status
                changed = True
            if changed:
                self.save()

    async def send(self, payload, expected):
        async with self.dispatch_lock:
            if self.ws is None or self.ws.closed:
                raise web.HTTPServiceUnavailable(text="MDM is disconnected. Reconnect before sending commands.")
            future = asyncio.get_running_loop().create_future()
            self.ack = expected, future
            try:
                await self.ws.send_json(payload)
                message = await asyncio.wait_for(future, 8)
            except (OSError, asyncio.TimeoutError, ClientError):
                raise web.HTTPGatewayTimeout(text="MDM did not acknowledge the command. Check Activity before retrying.") from None
            finally:
                self.ack = None
            if message["type"] == "ERROR":
                raise web.HTTPBadRequest(text=message.get("message", "MDM rejected the command."))
            return message

    def new_job(self, kind, title, results):
        job = dict(id=uuid4().hex, at=time.time(), title=title, kind=kind, results=results)
        self.jobs.append(job)
        self.save()
        return job

    def record_fleet(self, title, results):
        self.new_job("fleet", title, {result["device_id"]: result for result in results})

    def targets(self, ids):
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(i, str) for i in ids):
            raise web.HTTPBadRequest(text="Select one or more headsets.")
        devices = {device["device_id"]: device for device in self.monitor.devices}
        if any(device_id not in devices for device_id in ids):
            raise web.HTTPBadRequest(text="The selected headsets changed. Refresh the selection.")
        if not self.monitor.connected:
            raise web.HTTPServiceUnavailable(text="MDM is disconnected.")
        return [devices[device_id] for device_id in dict.fromkeys(ids)]

    async def upload(self, request, endpoint, devices):
        origin = download_origin(devices, self.monitor.upstream)
        if request.content_type != "multipart/form-data":
            raise web.HTTPBadRequest(text="Choose a file before starting the transfer.")
        headers = {"Content-Type": request.headers["Content-Type"], "Host": origin.authority}
        instance = os.environ.get("IMMENSIVA_SUITE_INSTANCE")
        if instance:
            headers["X-Venue-Suite"] = instance
        try:
            async with ClientSession(timeout=ClientTimeout(total=3600, sock_connect=5)) as client:
                async with client.post(self.monitor.upstream + endpoint, headers=headers,
                                       data=request.content.iter_chunked(128 * 1024)) as response:
                    uploaded = await response.json(content_type=None)
                    if response.status >= 400:
                        raise web.HTTPBadRequest(text=uploaded.get("error", "MDM could not accept the upload."))
        except (OSError, ValueError, ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(text="Upload to MDM failed. Check the file and the MDM log.") from None
        key = "apk_url" if endpoint == "/api/apks" else "bundle_url"
        url = URL(uploaded.get(key, ""))
        filename = uploaded.get("apk_filename" if endpoint == "/api/apks" else "bundle_filename")
        if (url.scheme != "http" or url.host is None or url.origin() != origin or not filename
                or url.name != filename or url.parent.path != ("/apks" if endpoint == "/api/apks" else "/bundles")):
            raise web.HTTPBadGateway(text="MDM returned an unusable download URL. Check its venue LAN address before retrying.")
        return uploaded

    async def operation(self, request):
        kind = request.match_info["kind"]
        if kind not in OPERATIONS:
            raise web.HTTPNotFound()
        if kind == "launch":
            data = await json_object(request)
            ids, package = data.get("targets"), data.get("package")
            if not isinstance(package, str) or package not in self.packages:
                raise web.HTTPBadRequest(text="Choose a registered experience.")
            extras = {"package_name": package}
        else:
            ids = request.query.getall("target", [])
            extras = {}
            if kind == "files":
                from .server import validate_headset_destination

                destination = request.query.get("destination", "").strip()
                error = validate_headset_destination(destination)
                if error:
                    raise web.HTTPBadRequest(text=error)
                extras = {"dest_path": destination, "delete_extras": False}
        targets = self.targets(ids)
        online = [device for device in targets if device["status"] == "online"]
        if not online:
            raise web.HTTPConflict(text="None of the selected headsets are online.")
        active = {device["device_id"] for device in online}
        if any(job["kind"] in OPERATIONS and any(
            job["results"].get(device_id, {}).get("status") in PENDING for device_id in active
        ) for job in self.jobs):
            raise web.HTTPConflict(text="A selected headset already has a pending preparation command.")
        title, command, expected, _, match_key = OPERATIONS[kind]
        if kind == "launch":
            title += " · " + self.packages[package]
        results = {device["device_id"]: dict(status=("Dispatched" if kind == "launch" else "Uploading")
                   if device["device_id"] in active else "Skipped",
                   detail="" if device["device_id"] in active else "Offline") for device in targets}
        job = self.new_job(kind, title, results)
        try:
            if kind != "launch":
                prefix = "apk" if kind == "install" else "bundle"
                endpoint = "/api/apks" if kind == "install" else "/api/bundles"
                uploaded = await self.upload(request, endpoint, online)
                if not self.pending(job):
                    raise web.HTTPServiceUnavailable(text="MDM disconnected during upload. Review Activity before retrying.")
                extras.update({key: uploaded[key] for key in (prefix + "_url", prefix + "_filename")})
                job["title"] += " · " + (extras["apk_filename"] if kind == "install" else extras["dest_path"])
                for device_id in active:
                    results[device_id].update(status="Queued", transfer="Queued")
            job["match"] = extras[match_key]
            self.save()
            reply = await self.send(dict(type=command, target_devices=sorted(active), **extras), expected)
            if reply.get("sent_count", reply.get("target_count", len(active))) < len(active):
                for entry in results.values():
                    if entry["status"] in {"Dispatched", "Queued"}:
                        entry["detail"] = "MDM accepted fewer targets than selected. Awaiting headset result."
            self.save()
        except (web.HTTPException, asyncio.CancelledError) as error:
            for entry in results.values():
                if entry["status"] in PENDING:
                    uncertain = isinstance(error, (web.HTTPGatewayTimeout, asyncio.CancelledError))
                    entry.update(status="Unverified" if uncertain else "Failed",
                                 detail=getattr(error, "text", "Request interrupted."))
            self.save()
            raise
        return web.json_response(job, status=202)

    async def duration_settings(self, request):
        data = await json_object(request)
        if any(package not in self.packages or (minutes is not None and (
            type(minutes) not in (float, int) or not math.isfinite(minutes) or not 0 < minutes <= 240
        )) for package, minutes in data.items()):
            raise web.HTTPBadRequest(text="Enter a duration between 0 and 240 minutes or leave it blank.")
        for package, minutes in data.items():
            if minutes is None:
                self.durations.pop(package, None)
            else:
                self.durations[package] = minutes
        self.save()
        return web.json_response(self.durations)

    async def room_group(self, request):
        from styly_mdm.server import MAX_GROUP_NAME_LEN

        data = await json_object(request)
        name = data.get("name")
        if not isinstance(name, str) or not 0 < len(name.strip()) <= MAX_GROUP_NAME_LEN:
            raise web.HTTPBadRequest(text="Enter a room name.")
        name = name.strip()
        ids = data.get("members")
        members = [device["device_id"] for device in self.targets(ids)] if ids != [] else []
        if name not in self.groups:
            await self.send(dict(type="CREATE_GROUP", name=name), "GROUP_CREATED")
        await self.send(dict(type="SET_GROUP_MEMBERS", name=name, members=members), "GROUP_MEMBERS_SET")
        return web.json_response({"ok": True})


async def json_object(request):
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid JSON request.") from None
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object.")
    return data
