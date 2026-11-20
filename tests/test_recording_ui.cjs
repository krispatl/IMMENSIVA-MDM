const assert = require('node:assert/strict');
const test = require('node:test');
const {consoleUI, flush, headset} = require('./helpers/venue_console.cjs');

const reply = (body, ok = true) => ({ok, json: async () => body});
const confirmed = (state, message = 'Recording confirmed.') => reply({status: 'confirmed', state, message});

for (const action of ['start', 'stop']) {
  test(`${action} applies the requested state to a mixed selection, skipping offline and unselected headsets`, async () => {
    const states = {A: 'stopped', B: 'recording'};
    const expected = action === 'start' ? 'recording' : 'stopped';
    const ui = await consoleUI({recordingAvailable: true,
      readRecording: async target => reply({state: states[target]}),
      record: async ({device_id}) => {
        const unchanged = states[device_id] === expected;
        states[device_id] = expected;
        return confirmed(expected, unchanged ? 'Already ' + expected + '; no recording command was sent.' : 'Changed to ' + expected);
      },
    });
    await ui.select([headset('A'), headset('B'), headset('Offline', 'offline'), headset('Unselected')], ['A', 'B', 'Offline']);
    await ui.task('recording');
    assert.deepEqual(ui.recordingReads, ['A', 'B']);
    assert.equal(ui.id('btnRecordStart').disabled, false);
    assert.equal(ui.id('btnRecordStop').disabled, false);
    await ui.record(action);
    assert.deepEqual(ui.recordingPosts.map(({device_id, action}) => ({device_id, action})), [{device_id: 'A', action}, {device_id: 'B', action}]);
    const ids = ui.recordingPosts.map(item => item.request_id);
    assert.equal(new Set(ids).size, 2);
    ids.forEach(id => assert.match(id, /^[a-f0-9]{32}$/));
    assert.match(ui.id('recordingResult').textContent, /2 confirmed · 0 failed · 1 offline skipped/);
    assert.match(ui.id('recordingResult').textContent, /Already .*no recording command was sent/);
    assert.equal(ui.id('btnRecordStart').disabled, action === 'start');
    assert.equal(ui.id('btnRecordStop').disabled, action === 'stop');
  });
}

test('Recording failures and unconfirmed responses do not block the rest of the selection', async () => {
  const ui = await consoleUI({recordingAvailable: true,
    readRecording: async target => target === 'B' ? reply({error: 'State unavailable'}, false) : reply({state: 'stopped'}),
    record: async ({device_id}) => {
      if (device_id === 'B') return reply({error: 'Native state unavailable; no command sent.'}, false);
      if (device_id === 'C') throw new Error('Connection lost');
      if (device_id === 'D') return confirmed('stopped');
      return confirmed('recording');
    },
  });
  const devices = ['A', 'B', 'C', 'D'].map(id => headset(id));
  await ui.select(devices, devices.map(device => device.device_id));
  await ui.task('recording');
  await ui.record('start');
  assert.equal(ui.recordingPosts.length, 4);
  const result = ui.id('recordingResult').textContent;
  assert.match(result, /1 confirmed · 3 failed/);
  assert.match(result, /B · Native state unavailable; no command sent/);
  assert.match(result, /C · Connection lost/);
  assert.match(result, /D · Recording state was not confirmed/);
  assert.equal(ui.id('btnRecordStart').disabled, true);
  assert.equal(ui.id('btnRecordStop').disabled, false);
});

test('Recording batches preserve original targets, limit concurrency and block both buttons during an operation', async () => {
  const pending = [];
  let active = 0, maximum = 0;
  const ui = await consoleUI({recordingAvailable: true, record: () => new Promise(resolve => {
    active++;
    maximum = Math.max(maximum, active);
    pending.push(() => { active--; resolve(confirmed('recording')); });
  })});
  const devices = Array.from({length: 7}, (_, index) => headset(String(index)));
  await ui.select(devices, devices.map(device => device.device_id));
  await ui.task('recording');
  const batch = ui.record('start');
  assert.equal(ui.recordingPosts.length, 4);
  assert.equal(ui.id('btnRecordStart').disabled, true);
  assert.equal(ui.id('btnRecordStop').disabled, true);
  await ui.select([headset('New selection')], ['New selection']);
  await ui.record('start');
  await ui.record('stop');
  assert.equal(ui.recordingPosts.length, 4);
  pending.splice(0).forEach(resolve => resolve());
  await flush();
  assert.equal(ui.recordingPosts.length, 7);
  pending.splice(0).forEach(resolve => resolve());
  await batch;
  await flush();
  assert.equal(maximum, 4);
  assert.deepEqual(ui.recordingPosts.map(item => item.device_id), devices.map(device => device.device_id));
  assert.equal(new Set(ui.recordingPosts.map(item => item.request_id)).size, 7);
  assert.match(ui.id('recordingResult').textContent, /7 confirmed · 0 failed/);
  assert.match(ui.id('recordingState').textContent, /^New selection · Recording stopped$/);
});

