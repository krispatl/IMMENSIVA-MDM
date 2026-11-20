import asyncio
import json
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
import pytest_asyncio

from immensiva_mdm import server
from immensiva_mdm.browser import HeadsetBrowser


DEVICE = {"device_id": "tabs-pico", "ip": "192.0.2.1", "status": "online"}
PACKAGE = "com.pico.browser.overseas"


@pytest_asyncio.fixture
async def tab_browser(tmp_path):
    tools = tmp_path / "tools"
    (tools / "scrcpy-win64-v5.0.1").mkdir(parents=True)
    (tools / "scrcpy-win64-v5.0.1/adb.exe").touch()
    browser = HeadsetBrowser(tools)
    state = {"tabs": [{"id": "one", "type": "page", "url": "https://private.invalid/?token=secret"},
                      {"id": "two", "type": "page", "url": "https://example.com/"},
                      {"id": "worker", "type": "service_worker"}],
             "requests": [], "mode": "normal", "running": True,
             "started": asyncio.Event(), "release": asyncio.Event()}

    async def listing(request):
        if state["mode"] == "wait":
            state["started"].set()
            await state["release"].wait()
        if state["mode"] == "redirect":
            raise web.HTTPFound("/unexpected")
        # Split JSON across chunks to exercise real HTTP response handling.
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        data = json.dumps(state["tabs"]).encode()
        await response.write(data[:5])
        await asyncio.sleep(0)
        await response.write(data[5:])
        await response.write_eof()
        return response

    async def close(request):
        key = request.match_info["target"]
        state["requests"].append(key)
        if state["mode"] != "unchanged":
            state["tabs"] = [tab for tab in state["tabs"] if tab["id"] != key]
            if not any(tab["type"] == "page" for tab in state["tabs"]) and state.get("replacement"):
                state["tabs"].append({"id": "replacement", "type": "page", "url": state["replacement"]})
        return web.Response(text="Target is closing", status=500 if state["mode"] == "lost" else 200)

    app = web.Application()
    app.router.add_get("/json/list", listing)
    app.router.add_get("/json/close/{target}", close)
    async with TestServer(app) as transport:
        async def command(*args, **kwargs):
            if args[0] == "connect":
                return "connected"
            if args[2:] == ("shell", "getprop", "ro.serialno"):
                return DEVICE["device_id"]
            if args[2] == "shell" and args[3].startswith("cmd package resolve-activity"):
                return PACKAGE + "/.Main"
            if args[2] == "shell" and args[3].startswith("pidof "):
                return "123" if state["running"] else ""
            if args[2:] == ("shell", "cat", "/proc/net/unix"):
                return "other @weblayer_devtools_remote_999\nbrowser @weblayer_devtools_remote_123"
            if args[2] == "shell" and args[3].startswith("am start "):
                state["running"] = True
                return "Status: ok"
            if args[2:] == ("forward", "tcp:0", "localabstract:weblayer_devtools_remote_123"):
                return str(transport.port)
            if args[2:] == ("forward", "--remove", "tcp:" + str(transport.port)):
                return ""
            raise AssertionError(args)
        browser.command = AsyncMock(side_effect=command)
        try:
            yield browser, state
        finally:
            state["release"].set()


@pytest.mark.asyncio
async def test_close_tabs_uses_browser_socket_preserves_workers_and_removes_its_forward(tab_browser):
    browser, state = tab_browser
    result = await browser.close_all_tabs(DEVICE)
    assert result["status"] == "confirmed" and result["closed"] == 2 and result["remaining"] == 0
    assert state["requests"] == ["one", "two"]
    assert state["tabs"] == [{"id": "worker", "type": "service_worker"}]
    assert "private" not in str(result) and "secret" not in str(result)
    calls = [call.args for call in browser.command.await_args_list]
    assert calls[-1][2:4] == ("forward", "--remove")
    assert sum("tcp:0" in call for call in calls) == 1
    assert not any(any(word in str(call) for word in ("pm clear", "force-stop", "install", "remove-all")) for call in calls)


