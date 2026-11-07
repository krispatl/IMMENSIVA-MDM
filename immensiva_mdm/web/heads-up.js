const get = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const touch = document.body.classList.contains('touch');
let accessKey = touch ? localStorage.getItem('venue-access') || '' : '';
let busy = false;
let pollTimer;
let lastState;

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function icon(viewBox, markup) {
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', viewBox);
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = markup;
  return svg;
}

function render(state) {
  let connected = 0, playing = 0, low = 0, dark = 0;
  const query = touch ? get('search').value.trim().toLowerCase() : '';
  const cards = [];
  for (const {device, info} of window.fleetStatus.sorted(state)) {
    const {online, charge, low: lowBattery, experience, name} = info;
    const blackout = info.display === 'off';
    connected += Number(online);
    playing += Number(Boolean(experience));
    low += Number(lowBattery);
    dark += Number(blackout);

    if (query && !name.toLowerCase().includes(query)) continue;
    const card = node('article', undefined, 'headset');
    card.classList.toggle('is-offline', !online);
    card.classList.toggle('is-dark', blackout);
    card.classList.toggle('is-low', lowBattery);
    const heading = node('div', undefined, 'card-heading');
    heading.append(node('h2', name),
      node('span', info.connection, 'status'));

    const battery = node('div', undefined, 'battery');
    const graphic = icon('0 0 52 30', '<rect x="2" y="4" width="43" height="22" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M49 10v10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>');
    const fill = document.createElementNS(svgNS, 'rect');
    fill.setAttribute('x', '6');
    fill.setAttribute('y', '8');
    fill.setAttribute('height', '14');
    fill.setAttribute('rx', '2');
    fill.setAttribute('width', String(Number.isFinite(charge) ? 35 * Math.max(0, Math.min(100, charge)) / 100 : 0));
    fill.setAttribute('fill', 'currentColor');
    graphic.append(fill);
    battery.append(graphic, node('strong', Number.isFinite(charge) ? charge + '%' : '—'));
    if (online && device.battery?.charging) battery.append(node('small', '⚡ Charging'));
    else if (lowBattery) battery.append(node('small', 'Low battery'));

    const app = node('div', undefined, 'app');
    const caption = node('div');
    caption.append(node('strong', info.app), node('small', 'Foreground app'));
    app.append(icon('0 0 28 28', '<rect x="2" y="4" width="24" height="20" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="m11 9 8 5-8 5z" fill="currentColor"/>'), caption);
    const details = node('div', undefined, 'headset-details');
    details.append(node('span', info.displayLabel), node('span', info.timer));
    card.append(heading, battery, app, details);
    if (touch) {
      const actions = node('div', undefined, 'touch-actions');
      for (const [action, title] of [
        ['display_off', 'Blackout'], ['display_on', 'Restore'], ['stop_experience', 'Stop experience']
      ]) {
        const button = node('button', title, action === 'stop_experience' ? 'stop' : '');
        button.disabled = busy || !online;
        button.setAttribute('aria-label', title + ' · ' + name);
        button.onclick = () => control(action, device.device_id, name);
        actions.append(button);
      }
      card.append(actions);
    }
    cards.push(card);
  }
  get('connected').textContent = connected;
  get('playing').textContent = playing;
  get('low').textContent = low;
  get('dark').textContent = dark;
  get('offline').textContent = state.devices.length - connected;
  get('connection').textContent = state.connected ? 'MDM connected' : 'MDM disconnected';
  get('fleet').replaceChildren(...cards);
  if (touch) {
    if (!cards.length) get('fleet').append(node('p', query ? 'No matching headsets.' : 'Waiting for headsets…'));
    document.querySelectorAll('[data-fleet-action]').forEach(button => {
      button.disabled = busy || connected === 0;
    });
  }
}

function setAccess(key) {
  accessKey = key;
  lastState = undefined;
  if (key) localStorage.setItem('venue-access', key);
  else localStorage.removeItem('venue-access');
  get('pair').hidden = Boolean(key);
  get('controls').hidden = true;
  get('access-key').value = '';
  clearTimeout(pollTimer);
  if (key) poll();
}

async function control(action, deviceId, name) {
  if (busy || !lastState?.connected) return;
  const title = {display_off: 'Blackout', display_on: 'Restore', stop_experience: 'Stop experience on'}[action];
  if ((!deviceId || action === 'stop_experience') &&
      !window.confirm(title + ' ' + name + '?')) return;
  const path = deviceId ? '/api/action' :
    action === 'stop_experience' ? '/api/stop-group' : '/api/display-group';
  const data = deviceId ? {action, device_id: deviceId} :
    action === 'stop_experience' ? {} : {action: action === 'display_off' ? 'off' : 'on'};
  busy = true;
  get('result').textContent = 'Sending command…';
  render(lastState);
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + accessKey},
      body: JSON.stringify(data)
    });
    if (response.status === 401) {
      setAccess('');
      get('connection').textContent = 'Enter the venue access key';
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Command failed. Try again.');
    get('result').textContent = deviceId ? 'Command completed · ' + name :
      result.succeeded + ' succeeded · ' + result.failed + ' failed · ' + result.skipped + ' skipped';
  } catch (error) {
    get('result').textContent = error.message;
  } finally {
    busy = false;
    if (lastState) render(lastState);
  }
}

async function poll() {
  if (touch && !accessKey) return;
  const key = accessKey;
  try {
    const response = await fetch('/api/heads-up', {
      signal: AbortSignal.timeout(5000),
      headers: touch ? {Authorization: 'Bearer ' + key} : {}
    });
    if (key !== accessKey) return;
    if (touch && response.status === 401) {
      setAccess('');
      get('connection').textContent = 'Access key rejected';
      return;
    }
    if (!response.ok) throw new Error('Monitor unavailable');
    const state = await response.json();
    if (key !== accessKey) return;
    lastState = state;
    if (touch) get('controls').hidden = false;
    render(lastState);
  } catch {
    if (key !== accessKey) return;
    if (lastState) {
      lastState = {...lastState, connected: false};
      render(lastState);
    }
    get('connection').textContent = 'Reconnecting to monitor…';
  }
  pollTimer = setTimeout(poll, 2000);
}

if (touch) {
  const inviteKey = new URLSearchParams(window.location.hash.slice(1)).get('key');
  if (inviteKey) history.replaceState(null, '', window.location.pathname + window.location.search);
  get('pair').onsubmit = event => {
    event.preventDefault();
    setAccess(get('access-key').value.trim());
  };
  get('disconnect').onclick = () => {
    setAccess('');
    get('connection').textContent = 'Disconnected';
  };
  get('search').oninput = () => { if (lastState) render(lastState); };
  document.querySelectorAll('[data-fleet-action]').forEach(button => {
    button.onclick = () => control(button.dataset.fleetAction, null, get('connected').textContent + ' connected headsets');
  });
  setAccess(inviteKey || accessKey);
  if (!accessKey) get('connection').textContent = 'Enter the venue access key';
} else {
get('fullscreen').hidden = !document.fullscreenEnabled;
get('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    get('fullscreen').textContent = 'Full screen unavailable';
  }
};
document.addEventListener('fullscreenchange', () => {
  get('fullscreen').textContent = document.fullscreenElement ? 'Exit full screen' : 'Full screen';
});
poll();
}
