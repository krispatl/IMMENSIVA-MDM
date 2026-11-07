const paths = {
  headset: '<path d="M4 8h16l2 8a2 2 0 0 1-2 2h-4l-4-3-4 3H4a2 2 0 0 1-2-2l2-8Z"/><path d="m7 8 1-3h8l1 3M7 12h1m8 0h1"/>',
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V10Z"/><path d="M9 21v-7h6v7"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  arrow: '<path d="M6 18 18 6M6 6h12v12"/>',
  signal: '<path d="M4 18v3m5-8v8m6-13v13m5-18v18"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  dark: '<path d="M21 13a9 9 0 0 1-10-10 9 9 0 1 0 10 10Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="3"/>',
  alert: '<path d="M10 4 2 18a2 2 0 0 0 2 3h16a2 2 0 0 0 2-3L14 4a2 2 0 0 0-4 0Z"/><path d="M12 9v4m0 4v.01"/>',
  map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Zm6-3v15m6-12v15"/>',
  fit: '<path d="M3 9V3h6m6 0h6v6m0 6v6h-6M9 21H3v-6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.01"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  play: '<path d="m8 4 12 8-12 8V4Z"/>',
  pause: '<path d="M8 4v16M16 4v16"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  reset: '<path d="M3 10a9 9 0 1 1 1 7M3 4v6h6"/>',
  pin: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  target: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  battery: '<rect x="2" y="6" width="18" height="12" rx="3"/><path d="M23 10v4M6 10v4m4-4v4m4-4v4"/>',
  bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z"/>'
};
const byId = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
let state = null;
let selected = null;
let fleetFilter = 'all';
let eventFilter = 'all';
let clockOffset = 0;
let bulkBusy = false;
let homeMenuPending = null;
let pollBusy = false;
let packagesLoaded = false;
let timerEdited = false;
let eventSignature = '';
const busyDevices = new Set();
const cards = new Map();
const mapMarkers = new Map();
let measurement = null;
let savingOutline = false;
let fittedRoom = null;

