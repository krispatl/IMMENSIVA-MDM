"""ADB transport shared by operator controls, with device identity verification."""
import asyncio
from ipaddress import ip_address
import os


class HeadsetAdb:
    def __init__(self, tools):
        self.adb = tools / "scrcpy-win64-v5.0.1" / "adb.exe"
        self.locks = {}

    @property
    def available(self):
        return self.adb.is_file()

    async def command(self, *args, timeout=15):
        process = await asyncio.create_subprocess_exec(
            str(self.adb), *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        result = output.decode(errors="replace").strip()
        if process.returncode:
            raise RuntimeError(result[-1000:] or "ADB command failed.")
        return result

    async def connect(self, device):
        if device.get("status") != "online":
            raise ValueError("Select an online headset.")
        address = str(ip_address(device["ip"]))
        address = (f"[{address}]" if ":" in address else address) + ":5555"
        await self.command("connect", address)
        serial = await self.command("-s", address, "shell", "getprop", "ro.serialno")
        if serial != device["device_id"]:
            raise RuntimeError("ADB identity does not match the selected headset.")
        return address