test('An older state poll cannot overwrite confirmed batch results', async () => {
  const pending = [];
  let defer = false;
  const ui = await consoleUI({recordingAvailable: true,
    readRecording: () => defer ? new Promise(resolve => pending.push(resolve)) : reply({state: 'stopped'}),
  });
  await ui.select([headset('A'), headset('B')], ['A', 'B']);
  await ui.task('recording');
  defer = true;
  await ui.tick(5000);
  assert.equal(pending.length, 2);
  await ui.record('start');
  pending.forEach(resolve => resolve(reply({state: 'stopped'})));
  await flush();
  assert.equal(ui.id('btnRecordStart').disabled, true);
  assert.equal(ui.id('btnRecordStop').disabled, false);
  assert.equal(ui.id('recordingState').textContent, 'A · Recording active\nB · Recording active');
});

test('State polling has bounded concurrency and checks waiting headsets before refreshing earlier ones', async () => {
  const pending = [];
  const ui = await consoleUI({recordingAvailable: true, readRecording: target => new Promise(resolve => pending.push({target, resolve}))});
  const devices = Array.from({length: 7}, (_, index) => headset(String(index)));
  await ui.select(devices, devices.map(device => device.device_id));
  await ui.task('recording');
  assert.deepEqual(ui.recordingReads, ['0', '1', '2', '3']);
  assert.equal(ui.id('btnRecordStart').disabled, true);
  await ui.tick(6000);
  pending.shift().resolve(reply({state: 'stopped'}));
  await flush();
  assert.deepEqual(ui.recordingReads, ['0', '1', '2', '3', '4']);
  await ui.task('launch');
  pending.splice(0).forEach(({resolve}) => resolve(reply({state: 'stopped'})));
  await flush();
});

test('Deselecting a headset discards its pending state response and reconnecting requires fresh state', async () => {
  let completeA;
  let currentB = 'recording';
  const ui = await consoleUI({recordingAvailable: true,
    readRecording: target => target === 'A' ? new Promise(resolve => { completeA = resolve; }) : reply({state: currentB}),
  });
  await ui.select([headset('A'), headset('B')], ['A']);
  await ui.task('recording');
  await ui.select([headset('A'), headset('B')], ['B']);
  completeA(reply({state: 'stopped'}));
  await flush();
  assert.equal(ui.id('recordingState').textContent, 'B · Recording active');
  assert.equal(ui.id('btnRecordStart').disabled, true);
  ui.id('connText').textContent = 'Disconnected';
  await ui.tick();
  assert.equal(ui.id('btnRecordStop').disabled, true);
  currentB = 'stopped';
  ui.id('connText').textContent = 'Connected';
  await ui.tick();
  assert.deepEqual(ui.recordingReads, ['A', 'B', 'B']);
  assert.equal(ui.id('btnRecordStart').disabled, false);
  assert.equal(ui.id('btnRecordStop').disabled, true);
});

test('Stale or unavailable native state cannot enable either recording button', async () => {
  let fail = false;
  const ui = await consoleUI({recordingAvailable: true,
    readRecording: async () => fail ? reply({error: 'Recording state unavailable.'}, false) : reply({state: 'stopped'}),
  });
  await ui.select([headset('A')], ['A']);
  await ui.task('recording');
  assert.equal(ui.id('btnRecordStart').disabled, false);
  fail = true;
  await ui.tick(11000);
  assert.equal(ui.id('btnRecordStart').disabled, true);
  assert.equal(ui.id('btnRecordStop').disabled, true);
  await ui.record('start');
  await ui.record('stop');
  assert.equal(ui.recordingPosts.length, 0);
  assert.match(ui.id('recordingState').textContent, /Recording state unavailable/);
});

test('Recording controls reject disconnected, unavailable, empty and offline-only selections', async () => {
  for (const scenario of [
    {connected: false, devices: [headset('A')], selected: ['A']},
    {recordingAvailable: false, devices: [headset('A')], selected: ['A']},
    {devices: [headset('A')], selected: []},
    {devices: [headset('A', 'offline')], selected: ['A']},
  ]) {
    const ui = await consoleUI({recordingAvailable: true, ...scenario});
    await ui.select(scenario.devices, scenario.selected);
    await ui.task('recording');
    assert.equal(ui.id('btnRecordStart').disabled, true);
    assert.equal(ui.id('btnRecordStop').disabled, true);
    await ui.record('start');
    await ui.record('stop');
    assert.equal(ui.recordingPosts.length, 0);
    assert.equal(ui.recordingReads.length, 0);
  }
});