function svgNode(tag, attributes = {}, text) {
  const node = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const node = svgNode('svg', {viewBox: '0 0 24 24', class: 'icon', 'aria-hidden': 'true'});
  node.innerHTML = paths[name] || paths.info;
  return node;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

document.querySelectorAll('[data-icon]').forEach(node => node.append(icon(node.dataset.icon)));
const mapBase = svgNode('g');
const mapMarkerLayer = svgNode('g');
byId('room').replaceChildren(mapBase, mapMarkerLayer);

function label(deviceId) {
  return state.devices.find(device => device.device_id === deviceId)?.label || deviceId || 'System';
}

function online(device) {
  return state.connected && device.status === 'online';
}

function elapsed(session) {
  if (!session) return 0;
  const additional = session.status === 'running'
    ? Math.max(0, Date.now() / 1000 + clockOffset - session.started)
    : 0;
  return session.elapsed + additional;
}

function timeText(value) {
  const total = Math.max(0, Math.ceil(value));
  return String(Math.floor(total / 60)).padStart(2, '0') + ':' + String(total % 60).padStart(2, '0');
}

function displayState(deviceId) {
  const display = state.displays[deviceId];
  if (!display || state.now - display.checked_at > 20) return 'unknown';
  return display.state;
}

function freshPosition(device) {
  const sample = state.poses[device.device_id];
  return online(device) && sample && state.now - sample.received < 4;
}

function deviceStatus(device) {
  if (!state.connected) return ['MDM unavailable', 'danger'];
  if (!online(device)) return ['Offline', 'neutral'];
  if (displayState(device.device_id) === 'off') return ['Blacked out', 'blackout'];
  const display = state.displays[device.device_id];
  if (display && displayState(device.device_id) === 'unknown') return ['Check display', 'warning'];
  const session = state.sessions[device.device_id];
  if (!session) return ['Connected', 'success'];
  if (session.status === 'running' && elapsed(session) >= session.duration) return ['Duration reached', 'warning'];
  const captions = {running: 'Timer running', paused: 'Timer paused', finished: 'Session finished'};
  return [captions[session.status] || 'Connected', session.status === 'running' ? 'success' : 'neutral'];
}

function needsAttention(device) {
  return window.fleetStatus.status(state, device).attention;
}

function notify(message) {
  byId('messageText').textContent = message;
  byId('message').hidden = !message;
}

function selectDevice(deviceId) {
  selected = deviceId;
  timerEdited = false;
  syncTimerSelection();
  render();
}

function actionButton(caption, image, action, deviceId, style) {
  const button = element('button', undefined, 'button ' + style);
  button.append(icon(image), element('span', caption));
  button.dataset.cardAction = action;
  button.setAttribute('aria-label', caption + ' · ' + label(deviceId));
  button.onclick = () => runAction(deviceId, action);
  return button;
}

function createCard(device) {
  const key = device.device_id;
  const root = element('article', undefined, 'headset-card');
  const select = element('button', undefined, 'card-select');
  const image = element('span', undefined, 'card-headset');
  image.append(icon('headset'));
  const title = element('span', undefined, 'card-title');
  const name = element('strong');
  const address = element('small');
  title.append(name, address);
  const battery = element('span', undefined, 'battery');
  const batteryText = element('span');
  battery.append(icon('battery'), batteryText);
  select.append(image, title, battery);
  select.onclick = () => selectDevice(key);
  const statusLine = element('div', undefined, 'card-status');
  const status = element('span');
  const display = element('span', undefined, 'location-chip');
  const position = element('span', undefined, 'location-chip');
  const positionText = element('span');
  position.append(icon('pin'), positionText);
  statusLine.append(status, display, position);
  const sessionLine = element('div', undefined, 'card-session');
  const experience = element('span');
  const remaining = element('span', undefined, 'card-time');
  sessionLine.append(experience, remaining);
  const progress = element('progress', undefined, 'card-progress');
  progress.setAttribute('aria-label', 'Elapsed operator timer');
  const actions = element('div', undefined, 'card-actions');
  const view = actionButton('View', 'eye', 'view', key, 'secondary');
  const blackout = actionButton('Blackout', 'dark', 'display_off', key, 'dark');
  const restore = actionButton('Restore', 'sun', 'display_on', key, 'restore');
  const stop = actionButton('', 'stop', 'stop_experience', key, 'stop stop-icon');
  stop.setAttribute('aria-label', 'Stop experience · ' + label(key));
  stop.title = 'Stop experience';
  actions.append(view, blackout, restore, stop);
  root.append(select, statusLine, sessionLine, progress, actions);
  byId('fleet').append(root);
  return {root, select, name, address, battery, batteryText, status, display, positionText,
    experience, remaining, progress, actions};
}

function renderCards() {
  const query = byId('search').value.trim().toLowerCase();
  let visible = 0;
  const known = new Set(state.devices.map(device => device.device_id));
  for (const [key, card] of cards) {
    if (!known.has(key)) {
      card.root.remove();
      cards.delete(key);
    }
  }
  const ordered = window.fleetStatus.sorted(state);
  let previous = null;
  for (const {device, info} of ordered) {
    const key = device.device_id;
    if (!cards.has(key)) cards.set(key, createCard(device));
    const card = cards.get(key);
    const next = previous ? previous.nextElementSibling : byId('fleet').firstElementChild;
    if (next !== card.root) byId('fleet').insertBefore(card.root, next);
    previous = card.root;
    const matchesQuery = [device.label, key, device.ip].join(' ').toLowerCase().includes(query);
    const matchesFilter = fleetFilter === 'all' ||
      (fleetFilter === 'online' && online(device)) ||
      (fleetFilter === 'attention' && needsAttention(device));
    card.root.hidden = !matchesQuery || !matchesFilter;
    if (!card.root.hidden) visible++;
    card.root.classList.toggle('selected', key === selected);
    card.select.setAttribute('aria-pressed', String(key === selected));
    card.name.textContent = info.name;
    card.address.textContent = device.ip;
    card.batteryText.textContent = Number.isFinite(info.charge) ? info.charge + '%' + (device.battery?.charging ? ' +' : '') : '—';
    card.battery.classList.toggle('low', info.low);
    card.battery.title = device.battery?.charging ? 'Charging' : 'Battery level';
    card.status.textContent = info.connection;
    card.status.className = 'pill ' + (info.online ? 'success' : 'neutral');
    card.display.textContent = info.displayLabel;
    card.positionText.textContent = freshPosition(device) ? 'Locating' : state.poses[key] ? 'Stale' : 'Not locating';
    const session = state.sessions[key];
    card.experience.textContent = info.app;
    card.experience.title = 'Foreground app';
    card.remaining.textContent = info.timer;
    card.progress.hidden = !session;
    if (session) {
      card.progress.max = session.duration;
      card.progress.value = Math.min(session.duration, elapsed(session));
    }
    card.actions.querySelectorAll('button').forEach(button => {
      button.disabled = bulkBusy || busyDevices.has(key) ||
        (button.dataset.cardAction !== 'display_on' && !online(device));
    });
  }
  byId('fleetEmpty').hidden = visible > 0;
}

function renderDetails() {
  const device = state.devices.find(item => item.device_id === selected);
  byId('details').hidden = !device;
  if (!device) return;
  const key = device.device_id;
  byId('selectedName').textContent = device.label;
  const properties = state.inventory[key]?.properties || {};
  byId('deviceMeta').textContent = [
    properties['sys.pxr.product.name'] || device.model,
    'PUI ' + (properties['ro.pui.build.version'] || 'unknown'),
    device.ip
  ].join(' · ');
  const [caption, color] = deviceStatus(device);
  byId('selectedStatus').textContent = caption;
  byId('selectedStatus').className = 'pill ' + color;
  const sample = state.poses[key];
  const age = sample ? Math.max(0, Math.round(state.now - sample.received)) : null;
  if (freshPosition(device)) {
    byId('trackingState').textContent = 'Receiving positions · last sample ' + age + 's ago';
  } else if (sample && state.tracking[key]?.startsWith('Receiving')) {
    byId('trackingState').textContent = 'Position updates stale · last sample ' + age + 's ago';
  } else {
    byId('trackingState').textContent = state.tracking[key] || 'Position feed is off';
  }
  const session = state.sessions[key];
  document.querySelectorAll('[data-action]').forEach(button => {
    const action = button.dataset.action;
    const onlineRequired = ['view', 'display_off', 'stop_experience', 'track', 'start'].includes(action);
    button.disabled = bulkBusy || busyDevices.has(key) || (onlineRequired && !online(device)) ||
      (['pause', 'resume', 'finish', 'reset'].includes(action) && !session) ||
      (action === 'pause' && session?.status !== 'running') ||
      (action === 'resume' && session?.status !== 'paused');
  });
}

function createMapMarker(key) {
  const root = svgNode('g', {class: 'map-marker', role: 'button', tabindex: 0});
  const title = svgNode('title');
  const halo = svgNode('circle', {opacity: .12});
  const arrow = svgNode('path', {d: 'M0 -30 L-6 -19 L6 -19 Z'});
  const core = svgNode('circle', {r: 16, stroke: 'white', 'stroke-width': 3, class: 'marker-core'});
  const number = svgNode('text', {y: 4, 'text-anchor': 'middle', fill: 'white', 'font-size': 14,
    'font-weight': 700, 'font-family': 'system-ui'});
  const plate = svgNode('rect', {height: 30, rx: 6, fill: 'white', opacity: .96});
  const caption = svgNode('text', {'text-anchor': 'middle', 'font-size': 14,
    'font-weight': 600, 'font-family': 'system-ui'});
  root.append(title, halo, arrow, core, number, plate, caption);
  root.onclick = () => selectDevice(key);
  root.onkeydown = event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      selectDevice(key);
    }
  };
  mapMarkerLayer.append(root);
  return {root, title, halo, arrow, core, number, plate, caption};
}

