const assert = require('node:assert/strict');
const test = require('node:test');
const {consoleUI, flush, headset, success} = require('./helpers/venue_console.cjs');

test('Open URL sends to every selected online headset and skips offline and unselected devices', async () => {
  const ui = await consoleUI();
  await ui.select([headset('A'), headset('B'), headset('C', 'offline'), headset('D')], ['A', 'B', 'C']);
  assert.equal(ui.id('btnOpenUrl').disabled, false);
  assert.equal(ui.id('btnOpenUrl').textContent, 'Open URL on 2 headsets');
  const url = 'https://example.com/?a=1&b=two#room';
  ui.id('operatorUrl').value = url;
  await ui.submit();
  assert.deepEqual(ui.posts, [{device_id: 'A', url}, {device_id: 'B', url}]);
  assert.match(ui.id('browserResult').textContent, /2 sent · 0 failed · 1 offline skipped/);
  assert.match(ui.id('browserResult').textContent, /A · URL sent/);
  assert.match(ui.id('browserResult').textContent, /B · URL sent/);
  assert.equal(ui.id('btnOpenUrl').disabled, false);
});

test('One failed headset does not prevent other URL requests or hide their results', async () => {
  const ui = await consoleUI({respond: async ({device_id}) => {
    if (device_id === 'B') return {ok: false, json: async () => ({error: 'Headset is offline or unknown.'})};
    if (device_id === 'C') throw new Error('Connection lost');
    return success();
  }});
  await ui.select(['A', 'B', 'C'].map(id => headset(id)), ['A', 'B', 'C']);
  ui.id('operatorUrl').value = 'http://192.0.2.10/';
  await ui.submit();
  assert.equal(ui.posts.length, 3);
  assert.match(ui.id('browserResult').textContent, /1 sent · 2 failed/);
  assert.match(ui.id('browserResult').textContent, /B · Headset is offline or unknown/);
  assert.match(ui.id('browserResult').textContent, /C · Connection lost/);
  assert.equal(ui.id('operatorUrl').disabled, false);
});

test('A batch keeps its original targets and URL, limits concurrency and blocks duplicate submission', async () => {
  const pending = [];
  let active = 0, maximumActive = 0;
  const ui = await consoleUI({respond: () => new Promise(resolve => {
    active++;
    maximumActive = Math.max(active, maximumActive);
    pending.push(() => { active--; resolve(success()); });
  })});
  const devices = Array.from({length: 7}, (_, index) => headset(String(index)));
  await ui.select(devices, devices.map(device => device.device_id));
  const url = 'https://example.com/original';
  ui.id('operatorUrl').value = url;
  const batch = ui.submit();
  assert.equal(ui.posts.length, 4);
  assert.equal(ui.id('btnOpenUrl').disabled, true);
  assert.equal(ui.id('operatorUrl').disabled, true);
  await ui.select([headset('New selection')], ['New selection']);
  ui.id('operatorUrl').value = 'https://example.com/changed';
  await ui.submit();
  assert.equal(ui.posts.length, 4);
  pending.splice(0).forEach(resolve => resolve());
  await flush();
  assert.equal(ui.posts.length, 7);
  pending.splice(0).forEach(resolve => resolve());
  await batch;
  assert.equal(maximumActive, 4);
  assert.deepEqual(ui.posts, devices.map(device => ({device_id: device.device_id, url})));
  assert.match(ui.id('browserResult').textContent, /7 sent · 0 failed/);
  assert.equal(ui.id('btnOpenUrl').disabled, false);
  assert.equal(ui.id('btnOpenUrl').textContent, 'Open URL on headset');
});

test('Disconnected, unavailable, empty and offline-only selections cannot submit', async () => {
  for (const scenario of [
    {connected: false, devices: [headset('A')], selected: ['A']},
    {available: false, devices: [headset('A')], selected: ['A']},
    {devices: [headset('A')], selected: []},
    {devices: [headset('A', 'offline')], selected: ['A']},
  ]) {
    const ui = await consoleUI(scenario);
    await ui.select(scenario.devices, scenario.selected);
    ui.id('operatorUrl').value = 'https://example.com/';
    assert.equal(ui.id('btnOpenUrl').disabled, true);
    await ui.submit();
    assert.equal(ui.posts.length, 0);
  }
});

