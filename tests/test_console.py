import asyncio,io,zipfile
import pytest
from aiohttp import ClientSession,FormData
from aiohttp.test_utils import TestServer
from immensiva_mdm import server

@pytest.fixture
def app(tmp_path):
    server.upstream._apply_data_dir(str(tmp_path/'mdm'))
    server.upstream.devices.clear();server.upstream.device_registry.clear()
    return server.create_app()

@pytest.mark.asyncio
async def test_branding_and_preserved_protocol(app):
    async with TestServer(app) as s,ClientSession() as c:
        async with c.get(s.make_url('/')) as r:
            html=await r.text();assert r.status==200 and 'IMMENSIVA MDM' in html
            for id in ['btnLaunch','btnInstall','btnSync','syncConfirm','btnManageGroups','serverVersion']:assert f'id="{id}"' in html
            assert '/static/push-jobs-v1.js' in html
        for path in ['/brand/assets/espronceda.webp','/brand/assets/immensiva.png','/brand/assets/styly-white.png','/brand/theme.css','/brand/venue.js','/guide']:
            async with c.get(s.make_url(path)) as r:assert r.status==200,path
        async with c.get(s.make_url('/health')) as r:
            data=await r.json();assert data['product']=='IMMENSIVA MDM' and data['backendVersion']=='0.6.0'
        ws=await c.ws_connect(s.make_url('/ws/admin'));messages=[];required={'SERVER_INFO','CLIENT_APK_INFO','DEVICE_LIST','GROUP_LIST'}
        for _ in range(12):
            messages.append(await ws.receive_json(timeout=3))
            if required<={m['type'] for m in messages}:break
        assert required<={m['type'] for m in messages}
        await ws.close()

@pytest.mark.asyncio
async def test_group_and_selected_device_launch(app):
    async with TestServer(app) as s,ClientSession() as c:
        a=await c.ws_connect(s.make_url('/ws/device'));b=await c.ws_connect(s.make_url('/ws/device'))
        for ws,id in [(a,'fixture-studio'),(b,'fixture-gallery')]:
            await ws.send_json(dict(type='REGISTER',device_id=id,model='PICO fixture',version_name='0.6.0'))
            assert (await ws.receive_json(timeout=3))['type']=='REGISTERED'
        admin=await c.ws_connect(s.make_url('/ws/admin'))
        await admin.send_json(dict(type='CREATE_GROUP',name='Studio'))
        while (await admin.receive_json(timeout=3))['type']!='GROUP_CREATED':pass
        await admin.send_json(dict(type='SET_GROUP_MEMBERS',name='Studio',members=['fixture-studio']))
        while (await admin.receive_json(timeout=3))['type']!='GROUP_MEMBERS_SET':pass
        await admin.send_json(dict(type='LAUNCH_APP',target_devices=['fixture-studio'],package_name='com.fifthyang.lordlyrical',extra_data='{}'))
        msg=await a.receive_json(timeout=3);assert msg['type']=='EXECUTE_LAUNCH' and msg['package_name']=='com.fifthyang.lordlyrical'
        with pytest.raises(asyncio.TimeoutError):await b.receive_json(timeout=.15)
        await a.close();await b.close();await admin.close()

@pytest.mark.asyncio
async def test_apk_upload_and_download(app, monkeypatch):
    monkeypatch.setattr(server.upstream, 'get_local_ip_addresses', lambda: ['192.0.2.10'])
    # Protocol fixture only: never sent to a physical headset or claimed installable.
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:z.writestr('AndroidManifest.xml','fixture')
    payload=data.getvalue();form=FormData();form.add_field('apk',payload,filename='protocol-fixture.apk',content_type='application/vnd.android.package-archive')
    async with TestServer(app) as s,ClientSession() as c:
        async with c.post(s.make_url('/api/apks'),data=form) as r:
            assert r.status==200;value=await r.json()
        download = s.make_url('/apks/' + value['apk_filename'])
        assert value['apk_url'] == str(download.with_host('192.0.2.10'))
        async with c.get(download) as r:assert await r.read()==payload