function currentFingerprint() {
  const samples = Object.entries(state.poses);
  return measurement?.fingerprint || state.poses[selected]?.map?.md5 ||
    samples.find(([, sample]) => sample.map?.md5)?.[1].map.md5 ||
    Object.keys(state.rooms)[0] || Object.keys(state.measured_rooms)[0];
}

function measurementSample() {
  if (!measurement || !state) return null;
  const device = state.devices.find(item => item.device_id === measurement.deviceId);
  const sample = state.poses[measurement.deviceId];
  const age = Date.now() / 1000 + clockOffset - (sample?.received || 0);
  return device && online(device) && age < 4 && sample?.map?.md5 === measurement.fingerprint ? sample : null;
}

function drawMap() {
  const samples = Object.entries(state.poses);
  const fingerprint = currentFingerprint();
  const room = state.rooms[fingerprint];
  const points = fingerprint ? samples.filter(([, sample]) => sample.map?.md5 === fingerprint) : [];
  const measured = state.measured_rooms[fingerprint];
  const outline = measured || room?.points || [];
  const fittedPositions = fittedRoom && fittedRoom.fingerprint === fingerprint ? fittedRoom.points : [];
  const extent = outline.length
    ? [...outline, ...(measurement?.points || []), ...fittedPositions]
    : points.map(([, sample]) => sample.pose);
  byId('measureRoom').disabled = !room || !selected || Boolean(measurement);
  byId('roomMeasure').hidden = !measurement;
  if (measurement) {
    const ready = Boolean(measurementSample());
    const count = measurement.points.length;
    byId('measureStatus').textContent = label(measurement.deviceId) + ' · ' +
      count + (count === 1 ? ' corner' : ' corners') + ' · ' +
      (ready ? 'Ready to capture' : 'Start locating this headset on this map');
    byId('captureCorner').disabled = savingOutline || !ready || measurement.points.length >= 256;
    byId('undoCorner').disabled = savingOutline || !measurement.points.length;
    byId('saveOutline').disabled = savingOutline || measurement.points.length < 3;
    byId('restoreOutline').hidden = !measured;
    byId('restoreOutline').disabled = savingOutline;
    byId('cancelMeasure').disabled = savingOutline;
  }
  byId('mapEmpty').hidden = extent.length > 0;
  if (!extent.length) {
    mapBase.replaceChildren();
    mapMarkerLayer.replaceChildren();
    mapMarkers.clear();
    byId('positionCount').textContent = '0 locating';
    return;
  }
  const minX = Math.min(...extent.map(point => point.x));
  const maxX = Math.max(...extent.map(point => point.x));
  const minZ = Math.min(...extent.map(point => point.z));
  const maxZ = Math.max(...extent.map(point => point.z));
  const scale = Math.min(780 / Math.max(4, maxX - minX + 2), 520 / Math.max(4, maxZ - minZ + 2));
  const centerX = (minX + maxX) / 2;
  const centerZ = (minZ + maxZ) / 2;
  const x = value => 500 + (value - centerX) * scale;
  const z = value => 330 - (value - centerZ) * scale;
  const nodes = [svgNode('title', {}, 'PICO LBE play boundary and reported global headset positions')];
  const grid = svgNode('g', {stroke: '#e4ebdf', 'stroke-width': .8});
  const gridStep = Math.max(1, Math.ceil(Math.max(maxX - minX, maxZ - minZ) / 30));
  for (let value = Math.floor(minX) - 2; value <= maxX + 2; value += gridStep) {
    grid.append(svgNode('line', {x1: x(value), x2: x(value), y1: 35, y2: 620}));
  }
  for (let value = Math.floor(minZ) - 2; value <= maxZ + 2; value += gridStep) {
    grid.append(svgNode('line', {x1: 65, x2: 935, y1: z(value), y2: z(value)}));
  }
  nodes.push(grid);
  if (outline.length) {
    const polygon = outline.map(point => x(point.x) + ',' + z(point.z)).join(' ');
    nodes.push(svgNode('polygon', {points: polygon, fill: '#eff5e8', stroke: '#6b947b',
      'stroke-width': 2, 'stroke-linejoin': 'bevel'}));
    const width = Math.max(...outline.map(point => point.x)) - Math.min(...outline.map(point => point.x));
    const depth = Math.max(...outline.map(point => point.z)) - Math.min(...outline.map(point => point.z));
    let area = 0;
    outline.forEach((point, index) => {
      const next = outline[(index + 1) % outline.length];
      area += point.x * next.z - next.x * point.z;
    });
    nodes.push(svgNode('text', {x: 500, y: 28, 'text-anchor': 'middle', fill: '#83997a',
      'font-size': 13, 'font-family': 'system-ui'}, 'APPROX. ' + width.toFixed(1) + ' m × ' + depth.toFixed(1) + ' m'));
    byId('roomDimensions').textContent = 'Approx. ' + Math.round(Math.abs(area) / 2) + ' m² · X / Z';
  }
  if (measurement?.points.length) {
    const draft = measurement.points;
    nodes.push(svgNode(draft.length >= 3 ? 'polygon' : 'polyline', {
      points: draft.map(point => x(point.x) + ',' + z(point.z)).join(' '),
      fill: draft.length >= 3 ? '#edd7b35c' : 'none', stroke: '#b36c23',
      'stroke-width': 3, 'stroke-dasharray': '7 4'
    }));
    for (const point of draft) {
      nodes.push(svgNode('circle', {cx: x(point.x), cy: z(point.z), r: 5, fill: '#b36c23'}));
    }
  }
  let live = 0;
  let beyondFrame = 0;
  const captionBoxes = [];
  const present = new Set(points.map(([key]) => key));
  for (const [key, marker] of mapMarkers) {
    if (!present.has(key)) {
      marker.root.remove();
      mapMarkers.delete(key);
    }
  }
  points.forEach(([key, sample]) => {
    const device = state.devices.find(item => item.device_id === key);
    const fresh = device && freshPosition(device);
    if (fresh) live++;
    const current = key === selected;
    const color = fresh ? (current ? '#cc9653' : '#438b70') : '#9fae96';
    if (!mapMarkers.has(key)) mapMarkers.set(key, createMapMarker(key));
    const marker = mapMarkers.get(key);
    const outside = x(sample.pose.x) < 10 || x(sample.pose.x) > 990 ||
      z(sample.pose.z) < 10 || z(sample.pose.z) > 660;
    marker.root.style.display = outside ? 'none' : '';
    if (outside) beyondFrame++;
    marker.root.setAttribute('transform', 'translate(' + x(sample.pose.x) + ' ' + z(sample.pose.z) + ')');
    marker.root.setAttribute('aria-label', label(key) + (fresh ? ' · live position' : ' · stale position'));
    marker.title.textContent = label(key) + ' · X ' + sample.pose.x.toFixed(2) + ', Z ' + sample.pose.z.toFixed(2);
    marker.halo.setAttribute('r', current ? 32 : 25);
    marker.halo.setAttribute('fill', color);
    const p = sample.pose;
    const direction = Math.atan2(-2 * (p.rx * p.rz + p.rw * p.ry), -(1 - 2 * (p.rx * p.rx + p.ry * p.ry))) * 180 / Math.PI;
    marker.arrow.setAttribute('fill', color);
    marker.arrow.setAttribute('transform', 'rotate(' + direction + ')');
    marker.core.setAttribute('fill', color);
    marker.number.textContent = (device?.label || key).split('-').pop().slice(-2);
    const caption = label(key) + (fresh ? '' : ' · stale');
    const width = caption.length * 9 + 18;
    const candidates = [[24, -38], [-width - 24, -38], [-width / 2, 31], [-width / 2, -65]];
    const box = candidates.find(([left, top]) => {
      const absoluteX = x(sample.pose.x) + left;
      const absoluteY = z(sample.pose.z) + top;
      const hitsCaption = captionBoxes.some(previous => absoluteX < previous.x + previous.width &&
        absoluteX + width > previous.x && absoluteY < previous.y + 30 && absoluteY + 30 > previous.y);
      const hitsMarker = points.some(([, other]) => x(other.pose.x) + 22 > absoluteX &&
        x(other.pose.x) - 22 < absoluteX + width && z(other.pose.z) + 22 > absoluteY &&
        z(other.pose.z) - 22 < absoluteY + 30);
      return !hitsCaption && !hitsMarker;
    }) || candidates[2];
    captionBoxes.push({x: x(sample.pose.x) + box[0], y: z(sample.pose.z) + box[1], width});
    marker.plate.setAttribute('x', box[0]);
    marker.plate.setAttribute('y', box[1]);
    marker.plate.setAttribute('width', width);
    marker.caption.setAttribute('x', box[0] + width / 2);
    marker.caption.setAttribute('y', box[1] + 20);
    marker.caption.setAttribute('fill', color);
    marker.caption.textContent = caption;
  });
  const scaleLength = Math.max(1, Math.round(90 / scale));
  nodes.push(svgNode('path', {d: 'M80 600 v6 h' + scaleLength * scale + ' v-6',
    fill: 'none', stroke: '#8c9e7d', 'stroke-width': 2}));
  nodes.push(svgNode('text', {x: 80, y: 590, fill: '#829773', 'font-size': 11,
    'font-family': 'system-ui'}, scaleLength + ' m'));
  mapBase.replaceChildren(...nodes);
  byId('positionCount').textContent = live + ' locating';
  byId('positionCount').className = 'pill ' + (live ? 'success' : 'neutral');
  byId('boundaryLabel').textContent = room ? room.name : 'Boundary unavailable · showing positions';
  byId('outlineLegend').textContent = measured ? 'Measured outline' : 'PICO boundary';
  byId('mapSource').textContent = measured ? 'OPERATOR MEASURED · X / Z' :
    room ? 'PICO BOUNDARY FROM ' + label(room.source) : 'PICO GLOBAL COORDINATES';
  byId('mapNote').textContent = (measured
    ? 'Outline captured from headset positions on this LBE map.'
    : 'PICO play boundary. Measure the outline to match the physical perimeter.') +
    (beyondFrame ? ' ' + beyondFrame + ' markers beyond the view. Use Fit room to include them.' : '') +
    (samples.length > points.length ? ' Other LBE maps are excluded.' : '');
}

