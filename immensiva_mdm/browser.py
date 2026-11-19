"""Open a web URL in the headset browser without installing an APK."""
import asyncio
import re
import shlex
from urllib.parse import urlsplit

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