test('A single selected headset still works and invalid URL schemes never submit', async () => {
  const ui = await consoleUI();
  await ui.select([headset('A')], ['A']);
  ui.id('operatorUrl').value = 'file:///sdcard/example.html';
  await ui.submit();
  assert.equal(ui.posts.length, 0);
  assert.match(ui.id('operatorUrl').validationMessage, /http/);
  ui.id('operatorUrl').value = 'https://example.com/';
  ui.id('operatorUrl').dispatchEvent({type: 'input'});
  assert.equal(ui.id('operatorUrl').validationMessage, '');
  await ui.submit();
  assert.equal(ui.posts.length, 1);
  assert.match(ui.id('browserResult').textContent, /1 sent · 0 failed/);
});

test('Close tabs needs no URL, targets all selected online headsets and skips offline devices', async () => {
  const ui = await consoleUI();
  await ui.select([headset('A'), headset('B'), headset('C', 'offline'), headset('D')], ['A', 'B', 'C']);
  assert.equal(ui.id('operatorUrl').value, '');
  assert.equal(ui.id('btnCloseBrowserTabs').disabled, false);
  await ui.closeTabs();
  assert.deepEqual(ui.closePosts, [{device_id: 'A'}, {device_id: 'B'}]);
  assert.equal(ui.posts.length, 0);
  assert.match(ui.id('browserResult').textContent, /Close tabs complete · 2 confirmed · 0 failed · 1 offline skipped/);
  assert.match(ui.id('browserResult').textContent, /A · Closed all 2 browser tabs/);
  assert.equal(ui.id('btnOpenUrl').disabled, false);
});

test('Close tabs reports partial and unconfirmed responses as individual failures', async () => {
  const ui = await consoleUI({closeTabs: async ({device_id}) => {
    if (device_id === 'A') return {ok: false, json: async () => ({status: 'partial', message: 'Closed 2 tabs; 1 remains.'})};
    if (device_id === 'B') return {ok: true, json: async () => ({status: 'partial', message: 'Not confirmed.'})};
    return {ok: true, json: async () => ({status: 'confirmed', message: 'No open browser tabs.'})};
  }});
  await ui.select(['A', 'B', 'C'].map(id => headset(id)), ['A', 'B', 'C']);
  await ui.closeTabs();
  assert.equal(ui.closePosts.length, 3);
  assert.match(ui.id('browserResult').textContent, /1 confirmed · 2 failed/);
  assert.match(ui.id('browserResult').textContent, /A · Closed 2 tabs; 1 remains/);
  assert.match(ui.id('browserResult').textContent, /B · Not confirmed/);
  assert.match(ui.id('browserResult').textContent, /C · No open browser tabs/);
});

test('Close tabs holds the original selection and blocks opening or closing again while busy', async () => {
  const pending = [];
  const ui = await consoleUI({closeTabs: () => new Promise(resolve => pending.push(resolve))});
  const devices = Array.from({length: 6}, (_, index) => headset(String(index)));
  await ui.select(devices, devices.map(device => device.device_id));
  const batch = ui.closeTabs();
  assert.equal(ui.closePosts.length, 4);
  assert.equal(ui.id('btnCloseBrowserTabs').disabled, true);
  assert.equal(ui.id('btnOpenUrl').disabled, true);
  assert.equal(ui.id('btnCloseBrowserTabs').textContent, 'Closing tabs…');
  await ui.select([headset('New')], ['New']);
  ui.id('operatorUrl').value = 'https://example.com/';
  await ui.submit();
  await ui.closeTabs();
  assert.equal(ui.posts.length, 0);
  const result = {ok: true, json: async () => ({status: 'confirmed', message: 'Tabs closed.'})};
  pending.splice(0).forEach(resolve => resolve(result));
  await flush();
  assert.equal(ui.closePosts.length, 6);
  pending.splice(0).forEach(resolve => resolve(result));
  await batch;
  assert.deepEqual(ui.closePosts, devices.map(device => ({device_id: device.device_id})));
  assert.match(ui.id('browserResult').textContent, /6 confirmed · 0 failed/);
  assert.equal(ui.id('btnCloseBrowserTabs').disabled, false);
});

test('Unavailable, disconnected, empty and offline-only selections cannot close tabs', async () => {
  for (const scenario of [
    {connected: false, devices: [headset('A')], selected: ['A']},
    {available: false, devices: [headset('A')], selected: ['A']},
    {devices: [headset('A')], selected: []},
    {devices: [headset('A', 'offline')], selected: ['A']},
  ]) {
    const ui = await consoleUI(scenario);
    await ui.select(scenario.devices, scenario.selected);
    assert.equal(ui.id('btnCloseBrowserTabs').disabled, true);
    await ui.closeTabs();
    assert.equal(ui.closePosts.length, 0);
  }
});