function renderEvents() {
  const operations = state.operations.map(operation => ({...operation, message: operation.title, device: '',
    kind: Object.values(operation.results).some(item => ['Failed', 'Unverified'].includes(item.status)) ? 'problem' : 'activity'}));
  const events = [...state.events, ...operations].filter(event => eventFilter === 'all' || event.kind === eventFilter)
    .sort((a, b) => b.at - a.at).slice(0, 80);
  const signature = JSON.stringify(events);
  if (signature === eventSignature) return;
  eventSignature = signature;
  const expanded = new Set([...byId('events').querySelectorAll('details[open][data-operation]')]
    .map(details => details.dataset.operation));
  const nodes = events.map(event => {
    const row = element('div', undefined, 'event ' + event.kind);
    const image = element('span', undefined, 'event-icon');
    image.append(icon(event.kind === 'problem' ? 'alert' : event.kind === 'session' ? 'clock' : 'check'));
    const message = element('div', undefined, 'event-message');
    message.append(element('span', event.message.slice(0, 180)));
    if (event.results) {
      const details = element('details');
      details.dataset.operation = event.id;
      details.open = expanded.has(event.id);
      const counts = {};
      for (const item of Object.values(event.results)) counts[item.status] = (counts[item.status] || 0) + 1;
      const summary = Object.entries(counts).map(([status, count]) => count + ' ' + status.toLowerCase()).join(' · ');
      details.append(element('summary', summary || 'Headset results'));
      for (const [id, item] of Object.entries(event.results)) {
        const transfer = item.transfer ? 'Transfer ' + item.transfer.toLowerCase() + ' · ' : '';
        const phase = event.title.startsWith('Install APK') && item.transfer === 'Complete' ? 'Install ' : '';
        details.append(element('span', label(id) + ' · ' + transfer + phase + item.status +
          (item.detail ? ' · ' + item.detail : ''), 'operation-result'));
      }
      message.append(details);
    } else if (event.message.length > 180) {
      const details = element('details');
      details.append(element('summary', 'Technical details'), element('p', event.message));
      message.append(details);
    }
    const time = element('time', new Date(event.at * 1000).toLocaleTimeString('en-GB', {
      timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit'}));
    time.dateTime = new Date(event.at * 1000).toISOString();
    row.append(image, element('strong', event.results ? 'Fleet operation' : label(event.device)), message, time);
    return row;
  });
  byId('events').replaceChildren(...(nodes.length ? nodes : [element('p', 'Activity will appear here as you operate the fleet.', 'feed-empty')]));
}

function render() {
  if (!state) return;
  const connected = state.devices.filter(online).length;
  byId('online').textContent = connected;
  byId('knownCount').textContent = state.devices.length;
  byId('fleetTotal').textContent = 'of ' + state.devices.length + ' known headsets';
  byId('running').textContent = Object.values(state.sessions).filter(session => session.status === 'running' && elapsed(session) < session.duration).length;
  byId('darkCount').textContent = state.devices.filter(device => online(device) && displayState(device.device_id) === 'off').length;
  byId('attention').textContent = state.devices.filter(needsAttention).length;
  byId('connection').textContent = state.connected ? 'MDM connected' : 'MDM disconnected';
  byId('connection').className = 'pill ' + (state.connected ? 'success' : 'danger');
  byId('railStatus').textContent = state.connected ? 'Connected to MDM' : 'MDM disconnected';
  byId('railDot').classList.toggle('off', !state.connected);
  byId('blackoutCount').textContent = connected;
  byId('fleetScope').textContent = connected + ' connected · ' + (state.devices.length - connected) + ' offline';
  byId('blackoutAll').disabled = bulkBusy || connected === 0;
  byId('stopAll').disabled = bulkBusy || connected === 0;
  byId('restoreAll').disabled = bulkBusy || (!connected && !Object.keys(state.displays).length);
  const homeMenuBusy = homeMenuPending || state.home_menu_busy;
  const homeMenuStatus = byId('homeMenuStatus');
  const status = homeMenuBusy ? 'Updating connected headsets…' : state.home_menu ?
    homeMenuSummary(state.home_menu) : 'Single press · Connected headsets';
  if (homeMenuStatus.textContent !== status) homeMenuStatus.textContent = status;
  document.querySelectorAll('[data-home-menu]').forEach(button => {
    button.disabled = bulkBusy || Boolean(homeMenuBusy) || connected === 0 || !state.connected;
  });
  renderCards();
  renderDetails();
  drawMap();
  renderEvents();
  window.venueSuite.render(state);
}

async function confirmation(deviceId) {
  const dialog = byId('stopDialog');
  if (dialog.open) return false;
  byId('stopDialogTitle').textContent = deviceId ? 'Stop this experience?' : 'Stop all experiences?';
  byId('stopDialogText').textContent = deviceId
    ? 'End registered running experience apps on ' + label(deviceId) + '? Their current playback will end.'
    : 'End registered running experience apps on all ' + state.devices.filter(online).length + ' connected headsets? Their current playback will end.';
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once: true}));
}

