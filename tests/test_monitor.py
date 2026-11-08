import asyncio
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from immensiva_mdm.monitor import Monitor, create_app, decode_sample, equivalent_outline


class SampleTests(unittest.TestCase):
    def test_reversed_pico_outline_with_small_coordinate_noise_is_equivalent(self):
        original = [{"x": 0, "z": 0}, {"x": 4, "z": 0}, {"x": 0, "z": 4}]
        reversed_outline = [
            {"x": 4.002, "z": 0}, {"x": 0, "z": 0}, {"x": 0, "z": 4}, {"x": 4.002, "z": 0}]
        self.assertTrue(equivalent_outline(original, reversed_outline))
        reversed_outline[2]["z"] = 4.3
        self.assertFalse(equivalent_outline(original, reversed_outline))

    def test_large_room_packet_and_other_runs(self):
        sample = {"run": "current", "boundary": {"points": [{"x": n, "z": n / 2} for n in range(500)]}}
        encoded = base64.b64encode(json.dumps(sample).encode()).decode()
        chunks = [encoded[offset:offset + 3000] for offset in range(0, len(encoded), 3000)]
        pending = {}
        self.assertIsNone(decode_sample("PACKET old 1 0 1 ignored", "current", pending))
        result = None
        for index, chunk in enumerate(chunks):
            result = decode_sample(
                f"PACKET current 1 {index} {len(chunks)} {chunk}", "current", pending)
            if index < len(chunks) - 1:
                self.assertIsNone(result)
        self.assertEqual(result, sample)


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.monitor = Monitor(Path(self.temporary.name), Path("adb"), Path("scrcpy"), "http://localhost")
        self.monitor.connected = True
        self.monitor.devices = [
            dict(device_id="one", label="One", ip="192.0.2.1", status="online"),
            dict(device_id="two", label="Two", ip="192.0.2.2", status="online"),
            dict(device_id="offline", label="Offline", ip="192.0.2.3", status="offline"),
        ]
        self.monitor.address = AsyncMock(return_value="192.0.2.1:5555")

    async def test_disabled_monitoring_methods_do_not_connect_or_start_processes(self):
        self.monitor.command = AsyncMock()
        with patch("immensiva_mdm.monitor.asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            for method in (self.monitor.start_tracking, self.monitor.view):
                with self.subTest(method=method.__name__):
                    with self.assertRaises(web.HTTPForbidden):
                        await method("one")
            spawn.assert_not_awaited()
        self.monitor.address.assert_not_awaited()
        self.monitor.command.assert_not_awaited()
        self.assertEqual(self.monitor.tasks, {})
        self.assertIsNone(self.monitor.viewer)

    async def test_disabled_monitoring_api_rejects_requests_before_device_work(self):
        for task in ("feed", "timers", "refresh_displays", "refresh_foreground"):
            setattr(self.monitor, task, AsyncMock())
        self.monitor.command = AsyncMock()
        async with TestClient(TestServer(create_app(self.monitor))) as client:
            snapshot = await (await client.get("/api/state")).json()
            self.assertEqual(set(snapshot["disabled_actions"]), {"track", "view"})
            for action in ("track", "view"):
                with self.subTest(action=action):
                    response = await client.post("/api/action", json={"device_id": "one", "action": action})
                    self.assertEqual(response.status, 403)
                    self.assertEqual(await response.json(), {"error": snapshot["disabled_actions"][action]})
        self.monitor.address.assert_not_awaited()
        self.monitor.command.assert_not_awaited()
        self.assertEqual(self.monitor.tasks, {})
        self.assertIsNone(self.monitor.viewer)

    async def test_stop_feed_remains_available_during_monitoring_hold(self):
        for task in ("feed", "timers", "refresh_displays", "refresh_foreground"):
            setattr(self.monitor, task, AsyncMock())
        collector = asyncio.create_task(asyncio.Event().wait())
        self.monitor.tasks["one"] = collector
        async with TestClient(TestServer(create_app(self.monitor))) as client:
            response = await client.post("/api/action", json={"device_id": "one", "action": "stop_tracking"})
            self.assertEqual(response.status, 200)
            self.assertTrue(collector.cancelled())

    async def test_touch_listener_requires_key_and_limits_device_actions(self):
        config = {"address": "192.0.2.10", "key": "example-venue-access"}
        host = {"Host": "192.0.2.10:7081"}
        allowed = {**host, "Authorization": "Bearer " + config["key"]}
        self.monitor.set_display = AsyncMock()
        async with TestClient(TestServer(create_app(self.monitor, config, touch_only=True))) as client:
            self.assertEqual((await client.get("/api/heads-up", headers=host)).status, 401)
            self.assertEqual((await client.get("/api/heads-up", headers=allowed)).status, 200)
            self.assertEqual((await client.post("/api/shutdown", json={}, headers=allowed)).status, 404)
            self.assertEqual((await client.post("/api/home-menu", json={"mode": "restore"}, headers=allowed)).status, 404)
            body = {"device_id": "one", "action": "track"}
            self.assertEqual((await client.post("/api/action", json=body, headers=allowed)).status, 403)
            body["action"] = "display_off"
            wrong_origin = {**allowed, "Origin": "http://192.0.2.11:7081"}
            self.assertEqual((await client.post("/api/action", json=body, headers=wrong_origin)).status, 403)
            self.assertEqual((await client.post("/api/action", json=body, headers=allowed)).status, 200)
            self.monitor.set_display.assert_awaited_once_with("one", on=False)

    async def test_home_menu_reports_partial_fleet_results(self):
        root = self.monitor.state_path.parent
        tools = root / "monitor-tools"
        tools.mkdir()
        (tools / "home-menu-policy.py").write_text(
            "import json, sys\n"
            "assert sys.argv[1:] == ['restore', '--json-stdin']\n"
            "snapshot = json.load(sys.stdin)\n"
            "assert snapshot['connected']\n"
            "statuses = {'one': 'RESTORED policy', 'two': 'FAILED readback', 'offline': 'SKIPPED offline'}\n"
            "print(json.dumps([dict(d, result=statuses[d['device_id']]) for d in snapshot['devices']]))\n",
            encoding="utf-8")
        for task in ("feed", "timers", "refresh_displays", "refresh_foreground"):
            setattr(self.monitor, task, AsyncMock())
        with patch("immensiva_mdm.monitor.ROOT", root):
            async with TestClient(TestServer(create_app(self.monitor))) as client:
                self.assertEqual((await client.post("/api/home-menu", json={"mode": "toggle"})).status, 400)
                response = await client.post("/api/home-menu", json={"mode": "restore"})
                self.assertEqual(response.status, 200)
                result = await response.json()
                self.assertEqual((result["confirmed"], result["skipped"], result["failed"]), (1, 1, 1))
                snapshot = await (await client.get("/api/state")).json()
                self.assertEqual(snapshot["home_menu"], result)
                self.assertFalse(snapshot["home_menu_busy"])
                self.assertEqual([e["device"] for e in snapshot["events"] if e["kind"] == "problem"], ["two"])

    async def test_measured_outline_persists_by_map_and_preserves_pico_boundary(self):
        raw = [{"x": 0, "z": 0}, {"x": 4, "z": 0}, {"x": 0, "z": 4}]
        measured = [{"x": 1, "z": 1}, {"x": 3, "z": 1}, {"x": 1, "z": 3}]
        self.monitor.rooms["map-a"] = {"points": raw}
        for task in ("feed", "timers", "refresh_displays", "refresh_foreground"):
            setattr(self.monitor, task, AsyncMock())
        async with TestClient(TestServer(create_app(self.monitor))) as client:
            saved = await client.post("/api/room-outline", json={"fingerprint": "map-a", "points": measured})
            self.assertEqual(saved.status, 200)
            invalid = await client.post("/api/room-outline", json={
                "fingerprint": "map-a", "points": [measured[0]] * 3})
            self.assertEqual(invalid.status, 400)
            data = json.loads(self.monitor.state_path.read_text())
            self.assertEqual(data["measured_rooms"]["map-a"], measured)
            self.assertEqual(data["rooms"]["map-a"]["points"], raw)
            restored = await client.post("/api/room-outline", json={"fingerprint": "map-a", "points": None})
            self.assertEqual(restored.status, 200)
            self.assertEqual(self.monitor.measured_rooms, {})

    async def test_stop_only_registered_experience_processes(self):
        self.monitor.command = AsyncMock(side_effect=[
            "NAME\ncom.FacingWorlds.ModernFossils\ncom.styly.mdmclient\norg.immensiva.monitorprobe\ncom.other.app",
            "",
            "NAME\ncom.styly.mdmclient\norg.immensiva.monitorprobe\ncom.other.app",
        ])
        result = await self.monitor.stop_experience("one")
        self.assertEqual(result, ["com.FacingWorlds.ModernFossils"])
        stops = [call.args[-1] for call in self.monitor.command.await_args_list if "force-stop" in call.args]
        self.assertEqual(stops, ["com.FacingWorlds.ModernFossils"])

    async def test_stop_with_no_registered_app_is_noop(self):
        self.monitor.command = AsyncMock(return_value="NAME\ncom.styly.mdmclient\norg.immensiva.monitorprobe")
        self.assertEqual(await self.monitor.stop_experience("one"), [])
        self.assertEqual(self.monitor.command.await_count, 1)

    async def test_partial_stop_finishes_matching_timer_before_later_failure(self):
        self.monitor.sessions["one"] = dict(
            package="com.FacingWorlds.ModernFossils", status="running",
            elapsed=0, started=time.time() - 1, duration=60)
        self.monitor.command = AsyncMock(side_effect=[
            "com.FacingWorlds.ModernFossils\ncom.Immersiva.RELATS",
            "",
            "com.Immersiva.RELATS",
            RuntimeError("ADB connection lost"),
        ])
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            await self.monitor.stop_experience("one")
        self.assertEqual(self.monitor.sessions["one"]["status"], "finished")
        saved = json.loads(self.monitor.state_path.read_text())
        self.assertEqual(saved["sessions"]["one"]["status"], "finished")
        self.assertEqual(saved["events"][-1]["message"], "Stopped Modern Fossils")

    async def test_bulk_blackout_keeps_partial_results_and_skips_offline(self):
        async def display(device_id, on):
            if device_id == "two":
                raise RuntimeError("Disconnected")
        self.monitor.set_display = AsyncMock(side_effect=display)
        result = await self.monitor.group_action("display_off")
        self.assertEqual((result["succeeded"], result["failed"], result["skipped"]), (1, 1, 1))
        self.assertEqual({call.args[0] for call in self.monitor.set_display.await_args_list}, {"one", "two"})

    async def test_restore_includes_previously_controlled_disconnected_devices(self):
        self.monitor.connected = False
        self.monitor.displays = {"offline": {"state": "off"}}
        self.monitor.set_display = AsyncMock()
        result = await self.monitor.group_action("display_on")
        self.assertEqual(result["succeeded"], 1)
        self.monitor.set_display.assert_awaited_once_with("offline", True)

    async def test_display_read_ignores_virtual_displays(self):
        self.monitor.command = AsyncMock(return_value=(
            "  Display 42\n    connectionType=Internal\n    powerMode=Off\n"
            "  Virtual Display 55\n    powerMode=On\n"))
        self.assertEqual(await self.monitor.read_display("address"), "off")

    async def test_unconfirmed_blackout_is_not_reported_as_success(self):
        self.monitor.command = AsyncMock(return_value="IMMENSIVA_DISPLAY off")
        self.monitor.read_display = AsyncMock(return_value="on")
        with self.assertRaisesRegex(RuntimeError, "could not be confirmed"):
            await self.monitor.set_display("one", False)
        self.assertEqual(self.monitor.displays["one"]["state"], "on")
        self.assertEqual(self.monitor.events[-1]["kind"], "problem")


if __name__ == "__main__":
    unittest.main()
