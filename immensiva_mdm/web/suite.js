(() => {
  const get = id => document.getElementById(id);
  const textNode = (tag, text) => Object.assign(document.createElement(tag), {textContent: text});
  const selected = new Set();
  let latest;
  let targetSignature = '';
  let groupSignature = '';
  let durationSignature = '';
  let initialized = false;
  let working = false;
  let reviewing = false;
  let durationsEdited = false;

  function showView() {
    if (!initialized) return;
    const view = ['prepare', 'technician'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'operate';
    for (const name of ['operate', 'prepare', 'technician']) get(name + 'View').hidden = name !== view;
    document.querySelectorAll('[data-suite-tab]').forEach(link => {
      const current = link.dataset.suiteTab === view;
      link.classList.toggle('active', current);
      if (current) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function updateSelection() {
    const count = latest.devices.filter(device => selected.has(device.device_id) && device.status === 'online').length;
    get('prepareCount').textContent = `${selected.size} selected · ${latest.connected ? count : 0} connected`;
    get('prepareReview').disabled = !latest.connected || !count || working || reviewing;
    get('roomGroupForm').querySelector('button').disabled = !latest.connected || working;
  }

  async function send(path, body, multipart = false) {
    const response = await fetch(path, {method: 'POST',
      headers: multipart ? undefined : {'Content-Type': 'application/json'},
      body: multipart ? body : JSON.stringify(body)});
    if (!response.ok) {
      const raw = await response.text();
      let message = raw;
      try { message = JSON.parse(raw).error || raw; } catch { /* plain HTTP errors */ }
      throw new Error(message || 'The command failed.');
    }
    return response.json();
  }

  function init(state) {
    initialized = true;
    document.body.classList.add('venue-suite');
    document.title = 'IMMENSIVA · Venue Suite';
    document.querySelector('.rail-footer small').textContent = 'VENUE SUITE';
    document.querySelector('.page-footer span:last-child').textContent = 'Venue Suite · LBE alignment requires venue validation';
    document.querySelectorAll('[data-suite-tab]').forEach(link => { link.hidden = false; });
    get('suitePolicy').append(document.querySelector('.home-menu'));
    for (const [id, label] of Object.entries(state.packages)) {
      get('prepareApp').append(new Option(label, id));
      const field = textNode('label', label);
      const input = document.createElement('input');
      Object.assign(input, {type: 'number', min: '0.1', max: '240', step: '0.1', placeholder: 'Minutes', name: id});
      field.append(input);
      get('durationFields').append(field);
    }
    addEventListener('hashchange', showView);
    showView();
    get('suiteCalibrate').onclick = () => {
      location.hash = 'overview';
      showView();
      get('measureRoom').click();
      get('roomMeasure').scrollIntoView({block: 'center'});
    };
    get('prepareRoom').onchange = () => {
      const room = get('prepareRoom').value;
      selected.clear();
      const known = new Set(latest.devices.map(device => device.device_id));
      for (const id of latest.groups[room] || []) if (known.has(id)) selected.add(id);
      get('roomGroupName').value = room;
      targetSignature = '';
      render(latest);
    };
    get('prepareAction').onchange = () => {
      const action = get('prepareAction').value;
      get('prepareAppField').hidden = action !== 'launch';
      get('prepareApkField').hidden = action !== 'install';
      get('prepareFilesField').hidden = action !== 'files';
    };
    get('prepareForm').onsubmit = prepare;
    get('roomGroupForm').onsubmit = saveRoom;
    get('durationForm').oninput = () => { durationsEdited = true; };
    get('durationForm').onsubmit = saveDurations;
  }

  function render(state) {
    latest = state;
    get('mdmConsole').href = state.mdm_url;
    if (!state.suite) return;
    if (!initialized) init(state);
    get('suiteMdm').href = state.mdm_url;
    get('suiteHealth').textContent = state.connected ? 'MDM connected · ' + state.mdm_url : 'MDM disconnected · Check suite-data/logs/mdm.log.';
    get('suiteWifi').textContent = state.touch_enabled ? `Venue Wi-Fi enabled · port ${state.touch_port}` : 'Venue Wi-Fi is off · Open pairing for setup steps.';
    get('suiteCalibrate').disabled = get('measureRoom').disabled;
    const groups = JSON.stringify(state.groups);
    if (groups !== groupSignature) {
      groupSignature = groups;
      const room = get('prepareRoom').value;
      get('prepareRoom').replaceChildren(new Option('Select individually', ''),
        ...Object.keys(state.groups).map(name => new Option(name, name)));
      get('prepareRoom').value = Object.hasOwn(state.groups, room) ? room : '';
    }
    const devices = window.fleetStatus.sorted(state);
    const signature = JSON.stringify(devices.map(({device, info}) => [device.device_id, info.name, info.connection]));
    if (signature !== targetSignature) {
      targetSignature = signature;
      const available = new Set(state.devices.map(device => device.device_id));
      for (const id of selected) if (!available.has(id)) selected.delete(id);
      const list = devices.map(({device, info}) => {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = selected.has(device.device_id);
        input.onchange = () => {
          if (input.checked) selected.add(device.device_id);
          else selected.delete(device.device_id);
          updateSelection();
        };
        label.append(input, textNode('strong', info.name), textNode('small', info.connection));
        return label;
      });
      get('prepareTargets').replaceChildren(...(list.length ? list : [textNode('p', 'Waiting for pilot headsets to connect.') ]));
    }
    const durations = JSON.stringify(state.durations);
    if (!durationsEdited && durationSignature !== durations) {
      durationSignature = durations;
      get('durationFields').querySelectorAll('input').forEach(input => {
        input.value = state.durations[input.name] ?? '';
      });
    }
    updateSelection();
  }

  async function prepare(event) {
    event.preventDefault();
    if (working || reviewing || !selected.size) return;
    const action = get('prepareAction').value;
    const targets = [...selected];
    const apk = get('prepareApk').files[0];
    const files = [...get('prepareFiles').files];
    const destination = get('prepareDestination').value.trim();
    const pkg = get('prepareApp').value;
    const title = action === 'launch' ? 'Open ' + latest.packages[pkg] :
      action === 'install' ? 'Install ' + (apk?.name || 'APK') : 'Send ' + files.length + ' file(s)';
    if ((action === 'install' && !apk) || (action === 'files' && (!files.length || !destination))) {
      get('prepareResult').textContent = 'Choose the files and destination required by this action.';
      return;
    }
    get('prepareDialogTitle').textContent = title + '?';
    get('prepareDialogText').textContent = action === 'files' ? 'Destination ' + destination + '. Files with matching names are replaced.' :
      'Offline headsets in this selection will be skipped.';
    const labels = new Map(latest.devices.map(device => [device.device_id, device.label || device.device_id]));
    get('prepareDialogTargets').replaceChildren(...targets.map(id => textNode('li', labels.get(id) || id)));
    const dialog = get('prepareDialog');
    dialog.returnValue = 'cancel';
    reviewing = true;
    updateSelection();
    dialog.showModal();
    await new Promise(resolve => dialog.addEventListener('close', resolve, {once: true}));
    reviewing = false;
    if (dialog.returnValue !== 'confirm') { updateSelection(); return; }
    working = true;
    updateSelection();
    get('prepareResult').textContent = action === 'launch' ? 'Sending app command…' : 'Uploading to the venue PC…';
    try {
      const path = '/api/suite/operation/' + action;
      if (action === 'launch') await send(path, {targets, package: pkg});
      else {
        const form = new FormData();
        if (action === 'install') form.append('apk', apk);
        else for (const file of files) form.append('files', file, file.name);
        const query = new URLSearchParams(targets.map(id => ['target', id]));
        if (action === 'files') query.set('destination', destination);
        await send(path + '?' + query, form, true);
      }
      get('prepareResult').textContent = 'MDM accepted the command. Follow headset results in Activity.';
    } catch (error) {
      get('prepareResult').textContent = error.message;
    } finally {
      working = false;
      updateSelection();
    }
  }

  async function saveRoom(event) {
    event.preventDefault();
    if (working) return;
    working = true;
    updateSelection();
    const name = get('roomGroupName').value.trim();
    try {
      await send('/api/suite/group', {name, members: [...selected]});
      get('prepareResult').textContent = 'Saved room ' + name + '.';
    } catch (error) {
      get('prepareResult').textContent = error.message;
    } finally {
      working = false;
      updateSelection();
    }
  }

  async function saveDurations(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    try {
      const values = Object.fromEntries([...get('durationFields').querySelectorAll('input')]
        .map(input => [input.name, input.value === '' ? null : input.valueAsNumber]));
      latest.durations = await send('/api/suite/durations', values);
      durationsEdited = false;
      get('durationResult').textContent = 'Saved default durations.';
    } catch (error) {
      get('durationResult').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  window.venueSuite = {render};
})();