async function request(path, data) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  const text = await response.text();
  let result;
  try { result = JSON.parse(text); } catch { throw new Error(text || 'The monitor returned an empty response.'); }
  if (!response.ok) throw new Error(result.error || 'The action could not be completed.');
  return result;
}

async function runAction(deviceId, action) {
  if (!deviceId || bulkBusy || busyDevices.has(deviceId)) return;
  if (action === 'stop_experience' && !await confirmation(deviceId)) return;
  const packageName = byId('experience').value;
  const minutes = Number(byId('minutes').value);
  if (action === 'start' && (!Number.isFinite(minutes) || minutes <= 0 || minutes > 240)) {
    notify('Enter a duration between 0 and 240 minutes before starting the timer.');
    byId('minutes').focus();
    return;
  }
  if (action === 'start' && state.sessions[deviceId]?.status === 'running' &&
      !window.confirm('Replace the running timer on ' + label(deviceId) + '?')) return;
  busyDevices.add(deviceId);
  render();
  const captions = {display_off: 'Applying blackout', display_on: 'Restoring display', stop_experience: 'Stopping experience', track: 'Starting position feed', view: 'Opening live view'};
  notify((captions[action] || 'Updating timer') + ' · ' + label(deviceId) + '…');
  try {
    await request('/api/action', {device_id: deviceId, action, package: packageName, minutes});
    if (action === 'start' && !state.suite) localStorage.setItem('duration:' + packageName, String(minutes));
    const complete = {display_off: 'Blackout confirmed', display_on: 'Display restored', stop_experience: 'Experience stop check complete', track: 'Position feed requested', stop_tracking: 'Position feed stopped', view: 'Live viewer opened on this PC'};
    notify((complete[action] || 'Timer updated') + ' · ' + label(deviceId));
  } catch (error) {
    notify(label(deviceId) + ' · ' + error.message);
  } finally {
    busyDevices.delete(deviceId);
    await poll();
  }
}

