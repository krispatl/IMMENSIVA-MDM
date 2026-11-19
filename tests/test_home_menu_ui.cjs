const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../immensiva_mdm/web/monitor.js'), 'utf8');
const homeMenuCode = source.slice(source.indexOf('function homeMenuSummary('), source.indexOf('function restoreDuration('));

for (const previous of [null, {mode: 'lock', confirmed: 5, skipped: 15, failed: 0}]) {
  test(`Home result survives a polling refresh with ${previous ? 'a previous result' : 'no previous result'}`, async () => {
    let completeRequest;
    const notifications = [];
    const originalState = {connected: true, home_menu: previous, home_menu_busy: false};
    const context = vm.createContext({
      state: originalState,
      bulkBusy: false,
      homeMenuPending: null,
      busyDevices: new Set(),
      render() {},
      async poll() {},
      notify(message) { notifications.push(message); },
      request(endpoint, payload) {
        assert.equal(endpoint, '/api/home-menu');
        assert.equal(payload.mode, 'restore');
        return new Promise(resolve => { completeRequest = resolve; });
      },
    });
    vm.runInContext(homeMenuCode, context);
    const operation = context.runHomeMenu('restore');
    // The regular fleet poll replaces the entire state while the command waits.
    const refreshedState = {connected: true, home_menu: previous, home_menu_busy: true};
    context.state = refreshedState;
    const result = {mode: 'restore', confirmed: 2, skipped: 15, failed: 3};
    completeRequest(result);
    await operation;
    assert.deepEqual(notifications, ['Last command: Enable · 2 confirmed · 15 skipped · 3 failed. See Activity for details.']);
    assert.equal(refreshedState.home_menu, result);
    assert.equal(originalState.home_menu, previous);
    assert.equal(context.bulkBusy, false);
    assert.equal(context.homeMenuPending, null);
  });
}