@pytest.mark.asyncio
async def test_browser_is_started_to_close_saved_tabs_when_not_running(tab_browser):
    browser, state = tab_browser
    state["running"] = False
    assert (await browser.close_all_tabs(DEVICE))["status"] == "confirmed"
    launches = [call.args[3] for call in browser.command.await_args_list if len(call.args) > 3 and call.args[3].startswith("am start ")]
    assert len(launches) == 1 and "android.intent.action.MAIN" in launches[0] and " -d " not in launches[0]


@pytest.mark.asyncio
async def test_empty_browser_is_success_without_close_requests(tab_browser):
    browser, state = tab_browser
    state["tabs"] = []
    result = await browser.close_all_tabs(DEVICE)
    assert result == {"status": "confirmed", "closed": 0, "remaining": 0, "message": "No open browser tabs."}
    assert state["requests"] == []


@pytest.mark.asyncio
async def test_pico_retaining_current_activity_reports_launch_block_instead_of_unsupported_browser(tab_browser):
    browser, state = tab_browser
    state["running"] = False
    original_command = browser.command.side_effect

    async def blocked_launch(*args, **kwargs):
        if len(args) > 3 and args[2] == "shell" and args[3].startswith("am start "):
            return "Warning: Activity not started because the  current activity is being kept for the user.\nStatus: ok"
        return await original_command(*args, **kwargs)

    browser.command.side_effect = blocked_launch
    with pytest.raises(RuntimeError, match="did not allow its browser to open"):
        await browser.close_all_tabs(DEVICE)
    assert not any("forward" in call.args for call in browser.command.await_args_list)
    assert not state["requests"]


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement,expected", [("about:blank", "confirmed"), ("https://example.com/new", "partial")])
async def test_replacement_tab_is_not_chased_and_only_empty_replacement_counts_as_complete(tab_browser, replacement, expected):
    browser, state = tab_browser
    state["replacement"] = replacement
    result = await browser.close_all_tabs(DEVICE)
    assert result["status"] == expected and result["closed"] == 2 and result["remaining"] == 1
    assert state["requests"] == ["one", "two"]


@pytest.mark.asyncio
async def test_success_response_is_not_enough_if_tabs_remain(tab_browser):
    browser, state = tab_browser
    state["mode"] = "unchanged"
    with patch("immensiva_mdm.browser.asyncio.sleep", new_callable=AsyncMock):
        result = await browser.close_all_tabs(DEVICE)
    assert result["status"] == "partial" and result["closed"] == 0 and result["remaining"] == 2
    assert state["requests"] == ["one", "two"]


@pytest.mark.asyncio
async def test_lost_close_response_is_verified_without_retrying(tab_browser):
    browser, state = tab_browser
    state["mode"] = "lost"
    assert (await browser.close_all_tabs(DEVICE))["status"] == "confirmed"
    assert state["requests"] == ["one", "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tabs", [None, {}, ["invalid"], [{"type": "page", "id": "../../other"}],
    [{"type": "page", "id": "one"}, {"type": "page", "id": "one"}], [{"type": "page", "id": "one", "url": []}]])
async def test_invalid_tab_metadata_never_closes_and_still_cleans_up(tab_browser, tabs):
    browser, state = tab_browser
    state["tabs"] = tabs
    with pytest.raises(RuntimeError, match="tab list"):
        await browser.close_all_tabs(DEVICE)
    assert state["requests"] == []
    assert browser.command.await_args.args[2:4] == ("forward", "--remove")


@pytest.mark.asyncio
async def test_http_redirect_is_rejected_and_forward_removed(tab_browser):
    browser, state = tab_browser
    state["mode"] = "redirect"
    with pytest.raises(RuntimeError, match="rejected"):
        await browser.close_all_tabs(DEVICE)
    assert state["requests"] == []
    assert browser.command.await_args.args[2:4] == ("forward", "--remove")


