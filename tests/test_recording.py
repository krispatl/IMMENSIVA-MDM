import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
import pytest

from immensiva_mdm import server
from immensiva_mdm.monitor import Monitor, create_app
from immensiva_mdm.recording import PicoRecorder, parse_recording_state


MESSAGE = "Recording active on the headset."
STOPPED = "[pvr.screen.action]: []"
RECORDING = "[pvr.screen.action]: [record]"
REQUEST = "a" * 32
DEVICE = dict(device_id="one", ip="192.0.2.1", status="online", model="PICO 4 Ultra Enterprise")


@pytest.fixture
def recorder(tmp_path):
    (tmp_path / "screen-recording.apk").touch()
    (tmp_path / "scrcpy-win64-v5.0.1").mkdir()
    (tmp_path / "scrcpy-win64-v5.0.1/adb.exe").touch()
    return PicoRecorder(tmp_path)


@pytest.mark.parametrize("output", ["", "[unrelated]: [record]", "[pvr.screen.action]: [unknown]", STOPPED + "\n" + RECORDING])
def test_missing_or_unrecognized_native_flag_is_not_assumed_stopped(output):
    with pytest.raises(RuntimeError, match="state is unavailable"):
        parse_recording_state(output)


def test_native_flag_distinguishes_recording_from_present_empty_value():
    assert parse_recording_state(STOPPED) == "stopped"
    assert parse_recording_state(RECORDING + "\r\n") == "recording"


@pytest.mark.asyncio
async def test_state_read_is_read_only_and_checks_identity(recorder):
    recorder.command = AsyncMock(side_effect=["connected", "one", RECORDING])
    assert await recorder.state(DEVICE) == {"state": "recording"}
    assert recorder.command.await_count == 3
    assert recorder.command.await_args.args[-2:] == ("shell", "getprop")


@pytest.mark.asyncio
async def test_unknown_state_prevents_installation_and_record_command(recorder):
    recorder.command = AsyncMock(side_effect=["connected", "one", ""])
    with pytest.raises(RuntimeError, match="state is unavailable"):
        await recorder.set_state(DEVICE, "start", REQUEST)
    assert recorder.command.await_count == 3


@pytest.mark.parametrize("version", ["100004072", "100004073"])
@pytest.mark.asyncio
async def test_absent_flag_is_initial_idle_only_on_verified_native_recorder(recorder, version):
    recorder.command = AsyncMock(side_effect=["connected", "one", "[ro.pui.build.version]: [5.15.7]",
        "package:com.bytedance.pico.screencapture versionCode:" + version])
    if version == "100004072":
        assert await recorder.state(DEVICE) == {"state": "stopped"}
    else:
        with pytest.raises(RuntimeError, match="state is unavailable"):
            await recorder.state(DEVICE)


def test_verified_initial_idle_does_not_hide_invalid_existing_flag():
    with pytest.raises(RuntimeError):
        parse_recording_state("[pvr.screen.action]: [other]", verified_initial_idle=True)


@pytest.mark.parametrize("action", [None, "toggle", [], {}, "START"])
@pytest.mark.asyncio
async def test_invalid_action_never_reaches_headset(recorder, action):
    recorder.command = AsyncMock()
    with pytest.raises(ValueError, match="Start or Stop"):
        await recorder.set_state(DEVICE, action, REQUEST)
    recorder.command.assert_not_awaited()


@pytest.mark.parametrize("action,state,flag", [("start", "recording", RECORDING), ("stop", "stopped", STOPPED)])
@pytest.mark.asyncio
async def test_helper_noop_receipt_is_confirmed_against_native_state(recorder, action, state, flag):
    recorder.command = AsyncMock(side_effect=["connected", "one", flag, "Success", "Starting service",
        "RESULT " + REQUEST + " STATE " + state + " UNCHANGED", flag])
    result = await recorder.set_state(DEVICE, action, REQUEST)
    assert result["state"] == state and result["changed"] is False
    assert "no recording command" in result["message"]


