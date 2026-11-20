"""Open URLs and close PICO browser tabs without clearing browser data."""
import asyncio
import json
import re
import shlex
from urllib.parse import urlsplit

import aiohttp

from .adb import HeadsetAdb


MESSAGE = "URL sent to the headset browser. Check the page in the headset."


def validate_url(value):
    if not isinstance(value, str):
        raise ValueError("Enter a complete http:// or https:// URL.")
    value = value.strip()
    if (not value or len(value) > 4096 or "\\" in value
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError("Enter a URL of at most 4096 characters, without spaces or control characters.")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError()
        # Preserve paths, encoded characters, query strings and fragments exactly.
        host = parsed.hostname.encode("idna").decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError("Enter a complete http:// or https:// URL without embedded login credentials.") from None
    return value


class HeadsetBrowser(HeadsetAdb):
    async def browser_socket(self, address, package):
        async def find():
            pids = (await self.command("-s", address, "shell", "pidof " + shlex.quote(package) + " || true")).split()
            if not pids:
                return None
            if len(pids) != 1 or not pids[0].isdigit():
                raise RuntimeError("Could not identify the headset browser process.")
            # Only use the socket belonging to the resolved browser's main process.
            # Other apps' WebViews may also expose debugging sockets on this headset.
            socket = "weblayer_devtools_remote_" + pids[0]
            sockets = (await self.command("-s", address, "shell", "cat", "/proc/net/unix")).split()
            return socket if "@" + socket in sockets else None

        socket = await find()
        if socket:
            return socket
        # Restore saved tabs if the browser is not running, without opening a URL.
        output = await self.command("-s", address, "shell", shlex.join([
            "am", "start", "-W", "--user", "current", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.APP_BROWSER", "-p", package,
        ]), timeout=30)
        if not re.search(r"(?im)^Status:\s*ok\s*$", output):
            raise RuntimeError("Could not open the browser to close its saved tabs.")
        # PICO can return Status: ok while retaining its current system activity
        # and never starting the browser. Do not misreport that as unsupported.
        if re.search(r"Activity not started because.*current activity.*kept", output):
            socket = await find()
            if socket:
                return socket
            raise RuntimeError("The headset did not allow its browser to open. Wake the headset and open its browser once, then retry. No browser data was cleared.")
        for _ in range(12):
            socket = await find()
            if socket:
                return socket
            await asyncio.sleep(.25)
        raise RuntimeError("This headset browser does not expose tab controls. No browser data was cleared.")

    async def devtools_request(self, session, port, path):
        try:
            async with session.get(f"http://127.0.0.1:{port}{path}", allow_redirects=False) as response:
                if response.status != 200:
                    raise RuntimeError("The headset browser rejected a tab-control request.")
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise RuntimeError("The headset browser returned too much tab information.")
                return data.decode("utf-8")
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as error:
            raise RuntimeError("Browser tab controls did not respond. Check the headset before retrying.") from error

    async def browser_tabs(self, session, port):
        try:
            targets = json.loads(await self.devtools_request(session, port, "/json/list"))
            if not isinstance(targets, list) or any(not isinstance(target, dict) for target in targets):
                raise ValueError()
            tabs = {}
            for target in targets:
                if target.get("type") != "page":
                    continue
                key = target.get("id")
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key) or key in tabs:
                    raise ValueError()
                # Keep only whether a page is empty; never return/log browsing URLs.
                tabs[key] = target.get("url") in {"about:blank", "chrome://newtab/", "chrome-native://newtab/"}
            return tabs
        except (ValueError, TypeError) as error:
            raise RuntimeError("Could not read the headset browser's tab list.") from error

    async def close_all_tabs(self, device):
        if device.get("status") != "online":
            raise ValueError("Select an online headset.")
        if not self.available:
            raise ValueError("Browser controls need the ADB tools on this PC. Ask your technician to add them.")
        lock = self.locks.setdefault(device["device_id"], asyncio.Lock())
        if lock.locked():
            raise ValueError("A browser request is already in progress for this headset.")
        async with lock:
            address = await self.connect(device)
            package = await self.resolve_browser(address)
            try:
                return await asyncio.wait_for(self.close_browser_tabs(address, package), timeout=90)
            except asyncio.TimeoutError as error:
                raise RuntimeError("Closing browser tabs timed out. Check the headset before retrying.") from error

    async def close_browser_tabs(self, address, package):
        socket = await self.browser_socket(address, package)
        port = await self.command("-s", address, "forward", "tcp:0", "localabstract:" + socket)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise RuntimeError("Could not create the temporary browser connection.")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5), trust_env=False) as session:
                original = await self.browser_tabs(session, port)
                # Snapshot the tabs. Do not chase tabs opened by a person during the operation.
                for key in original:
                    try:
                        await self.devtools_request(session, port, "/json/close/" + key)
                    except RuntimeError:
                        # A lost response is ambiguous: verify the resulting list, never retry closing.
                        pass
                remaining = await self.browser_tabs(session, port)
                for _ in range(8):
                    if not original.keys() & remaining.keys():
                        break
                    await asyncio.sleep(.25)
                    remaining = await self.browser_tabs(session, port)
                closed = len(original.keys() - remaining.keys())
                empty_replacement = (len(remaining) == 1 and all(remaining.values())
                                     and not original.keys() & remaining.keys())
                complete = not remaining or empty_replacement
                if empty_replacement:
                    message = f"Closed {closed} browser tab(s). The browser has one new empty tab."
                elif complete:
                    message = f"Closed all {closed} browser tab(s)." if closed else "No open browser tabs."
                else:
                    message = f"Closed {closed} browser tab(s); {len(remaining)} remain. Check the headset before retrying."
                return {"status": "confirmed" if complete else "partial", "closed": closed,
                        "remaining": len(remaining), "message": message}
        finally:
            # Remove only this request's dynamically allocated forward, including on cancellation.
            await self.command("-s", address, "forward", "--remove", "tcp:" + port, timeout=5)

    async def resolve_browser(self, address):
        # Resolve without a URL: `am`'s --selector parsing can attach the URL
        # to MAIN/APP_BROWSER, which PICO's launcher activity cannot handle.
        # Use the discovered package with VIEW so Android chooses its URL entry
        # point (IntentDispatcher on PICO), not its launcher activity (Main).
        try:
            output = await self.command("-s", address, "shell", shlex.join([
                "cmd", "package", "resolve-activity", "--brief", "--user", "current",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_BROWSER",
            ]))
        except (OSError, RuntimeError, asyncio.TimeoutError) as error:
            raise RuntimeError("Could not find the headset browser. Check its ADB connection.") from error
        if "ResolverActivity" in output or "ChooserActivity" in output:
            raise RuntimeError("Choose a default browser inside the headset, then try again.")
        components = re.findall(r"(?m)^\s*([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/[A-Za-z0-9_.$]+\s*$", output)
        if len(components) != 1:
            raise RuntimeError("The headset could not find a browser. Check that a browser is enabled and allowed by headset policy.")
        return components[0]

    async def open_url(self, device, url):
        url = validate_url(url)
        if device.get("status") != "online":
            raise ValueError("Select an online headset.")
        if not self.available:
            raise ValueError("Browser controls need the ADB tools on this PC. Ask your technician to add them.")
        lock = self.locks.setdefault(device["device_id"], asyncio.Lock())
        if lock.locked():
            raise ValueError("A browser request is already in progress for this headset.")
        async with lock:
            address = await self.connect(device)
            package = await self.resolve_browser(address)
            # ADB passes `shell` arguments through the Android shell. Quote every
            # argument there as well as using an argument array for the local process.
            # Restrict VIEW to the browser, rather than an app claiming the URL's domain.
            command = shlex.join([
                "am", "start", "-W", "--user", "current",
                "-a", "android.intent.action.VIEW", "-c", "android.intent.category.BROWSABLE",
                "-d", url, "-p", package,
            ])
            try:
                output = await self.command("-s", address, "shell", command, timeout=30)
            except (OSError, RuntimeError, asyncio.TimeoutError) as error:
                # Android diagnostics echo the URL, which may contain private query tokens.
                raise RuntimeError("Browser request was not confirmed. Check the headset and its ADB connection.") from error
            if "ResolverActivity" in output or "ChooserActivity" in output:
                raise RuntimeError("Choose a default browser inside the headset, then try again.")
            if (re.search(r"(?im)^\s*(?:Error|Exception|SecurityException)\b", output)
                    or not re.search(r"(?im)^Status:\s*ok\s*$", output)):
                raise RuntimeError("The headset could not open its browser. Check that a browser is enabled and allowed by headset policy.")
            return {"status": "requested", "message": MESSAGE}