async function runGroup(action) {
  if (bulkBusy || busyDevices.size) {
    notify('Wait for the current headset action to finish.');
    return;
  }
  if (action === 'stop' && !await confirmation(null)) return;
  bulkBusy = true;
  render();
  notify('Sending ' + (action === 'stop' ? 'stop commands' : action === 'off' ? 'blackout commands' : 'restore commands') + ' to the fleet…');
  try {
    const result = await request(action === 'stop' ? '/api/stop-group' : '/api/display-group', {action});
    const stopped = result.results.reduce((total, item) => total + (item.stopped?.length || 0), 0);
    const caption = action === 'stop'
      ? stopped + ' experience app(s) stopped across ' + result.succeeded + ' headset(s).'
      : (action === 'off' ? 'Blackout confirmed' : 'Display restored') + ' on ' + result.succeeded + ' headset(s).';
    notify(caption + ' ' + result.failed + ' failed · ' + result.skipped + ' offline skipped. See Activity for details.');
  } catch (error) {
    notify(error.message);
  } finally {
    bulkBusy = false;
    await poll();
  }
}

function homeMenuSummary(result) {
  return 'Last command: ' + (result.mode === 'restore' ? 'Enable' : 'Disable') + ' · ' +
    result.confirmed + ' confirmed · ' + result.skipped + ' skipped · ' + result.failed + ' failed';
}

