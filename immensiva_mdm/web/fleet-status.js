(() => {
  const systemApps = {
    'com.pvr.tobhome': 'PICO Home',
    'com.pvr.appmanager': 'App library',
    'com.pvr.shortcut': 'PICO shortcuts',
    'com.picovr.settings': 'Settings',
    'com.pvr.seethrough.setting': 'Passthrough'
  };
  function status(state, device) {
    const id = device.device_id;
    const online = state.connected && device.status === 'online';
    const reading = state.foreground?.[id];
    const pkg = online && reading && state.now - reading.checked_at < 15 ? reading.package : null;
    const displayRecord = state.displays[id];
    const display = online && displayRecord && state.now - displayRecord.checked_at < 20 ? displayRecord.state : 'unknown';
    const charge = online ? device.battery?.level : null;
    const low = Number.isFinite(charge) && charge < 20;
    const session = state.sessions[id];
    let timer = 'No operator timer';
    let expired = false;
    if (session) {
      const running = session.status === 'running';
      const elapsed = session.elapsed + (running ? Math.max(0, state.now - session.started) : 0);
      const seconds = Math.max(0, Math.ceil(session.duration - elapsed));
      expired = running && seconds === 0;
      const remaining = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      timer = session.status === 'finished' ? 'Timer finished' : expired ? 'Duration reached' :
        (running ? 'Timer ' : 'Timer paused · ') + remaining;
    }
    return {
      online, low, charge, display, timer, pkg, experience: state.packages[pkg],
      name: device.label || id,
      connection: online ? 'Connected' : state.connected ? 'Offline' : 'MDM unavailable',
      app: state.packages[pkg] || systemApps[pkg] || pkg || 'App unavailable',
      displayLabel: display === 'off' ? 'Blacked out' : display === 'on' ? 'Display on' : 'Display unverified',
      attention: !online || low || expired || Boolean(displayRecord && display === 'unknown')
    };
  }
  function sorted(state) {
    return state.devices.map(device => ({device, info: status(state, device)}))
      .sort((a, b) => Number(b.info.attention) - Number(a.info.attention) ||
        a.info.name.localeCompare(b.info.name, undefined, {numeric: true}));
  }
  window.fleetStatus = {status, sorted};
})();