@pytest.mark.asyncio
async def test_stale_success_receipt_does_not_claim_wrong_native_state_or_retry(recorder):
    recorder.command = AsyncMock(side_effect=["connected", "one", STOPPED, "Success", "Starting service",
        "RESULT " + REQUEST + " STATE recording CHANGED", STOPPED])
    with pytest.raises(RuntimeError, match="state changed"):
        await recorder.set_state(DEVICE, "start", REQUEST)
    assert sum("start-foreground-service" in call.args for call in recorder.command.await_args_list) == 1


@pytest.mark.asyncio
async def test_start_checks_identity_state_and_waits_for_its_own_receipt(recorder):
    recorder.command = AsyncMock(side_effect=[
        "connected", "one", STOPPED, "Success", "Starting service",
        "RESULT " + "b" * 32 + " STATE recording CHANGED", "RESULT " + REQUEST + " STATE recording CHANGED", RECORDING,
    ])
    result = await recorder.set_state(DEVICE, "start", REQUEST)
    assert result == {"status": "confirmed", "state": "recording", "changed": True, "message": MESSAGE}
    calls = [call.args for call in recorder.command.await_args_list]
    assert calls[1] == ("-s", "192.0.2.1:5555", "shell", "getprop", "ro.serialno")
    assert calls[2][-1] == "getprop"
    assert calls[3][-1] == str(recorder.helper)
    starts = [call for call in calls if "start-foreground-service" in call]
    assert starts == [("-s", "192.0.2.1:5555", "shell", "am", "start-foreground-service",
                       "-n", "org.immensiva.recording/.RecordingService", "--es", "request", REQUEST, "--es", "action", "start")]
    # Even a new request is rejected during the cooldown, before touching the headset.
    with pytest.raises(ValueError, match="Wait a few seconds"):
        await recorder.set_state(DEVICE, "start", "c" * 32)
    assert recorder.command.await_count == len(calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("serial,install,error", [
    ("wrong-headset", None, "identity"), ("one", "Failure [DENIED]", "installation failed"),
])
async def test_identity_and_install_failures_never_toggle(recorder, serial, install, error):
    recorder.command = AsyncMock(side_effect=["connected", serial, STOPPED, install])
    with pytest.raises(RuntimeError, match=error):
        await recorder.set_state(DEVICE, "start", REQUEST)
    assert not any("start-foreground-service" in call.args for call in recorder.command.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["FAILED SecurityException: device owner restriction", None])
async def test_unconfirmed_request_is_not_retried(recorder, reply):
    response = "RESULT " + REQUEST + " " + reply if reply else "unrelated log entry"
    recorder.command = AsyncMock(side_effect=["connected", "one", STOPPED, "Success", "Starting service"] + [response] * 60)
    with patch("immensiva_mdm.recording.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="Check the headset before retrying"):
            await recorder.set_state(DEVICE, "start", REQUEST)
    assert sum("start-foreground-service" in call.args for call in recorder.command.await_args_list) == 1


@pytest.mark.asyncio
async def test_bad_offline_busy_and_unconfigured_requests_do_not_use_adb(recorder):
    recorder.command = AsyncMock()
    for device, request in [(DEVICE, None), (DEVICE, "shell; command"), ({**DEVICE, "status": "offline"}, REQUEST)]:
        with pytest.raises(ValueError):
            await recorder.set_state(device, "start", request)
    lock = recorder.locks.setdefault("one", asyncio.Lock())
    async with lock:
        with pytest.raises(ValueError, match="already in progress"):
            await recorder.set_state(DEVICE, "start", REQUEST)
    recorder.helper.unlink()
    with pytest.raises(ValueError, match="tools are missing"):
        await recorder.set_state(DEVICE, "start", REQUEST)
    recorder.command.assert_not_awaited()


@pytest.mark.asyncio
async def test_mdm_route_uses_connected_device_and_rejects_cross_origin(tmp_path):
    server.upstream._apply_data_dir(str(tmp_path / "mdm"))
    server.upstream.devices.clear()
    server.upstream.device_registry.clear()
    fake = AsyncMock()
    fake.available = True
    fake.state.return_value = {"state": "stopped"}
    fake.set_state.return_value = {"status": "confirmed", "state": "recording", "changed": True, "message": MESSAGE}
    with patch.object(server, "PicoRecorder", return_value=fake):
        async with TestClient(TestServer(server.create_app())) as client:
            assert (await (await client.get("/api/screen-recording")).json())["available"]
            assert (await client.get("/api/screen-recording?device_id=one")).status == 409
            body = {"device_id": "one", "action": "start", "request_id": REQUEST}
            response = await client.post("/api/screen-recording", json=body)
            assert response.status == 409
            server.upstream.devices["one"] = DEVICE.copy()
            status = await client.get("/api/screen-recording?device_id=one")
            assert (await status.json()) == {"state": "stopped"}
            assert status.headers["Cache-Control"] == "no-store"
            fake.state.assert_awaited_once_with(DEVICE)
            fake.state.side_effect = RuntimeError("Recording state is unavailable")
            status = await client.get("/api/screen-recording?device_id=one")
            assert status.status == 400 and (await status.json())["state"] == "unknown"
            fake.set_state.assert_not_awaited()
            response = await client.post("/api/screen-recording", json=body, headers={"Origin": "http://other.invalid"})
            assert response.status == 403
            fake.set_state.assert_not_awaited()
            for invalid in [[], {"device_id": []}, {}]:
                assert (await client.post("/api/screen-recording", json=invalid)).status == 400
            response = await client.post("/api/screen-recording", json=body)
            assert response.status == 200
            assert (await response.json())["status"] == "confirmed"
            fake.set_state.assert_awaited_once_with(DEVICE, "start", REQUEST)
            html = await (await client.get("/")).text()
            assert 'id="btnRecordStart"' in html
            assert 'id="btnRecordStop"' in html
            assert 'data-task="recording"' in html
    server.upstream.devices.clear()


@pytest.mark.asyncio
async def test_live_ops_recording_does_not_enable_capture_or_positioning(tmp_path):
    monitor = Monitor(tmp_path, Path("adb"), Path("scrcpy"), "http://localhost")
    monitor.connected = True
    monitor.devices = [DEVICE.copy()]
    for name in ("feed", "timers", "refresh_displays", "refresh_foreground", "address", "command"):
        setattr(monitor, name, AsyncMock())
    monitor.recorder.set_state = AsyncMock(return_value={"message": MESSAGE})
    monitor.recorder.state = AsyncMock(return_value={"state": "stopped"})
    async with TestClient(TestServer(create_app(monitor))) as client:
        body = {"device_id": "one", "action": "record_start", "request_id": REQUEST}
        response = await client.post("/api/action", json=body)
        assert response.status == 200
        monitor.recorder.set_state.assert_awaited_once_with(DEVICE, "start", REQUEST)
        state = await (await client.get("/api/state")).json()
        assert set(state["disabled_actions"]) == {"track", "view"}
        assert state["events"][-1]["message"] == MESSAGE
        status = await client.post("/api/action", json={"device_id": "one", "action": "recording_status"})
        assert (await status.json())["state"] == "stopped"
        assert (await (await client.get("/api/state")).json())["events"] == state["events"]
        monitor.connected = False
        assert (await client.post("/api/action", json=body)).status == 409
    monitor.address.assert_not_awaited()
    monitor.command.assert_not_awaited()
    assert monitor.viewer is None
    assert monitor.tasks == {}
    config = {"address": "192.0.2.10", "key": "test"}
    async with TestClient(TestServer(create_app(monitor, config, touch_only=True))) as client:
        response = await client.post("/api/action", json=body, headers={
            "Host": "192.0.2.10:7081", "Authorization": "Bearer test"})
        assert response.status == 403
    assert monitor.recorder.set_state.await_count == 1