async function runHomeMenu(mode) {
  if (!state?.connected || bulkBusy || state.home_menu_busy) return;
  if (busyDevices.size) {
    notify('Wait for the current headset action to finish.');
    return;
  }
  bulkBusy = true;
  homeMenuPending = mode;
  render();
  try {
    state.home_menu = await request('/api/home-menu', {mode});
    notify(homeMenuSummary(state.home_menu) + '. See Activity for details.');
  } catch (error) {
    notify(error.message);
  } finally {
    homeMenuPending = null;
    bulkBusy = false;
    render();
    await poll();
  }
}

function restoreDuration() {
  const packageName = byId('experience').value;
  byId('minutes').value = state.suite ? state.durations[packageName] ?? '' :
    localStorage.getItem('duration:' + packageName) || '';
}

function syncTimerSelection() {
  if (timerEdited) return;
  const session = state.sessions[selected];
  if (session && ['running', 'paused'].includes(session.status)) {
    byId('experience').value = session.package;
    byId('minutes').value = session.duration / 60;
    return;
  }
  const device = state.devices.find(device => device.device_id === selected);
  const current = device && window.fleetStatus.status(state, device).pkg;
  if (state.packages[current]) byId('experience').value = current;
  restoreDuration();
}

async function poll() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    const response = await fetch('/api/state', {cache: 'no-store'});
    if (!response.ok) throw new Error('Monitor unavailable');
    state = await response.json();
    clockOffset = state.now - Date.now() / 1000;
    if (!packagesLoaded) {
      const options = Object.entries(state.packages).map(([value, name]) => {
        const option = element('option', name);
        option.value = value;
        return option;
      });
      byId('experience').replaceChildren(...options);
      packagesLoaded = true;
      restoreDuration();
    }
    if (!selected && state.devices.length) {
      selected = state.devices.find(device => freshPosition(device))?.device_id ||
        state.devices.find(online)?.device_id || state.devices[0].device_id;
    }
    syncTimerSelection();
    render();
  } catch {
    if (state) {
      state.connected = false;
      render();
    }
    notify('Monitor connection lost. Reconnecting…');
  } finally {
    pollBusy = false;
  }
}

