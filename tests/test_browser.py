import asyncio
from pathlib import Path
import shlex
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
import pytest

from immensiva_mdm import server
from immensiva_mdm.browser import HeadsetBrowser, MESSAGE, validate_url
from immensiva_mdm.monitor import Monitor, create_app


DEVICE = dict(device_id="browser-pico", ip="192.0.2.1", status="online")
BROWSER = ("priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
           "com.pico.browser.overseas/com.google.android.apps.chrome.Main")


@pytest.fixture
def browser(tmp_path):
    (tmp_path / "scrcpy-win64-v5.0.1").mkdir()
    (tmp_path / "scrcpy-win64-v5.0.1/adb.exe").touch()
    return HeadsetBrowser(tmp_path)


@pytest.mark.parametrize("url", [
    None, {}, "", "example.com", "javascript:alert(1)", "intent://example.com",
    "file:///sdcard/file.html", "ftp://example.com", "https://", "https://example.com:bad/",
    "https://user:password@example.com", "https://example.com/a\nb", "https://example.com/a b",
    "https://example.com\\path", "https://example.com:70000", "https://example.com/" + "a" * 4096,
])
@pytest.mark.asyncio
async def test_invalid_url_is_rejected_before_adb(browser, url):
    browser.command = AsyncMock()
    with pytest.raises(ValueError):
        await browser.open_url(DEVICE, url)
    browser.command.assert_not_awaited()


@pytest.mark.parametrize("url", [
    "https://example.com/a?one=1&two=a%20b#scene",
    "http://192.168.1.20:8811/show", "https://[2001:db8::1]/scene",
    "https://example.com/?x=';echo${IFS}oops;$(id)`id`&y=2",
])
@pytest.mark.asyncio
async def test_open_url_preserves_data_and_targets_browser_without_installing(browser, url):
    browser.command = AsyncMock(side_effect=["connected", DEVICE["device_id"], BROWSER,
                                             "Status: ok\nActivity: com.pico.browser.overseas/com.google.android.apps.chrome.IntentDispatcher\nComplete"])
    assert await browser.open_url(DEVICE, url) == {"status": "requested", "message": MESSAGE}
    calls = [call.args for call in browser.command.await_args_list]
    assert calls[1] == ("-s", "192.0.2.1:5555", "shell", "getprop", "ro.serialno")
    assert calls[2][:3] == ("-s", "192.0.2.1:5555", "shell")
    discovery = shlex.split(calls[2][3])
    assert discovery == ["cmd", "package", "resolve-activity", "--brief", "--user", "current",
                         "-a", "android.intent.action.MAIN", "-c", "android.intent.category.APP_BROWSER"]
    remote = shlex.split(calls[3][3])
    assert remote == ["am", "start", "-W", "--user", "current", "-a", "android.intent.action.VIEW",
                      "-c", "android.intent.category.BROWSABLE", "-d", url, "-p", "com.pico.browser.overseas"]
    assert len(calls) == 4
    assert not (browser.adb.parent.parent / "screen-recording.apk").exists()


@pytest.mark.parametrize("component", ["vendor.browser/.Main", "vendor.browser/vendor.browser.Main$Alias"])
@pytest.mark.asyncio
async def test_browser_package_is_discovered_not_hardcoded(browser, component):
    browser.command = AsyncMock(side_effect=["connected", DEVICE["device_id"], component, "Status: ok"])
    await browser.open_url(DEVICE, "https://example.com")
    remote = shlex.split(browser.command.await_args.args[3])
    assert remote[remote.index("-p") + 1] == "vendor.browser"
    assert "-n" not in remote


@pytest.mark.parametrize("output", [
    "No activity found", "", "android/com.android.internal.app.ResolverActivity",
    "android/com.android.internal.app.ChooserActivity", "not a package/.Main",
    "bad;command/.Main", "vendor.one/.Main\nvendor.two/.Main",
    RuntimeError("ADB failed"), asyncio.TimeoutError(),
])
@pytest.mark.asyncio
async def test_browser_discovery_failure_does_not_launch_or_send_url(browser, output):
    browser.command = AsyncMock(side_effect=["connected", DEVICE["device_id"], output])
    with pytest.raises(RuntimeError):
        await browser.open_url(DEVICE, "https://example.com/?secret=private")
    assert browser.command.await_count == 3
    assert "private" not in str(browser.command.await_args_list)