@pytest.mark.asyncio
async def test_cancelled_request_removes_forward_and_releases_device_lock(tab_browser):
    browser, state = tab_browser
    state["mode"] = "wait"
    operation = asyncio.create_task(browser.close_all_tabs(DEVICE))
    await asyncio.wait_for(state["started"].wait(), 3)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    state["release"].set()
    assert browser.command.await_args.args[2:4] == ("forward", "--remove")
    assert not browser.locks[DEVICE["device_id"]].locked()


@pytest.mark.asyncio
async def test_close_rejects_offline_missing_tools_busy_and_wrong_identity(tab_browser):
    browser, state = tab_browser
    with pytest.raises(ValueError, match="online"):
        await browser.close_all_tabs({**DEVICE, "status": "offline"})
    lock = browser.locks.setdefault(DEVICE["device_id"], asyncio.Lock())
    async with lock:
        with pytest.raises(ValueError, match="already in progress"):
            await browser.close_all_tabs(DEVICE)
        with pytest.raises(ValueError, match="already in progress"):
            await browser.open_url(DEVICE, "https://example.com/")
    browser.command.assert_not_awaited()
    browser.command.side_effect = ["connected", "another-headset"]
    with pytest.raises(RuntimeError, match="identity"):
        await browser.close_all_tabs(DEVICE)
    assert browser.command.await_count == 2
    browser.adb.unlink()
    with pytest.raises(ValueError, match="ADB tools"):
        await browser.close_all_tabs(DEVICE)
    assert browser.command.await_count == 2 and state["requests"] == []


@pytest.mark.asyncio
async def test_unrelated_socket_is_never_used(tab_browser):
    browser, state = tab_browser
    original_command = browser.command.side_effect
    async def unrelated(*args, **kwargs):
        if args[2:] == ("shell", "cat", "/proc/net/unix"):
            return "other @weblayer_devtools_remote_999"
        return await original_command(*args, **kwargs)
    browser.command.side_effect = unrelated
    with patch("immensiva_mdm.browser.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="does not expose tab controls"):
            await browser.close_all_tabs(DEVICE)
    assert not any("forward" in call.args for call in browser.command.await_args_list)
    assert state["requests"] == []


@pytest.mark.asyncio
async def test_mdm_close_tabs_route_validates_origin_device_payload_and_partial_results(tmp_path):
    server.upstream._apply_data_dir(str(tmp_path / "mdm"))
    server.upstream.devices.clear()
    server.upstream.device_registry.clear()
    fake = AsyncMock()
    fake.available = True
    fake.close_all_tabs.return_value = {"status": "confirmed", "closed": 2, "remaining": 0, "message": "Closed all 2 browser tabs."}
    with patch.object(server, "HeadsetBrowser", return_value=fake):
        async with TestClient(TestServer(server.create_app())) as client:
            body = {"device_id": DEVICE["device_id"]}
            assert (await client.post("/api/browser/close-tabs", json=body)).status == 409
            server.upstream.devices[DEVICE["device_id"]] = DEVICE.copy()
            assert (await client.post("/api/browser/close-tabs", json=body, headers={"Origin": "http://foreign.invalid"})).status == 403
            assert (await client.post("/api/browser/close-tabs", data="{}")).status == 415
            for invalid in [[], {}, {"device_id": []}]:
                assert (await client.post("/api/browser/close-tabs", json=invalid)).status == 400
            fake.close_all_tabs.assert_not_awaited()
            response = await client.post("/api/browser/close-tabs", json=body)
            assert response.status == 200 and (await response.json())["closed"] == 2
            fake.close_all_tabs.assert_awaited_once_with(DEVICE)
            fake.close_all_tabs.return_value = {"status": "partial", "closed": 1, "remaining": 1, "message": "One tab remains."}
            response = await client.post("/api/browser/close-tabs", json=body)
            assert response.status == 409 and (await response.json())["remaining"] == 1
            fake.close_all_tabs.side_effect = RuntimeError("Browser unavailable")
            response = await client.post("/api/browser/close-tabs", json=body)
            assert response.status == 400 and (await response.json())["error"] == "Browser unavailable"
            assert 'id="btnCloseBrowserTabs"' in await (await client.get("/")).text()
    server.upstream.devices.clear()