byId('dismissMessage').onclick = () => notify('');
byId('experience').onchange = () => { timerEdited = true; restoreDuration(); };
byId('minutes').oninput = () => { timerEdited = true; };
byId('search').oninput = renderCards;
byId('fitRoom').onclick = () => {
  if (!state) return;
  const fingerprint = currentFingerprint();
  const points = Object.values(state.poses)
    .filter(sample => sample.map?.md5 === fingerprint)
    .map(sample => sample.pose);
  fittedRoom = {fingerprint, points};
  drawMap();
};
byId('measureRoom').onclick = () => {
  measurement = {fingerprint: currentFingerprint(), deviceId: selected, points: []};
  drawMap();
};
byId('captureCorner').onclick = () => {
  const sample = measurementSample();
  if (!sample) return;
  const {x, z} = sample.pose;
  if (measurement.points.some(point => Math.hypot(point.x - x, point.z - z) < .1)) {
    notify('Move the headset to the next corner before capturing.');
    return;
  }
  measurement.points.push({x, z});
  drawMap();
};
byId('undoCorner').onclick = () => {
  measurement.points.pop();
  drawMap();
};
byId('cancelMeasure').onclick = () => {
  measurement = null;
  drawMap();
};
async function applyOutline(points) {
  savingOutline = true;
  drawMap();
  try {
    const fingerprint = measurement.fingerprint;
    await request('/api/room-outline', {fingerprint, points});
    if (points) state.measured_rooms[fingerprint] = points;
    else delete state.measured_rooms[fingerprint];
    measurement = null;
    fittedRoom = null;
    notify(points ? 'Measured room outline saved.' : 'PICO boundary restored.');
  } catch (error) {
    notify(error.message);
  } finally {
    savingOutline = false;
    drawMap();
  }
}
byId('saveOutline').onclick = () => applyOutline(measurement.points);
byId('restoreOutline').onclick = () => applyOutline(null);
document.querySelectorAll('[data-action]').forEach(button => {
  button.onclick = () => runAction(selected, button.dataset.action);
});
document.querySelectorAll('[data-group]').forEach(button => {
  button.onclick = () => runGroup(button.dataset.group);
});
document.querySelectorAll('[data-home-menu]').forEach(button => {
  button.onclick = () => runHomeMenu(button.dataset.homeMenu);
});
document.querySelectorAll('[data-fleet]').forEach(button => {
  button.onclick = () => {
    fleetFilter = button.dataset.fleet;
    document.querySelectorAll('[data-fleet]').forEach(item => {
      item.classList.toggle('selected', item === button);
      item.setAttribute('aria-pressed', String(item === button));
    });
    renderCards();
  };
});
document.querySelectorAll('[data-filter]').forEach(button => {
  button.onclick = () => {
    eventFilter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(item => {
      item.classList.toggle('selected', item === button);
      item.setAttribute('aria-pressed', String(item === button));
    });
    eventSignature = '';
    renderEvents();
  };
});
function updateClock() {
  byId('wallClock').textContent = new Date().toLocaleTimeString('en-GB', {
    timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit'});
}
updateClock();
poll();
setInterval(updateClock, 1000);
setInterval(poll, 1500);