@pytest.mark.asyncio
async def test_busy_offline_missing_tools_and_wrong_identity_do_not_launch(browser):
    browser.command = AsyncMock()
    with pytest.raises(ValueError, match="online"):
        await browser.open_url({**DEVICE, "status": "offline"}, "https://example.com")
    browser.command.assert_not_awaited()
    lock = browser.locks.setdefault(DEVICE["device_id"], asyncio.Lock())
    async with lock:
        with pytest.raises(ValueError, match="already in progress"):
            await browser.open_url(DEVICE, "https://example.com")
    browser.command.assert_not_awaited()
    browser.command.side_effect = ["connected", "another-headset"]
    with pytest.raises(RuntimeError, match="identity"):
        await browser.open_url(DEVICE, "https://example.com")
    assert browser.command.await_count == 2
    browser.adb.unlink()
    with pytest.raises(ValueError, match="ADB tools"):
        await browser.open_url(DEVICE, "https://example.com")
    assert browser.command.await_count == 2


@pytest.mark.parametrize("output", [
    "Error: Activity not started, unable to resolve Intent {dat=https://example.com/?secret=private}",
    "Status: timeout", "", "SecurityException: denied\nStatus: ok",
    "Status: ok\nActivity: android/com.android.internal.app.ResolverActivity",
    RuntimeError("permission denied for https://example.com/?secret=private"), asyncio.TimeoutError(),
])
@pytest.mark.asyncio
async def test_launch_failure_is_reported_without_url_echo_or_automatic_retry(browser, output):
    browser.command = AsyncMock(side_effect=["connected", DEVICE["device_id"], BROWSER, output])
    with pytest.raises(RuntimeError) as error:
        await browser.open_url(DEVICE, "https://example.com/?secret=private")
    assert "private" not in str(error.value)
    assert browser.command.await_count == 4


@pytest.mark.asyncio
async def test_mdm_open_url_endpoint_targets_only_connected_device(tmp_path):
    server.upstream._apply_data_dir(str(tmp_path / "mdm"))
    server.upstream.devices.clear()
    server.upstream.device_registry.clear()
    fake = AsyncMock()
    fake.available = True
    fake.open_url.return_value = {"status": "requested", "message": MESSAGE}
    with patch.object(server, "HeadsetBrowser", return_value=fake):
        async with TestClient(TestServer(server.create_app())) as client:
            body = {"device_id": DEVICE["device_id"], "url": "https://example.com/?a=1&b=2"}
            assert (await (await client.get("/api/open-url")).json())["available"]
            assert (await client.post("/api/open-url", json=body)).status == 409
            server.upstream.devices[DEVICE["device_id"]] = DEVICE.copy()
            assert (await client.post("/api/open-url", json=body,
                                      headers={"Origin": "http://foreign.invalid"})).status == 403
            assert (await client.post("/api/open-url", data="{}")).status == 415
            for invalid in [[], {}, {"device_id": []}]:
                assert (await client.post("/api/open-url", json=invalid)).status == 400
            fake.open_url.assert_not_awaited()
            response = await client.post("/api/open-url", json=body)
            assert response.status == 200
            assert (await response.json())["message"] == MESSAGE
            fake.open_url.assert_awaited_once_with(DEVICE, body["url"])
            fake.open_url.side_effect = ValueError("Enter an http:// or https:// URL.")
            response = await client.post("/api/open-url", json={**body, "url": "file:///sdcard/"})
            assert response.status == 400
            assert "https://" in (await response.json())["error"]
    server.upstream.devices.clear()


@pytest.mark.asyncio
async def test_live_ops_open_url_keeps_url_out_of_activity_and_rejects_offline_and_touch(tmp_path):
    monitor = Monitor(tmp_path, Path("adb"), Path("scrcpy"), "http://localhost")
    monitor.connected = True
    monitor.devices = [DEVICE.copy()]
    for name in ("feed", "timers", "refresh_displays", "refresh_foreground"):
        setattr(monitor, name, AsyncMock())
    monitor.browser.open_url = AsyncMock(return_value={"status": "requested", "message": MESSAGE})
    body = {"action": "open_url", "device_id": DEVICE["device_id"], "url": "https://example.com/?secret=private"}
    async with TestClient(TestServer(create_app(monitor))) as client:
        assert (await client.post("/api/action", json=body)).status == 200
        monitor.browser.open_url.assert_awaited_once_with(DEVICE, body["url"])
        snapshot = await (await client.get("/api/state")).json()
        assert snapshot["events"][-1]["message"] == MESSAGE
        assert "private" not in str(snapshot)
        assert set(snapshot["disabled_actions"]) == {"track", "view"}
        monitor.connected = False
        assert (await client.post("/api/action", json=body)).status == 409
    config = {"address": "192.0.2.10", "key": "test"}
    async with TestClient(TestServer(create_app(monitor, config, touch_only=True))) as client:
        assert (await client.post("/api/action", json=body, headers={
            "Host": "192.0.2.10:7081", "Authorization": "Bearer test"})).status == 403
    assert monitor.browser.open_url.await_count == 1
