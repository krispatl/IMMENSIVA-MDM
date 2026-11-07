"""Brand and operator UX adapter; upstream device protocol stays unchanged."""
from pathlib import Path
from html import escape
import importlib.metadata, json, os
from ipaddress import ip_address
import posixpath
from aiohttp import web
from yarl import URL
import styly_mdm
from styly_mdm import server as upstream

from .catalog import PACKAGES

WEB=Path(__file__).resolve().parent/'web'
VERSION='1.1.0'


def validate_headset_destination(destination):
    """Android destinations use POSIX paths even when the MDM runs on Windows."""
    text = destination.strip() if isinstance(destination, str) else ''
    if not text:
        return 'Destination path is required'
    if '\x00' in text or '\\' in text:
        return 'Destination path contains an invalid character'
    if not text.startswith('/'):
        return 'Destination must be an absolute path'
    if '..' in text.split('/'):
        return "Destination path must not contain '..'"
    normalized = posixpath.normpath('/' + text.lstrip('/')).rstrip('/') + '/'
    prefix = next((prefix for prefix in upstream.SHARED_STORAGE_PREFIXES if normalized.startswith(prefix)), None)
    if prefix is None:
        return 'Destination must be under shared storage (/sdcard or /storage/emulated/0)'
    remainder = normalized[len(prefix):].strip('/')
    if not remainder:
        return 'Destination must be a subdirectory, not the shared-storage root'
    first_directory = remainder.split('/', 1)[0].lower()
    if first_directory in upstream.PROTECTED_TOPLEVEL_DIRS:
        return f"Destination must not be inside the protected '{first_directory}' directory"
    return None

def console_html():
    source=(Path(styly_mdm.__file__).parent/'static/index.html').read_text(encoding='utf-8')
    for marker in ['id="serverVersion"','id="targetsBody"','id="btnLaunch"','id="btnInstall"']:
        if marker not in source:raise RuntimeError('Unsupported STYLY-MDM console layout: '+marker)
    source=source.replace('<title>STYLY-MDM - Device Management</title>','<title>IMMENSIVA MDM · ESPRONCEDA</title>')
    source=source.replace('</head>','<link rel="stylesheet" href="/brand/theme.css"><link rel="stylesheet" href="/brand/operator.css"><script src="/brand/venue.js" defer></script></head>')
    source=source.replace('<div class="shell">',(WEB/'masthead.html').read_text(encoding='utf-8')+'<div class="shell">',1)
    source=source.replace('<div class="brand">STYLY-<span>MDM</span><span class="brand-version" id="serverVersion"></span></div>',
        '<div class="brand"><span class="brand-label">VENUE CONSOLE</span><span class="brand-version" id="serverVersion"></span></div>')
    source=source.replace('① Targets','Choose your headsets').replace('② Actions','Choose an action')
    source=source.replace('Quick Install','Install an experience').replace('Launch Command','Open an experience')
    source=source.replace('>Launch to Selected<','>Open on selected headsets<')
    source=source.replace('Manage Groups','Manage rooms').replace('No APK selected','Choose an Android app (.apk)')
    source=source.replace('placeholder="com.example.app"','placeholder="App package, e.g. com.fifthyang.lordlyrical"')
    source=source.replace('placeholder="/sdcard/STYLY/content"','placeholder="/sdcard/IMMENSIVA/content"')
    source=source.replace("return (d.label || '').toLowerCase().indexOf(q) !== -1;", "return [d.label,getDeviceId(d),d.model,d.ip].filter(Boolean).join(' ').toLowerCase().indexOf(q) !== -1;")
    source=source.replace('Filter devices by name…','Find by name, ID or IP…')
    # Use the existing authority-backed UI state; do not open a second admin socket.
    source=source.replace('function render() {','function render() {\n        document.dispatchEvent(new CustomEvent("venue:state", {detail:{devices:devices,selected:Array.from(selectedIds),groups:groups}}));',1)
    options = '\n'.join(f'<option value="{escape(package)}">{escape(name)}</option>' for package, name in PACKAGES.items())
    tasks = (WEB/'tasks.html').read_text(encoding='utf-8').replace('{{EXPERIENCE_OPTIONS}}', options)
    source=source.replace('<div class="commands">',tasks+'<div class="commands">',1)
    source=source.replace('</body>',(WEB/'operator-dialog.html').read_text(encoding='utf-8')+(WEB/'footer.html').read_text(encoding='utf-8')+'</body>')
    return source

@web.middleware
async def branding(request, handler):
    instance = os.environ.get('IMMENSIVA_SUITE_INSTANCE')
    local_authority = request.host.split(':', 1)[0] in {'localhost', '127.0.0.1'}
    if instance and (request.path in {'/', '/guide', '/ws/admin'} or request.path.startswith('/api/')):
        if request.remote not in {'127.0.0.1', '::1'}:
            raise web.HTTPForbidden()
        bridge = request.path in {'/api/apks', '/api/bundles'} and request.headers.get('X-Venue-Suite') == instance
        if not local_authority and not bridge:
            raise web.HTTPForbidden()
        if request.method == 'POST' or request.path == '/ws/admin':
            origin = request.headers.get('Origin')
            if origin is not None and origin != 'http://' + request.host:
                raise web.HTTPForbidden()
    if request.path=='/' and request.method in ('GET','HEAD'):
        return web.Response(text=console_html(),content_type='text/html',headers={'Cache-Control':'no-store'})
    if request.path=='/health':
        payload = dict(product='IMMENSIVA MDM',version=VERSION,backend='STYLY-MDM',backendVersion=importlib.metadata.version('styly-mdm'))
        if instance and local_authority and request.remote in {'127.0.0.1', '::1'}:
            payload['instance'] = instance
        return web.json_response(payload)
    if request.path=='/guide':return web.FileResponse(WEB/'guide.html')
    if request.method == 'POST' and request.path == '/api/apks':
        # Upstream uses the request authority in the URL sent to headsets.
        url = URL.build(scheme=request.scheme, authority=request.host)
        try:
            loopback = ip_address(url.host).is_loopback
        except ValueError:
            loopback = url.host == 'localhost'
        if loopback:
            addresses = upstream.get_local_ip_addresses()
            if len(addresses) == 1:
                request = request.clone(host=url.with_host(addresses[0]).authority)
    return await handler(request)

def create_app():
    if os.name == 'nt':
        upstream.validate_dest_path = validate_headset_destination
    app=_original_create_app()
    app.middlewares.insert(0,branding)
    app.router.add_static('/brand',WEB)
    return app

_original_create_app=upstream.create_app

def main():
    # Preserve the vendor CLI, discovery guard, durable registry, transfer
    # scheduler, signed client seeding and all HTTP/WebSocket handlers.
    upstream.create_app=create_app
    upstream.main()

if __name__=='__main__':main()
