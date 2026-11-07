"""Smoke test a disposable, running pilot with simulated headsets only."""
import argparse
import asyncio
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from aiohttp import ClientSession, FormData

PACKAGE = "com.fifthyang.lordlyrical.offline"


async def verify(args):
    async with ClientSession() as client:
        async def state():
            async with client.get(args.desktop + "/api/state") as response:
                response.raise_for_status()
                return await response.json()

        async def expect(predicate, description):
            for _ in range(60):
                snapshot = await state()
                if predicate(snapshot):
                    return snapshot
                await asyncio.sleep(.1)
            raise AssertionError(description)

        async def post(path, status=200, **kwargs):
            async with client.post(args.desktop + path, **kwargs) as response:
                body = await response.text()
                assert response.status == status, (path, response.status, body)
                return json.loads(body)

        async def receive(ws, kind):
            while True:
                message = await ws.receive_json(timeout=3)
                if message["type"] == kind:
                    return message

        async def register(ws, serial):
            await ws.send_json(dict(type="REGISTER", device_id=serial, model="PICO fixture", version_name="0.6.0"))
            await receive(ws, "REGISTERED")

        snapshot = await state()
        assert snapshot["suite"] and not snapshot["devices"], "Use a fresh disposable suite, with no other headsets."
        first, second = ("fixture-" + uuid4().hex[:8] for _ in range(2))

        async def result(job, status):
            def matches(snapshot):
                return any(operation["id"] == job["id"] and operation["results"][first]["status"] == status
                           for operation in snapshot["operations"])
            snapshot = await expect(matches, status)
            return next(operation["results"][first] for operation in snapshot["operations"] if operation["id"] == job["id"])

        async with client.ws_connect(args.mdm + "/ws/device") as a, client.ws_connect(args.mdm + "/ws/device") as b:
            await register(a, first)
            await register(b, second)
            await expect(lambda s: sum(d["status"] == "online" for d in s["devices"]) == 2, "both fixtures online")
            await post("/api/suite/group", json={"name": "Pilot room", "members": [first]})
            await expect(lambda s: s["groups"].get("Pilot room") == [first], "room membership")
            launch = await post("/api/suite/operation/launch", 202, json={"targets": [first], "package": PACKAGE})
            assert (await receive(a, "EXECUTE_LAUNCH"))["package_name"] == PACKAGE
            try:
                await asyncio.wait_for(receive(b, "EXECUTE_LAUNCH"), .3)
            except asyncio.TimeoutError:
                pass
            else:
                raise AssertionError("Excluded headset received launch")
            await a.send_json(dict(type="LAUNCH_RESULT", package_name=PACKAGE, status="success"))
            await result(launch, "Confirmed")
            assert not (await state())["sessions"]
            await b.close()
            await expect(lambda s: any(d["device_id"] == second and d["status"] == "offline" for d in s["devices"]), "offline fixture")

            apk = io.BytesIO()
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("AndroidManifest.xml", "simulated transfer fixture")
            form = FormData()
            form.add_field("apk", apk.getvalue(), filename="simulated.apk", content_type="application/vnd.android.package-archive")
            install = await post(f"/api/suite/operation/install?target={first}&target={second}", 202, data=form)
            assert install["results"][second]["status"] == "Skipped"
            message = await receive(a, "EXECUTE_INSTALL")
            assert message["apk_url"].startswith(args.mdm + "/apks/")
            async with client.get(message["apk_url"]) as response:
                assert response.status == 200 and await response.read() == apk.getvalue()
            await a.send_json(dict(type="DOWNLOAD_COMPLETE", apk_filename=message["apk_filename"]))
            assert (await result(install, "Installing"))["transfer"] == "Complete"
            await a.send_json(dict(type="INSTALL_RESULT", apk_filename=message["apk_filename"],
                                   status="fail", error="Fixture install failed"))
            assert (await result(install, "Failed"))["transfer"] == "Complete"

            form = FormData()
            form.add_field("files", b"example", filename="fixture.txt", content_type="text/plain")
            destination = "/sdcard/IMMENSIVA/content"
            push = await post(f"/api/suite/operation/files?target={first}&destination={destination}", 202, data=form)
            message = await receive(a, "EXECUTE_PUSH_FILES")
            assert message["bundle_url"].startswith(args.mdm + "/bundles/") and not message["delete_extras"]
            async with client.get(message["bundle_url"]) as response:
                assert response.status == 200
                with zipfile.ZipFile(io.BytesIO(await response.read())) as archive:
                    assert archive.read("fixture.txt") == b"example"
            await a.send_json(dict(type="DOWNLOAD_COMPLETE", task="push", dest_path=destination))
            await result(push, "Applying")
            await a.send_json(dict(type="PUSH_FILES_RESULT", dest_path=destination, status="success"))
            await result(push, "Confirmed")
            await post("/api/suite/durations", json={PACKAGE: 7.5})
            await post("/api/action", json=dict(action="start", device_id=first, package=PACKAGE))
            assert (await state())["sessions"][first]["duration"] == 450

        async with client.get(args.mdm + "/") as response:
            assert response.status == 403
        if args.touch_config:
            config = json.loads(args.touch_config.read_text(encoding="utf-8"))
            touch = f'http://{config["address"]}:{config["port"]}'
            headers = {"Authorization": "Bearer " + config["key"]}
            async with client.get(touch + "/api/heads-up") as response:
                assert response.status == 401
            async with client.get(touch + "/api/heads-up", headers=headers) as response:
                assert response.status == 200
            for path in ("/api/home-menu", "/api/suite/durations", "/api/suite/operation/launch", "/api/shutdown"):
                async with client.post(touch + path, headers=headers, json={}) as response:
                    assert response.status == 404, (path, response.status)
            async with client.get(args.desktop + "/touch-setup") as response:
                assert "Venue pairing QR code" in await response.text()
    print("Passed simulated room targeting, launch, APK phases, file push, timer and network access checks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", default="http://127.0.0.1:17082")
    parser.add_argument("--mdm", required=True, help="LAN URL of the disposable suite MDM")
    parser.add_argument("--touch-config", type=Path)
    asyncio.run(verify(parser.parse_args()))
