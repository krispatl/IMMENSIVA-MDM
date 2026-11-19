"""State-aware controls for PICO's native recorder; video stays on the headset."""
import asyncio
import re
import time

from .adb import HeadsetAdb


PACKAGE = "org.immensiva.recording"
STATE_PROPERTY = "pvr.screen.action"


def parse_recording_state(properties, *, verified_initial_idle=False):
    # Missing and empty are different: only a present, empty native flag means idle.
    matches = re.findall(r"(?m)^\[pvr\.screen\.action\]: \[(.*)\]\r?$", properties)
    if not matches and verified_initial_idle:
        return "stopped"
    if len(matches) != 1 or matches[0] not in {"", "record"}:
        raise RuntimeError("Recording state is unavailable on this headset.")
    return "recording" if matches[0] == "record" else "stopped"


class PicoRecorder(HeadsetAdb):
    def __init__(self, tools):
        super().__init__(tools)
        self.helper = tools / "screen-recording.apk"
        self.installed = set()
        self.last_sent = {}

    @property
    def available(self):
        return self.helper.is_file() and self.adb.is_file()

    async def state(self, device):
        if not self.available:
            raise ValueError("Native recording tools are missing. See docs/SCREEN_RECORDING.md.")
        address = await self.connect(device)
        return {"state": await self.read_state(address)}

    async def read_state(self, address):
        properties = await self.command("-s", address, "shell", "getprop")
        initial_idle = False
        # On this verified firmware the flag is first created when recording starts.
        # Do not generalize an absent flag to idle on other recorder/firmware versions.
        if ("[pvr.screen.action]:" not in properties
                and "[ro.pui.build.version]: [5.15.7]" in properties.splitlines()):
            package = await self.command("-s", address, "shell", "cmd", "package", "list", "packages",
                                         "--show-versioncode", "com.bytedance.pico.screencapture")
            initial_idle = package.strip() == "package:com.bytedance.pico.screencapture versionCode:100004072"
        return parse_recording_state(properties, verified_initial_idle=initial_idle)

    async def set_state(self, device, action, request_id):
        if action not in ("start", "stop"):
            raise ValueError("Choose Start or Stop recording. Reload the page if it still shows a toggle.")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise ValueError("Invalid recording request ID.")
        if device.get("status") != "online":
            raise ValueError("Select an online headset.")
        if not self.available:
            raise ValueError("Native recording tools are missing. See docs/SCREEN_RECORDING.md.")
        device_id = device["device_id"]
        lock = self.locks.setdefault(device_id, asyncio.Lock())
        if lock.locked():
            raise ValueError("A recording request is already in progress for this headset.")
        async with lock:
            if time.monotonic() - self.last_sent.get(device_id, -float("inf")) < 3:
                raise ValueError("Wait a few seconds for the current recording change to finish.")
            address = await self.connect(device)
            # Fail closed on unsupported firmware, before installing or invoking the helper.
            await self.read_state(address)
            if device_id not in self.installed:
                output = await self.command("-s", address, "install", "--no-incremental", "-r",
                                            str(self.helper), timeout=45)
                if "Success" not in output.splitlines():
                    raise RuntimeError("Recording helper installation failed: " + output[-500:])
                self.installed.add(device_id)
            self.last_sent[device_id] = time.monotonic()
            # The helper rechecks native state on the headset immediately before dispatch.
            # Never retry a toggle on a lost response, even when the requested state is known.
            try:
                output = await self.command(
                    "-s", address, "shell", "am", "start-foreground-service",
                    "-n", PACKAGE + "/.RecordingService", "--es", "request", request_id,
                    "--es", "action", action)
                if "Error" in output or "Exception" in output:
                    self.installed.discard(device_id)
                    raise RuntimeError(output[-500:])
                prefix = "RESULT " + request_id + " "
                for _ in range(60):
                    logs = await self.command("-s", address, "logcat", "-d", "-t", "200",
                                              "-s", "IMMENSIVA_RECORD:I", "*:S")
                    for line in reversed(logs.splitlines()):
                        if prefix in line:
                            result = line.split(prefix, 1)[1].strip()
                            expected = "recording" if action == "start" else "stopped"
                            if result in {"STATE " + expected + " CHANGED", "STATE " + expected + " UNCHANGED"}:
                                observed = await self.read_state(address)
                                if observed != expected:
                                    raise RuntimeError("The headset recording state changed before confirmation.")
                                changed = result.endswith(" CHANGED")
                                message = ("Recording active on the headset." if expected == "recording"
                                           else "Recording stopped on the headset.")
                                if not changed:
                                    message = "Already " + expected + "; no recording command was sent."
                                return {"status": "confirmed", "state": observed, "changed": changed, "message": message}
                            raise RuntimeError(result)
                    await asyncio.sleep(.25)
            except (OSError, RuntimeError, asyncio.TimeoutError) as error:
                raise RuntimeError(
                    f"Recording request was not confirmed: {error}. Check the headset before retrying.") from error
            raise RuntimeError("Recording request was not confirmed. Check the headset before retrying.")
