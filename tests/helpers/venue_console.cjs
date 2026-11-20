const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../immensiva_mdm/web/venue.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const headset = (device_id, status = 'online') => ({device_id, label: device_id, status});
const success = () => ({ok: true, json: async () => ({message: 'URL sent to the headset browser.'})});

// Run the complete operator script with DOM events and controllable HTTP responses.
async function consoleUI({available = true, connected = true, respond = success,
  closeTabs = async () => ({ok: true, json: async () => ({status: 'confirmed', closed: 2, remaining: 0, message: 'Closed all 2 browser tabs.'})}),
  recordingAvailable = false,
  readRecording = async () => ({ok: true, json: async () => ({state: 'stopped'})}),
  record = async ({action}) => ({ok: true, json: async () => ({status: 'confirmed', state: action === 'start' ? 'recording' : 'stopped', message: 'Confirmed.'})}),
} = {}) {
  let now = 1000000;
  const intervals = [];
  class Element {
    constructor() {
      this.listeners = {};
      this.dataset = {};
      this.classList = {toggle() {}, remove() {}, contains() { return false; }};
      this.textContent = '';
      this.value = '';
      this.options = [];
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    dispatchEvent(event) { return this.listeners[event.type]?.(event); }
    setAttribute() {}
    append() {}
    prepend() {}
    after() {}
    before() {}
    click() { return this.dispatchEvent({type: 'click'}); }
    querySelector(selector) { return selector === '.empty' ? null : new Element(); }
    setCustomValidity(message) { this.validationMessage = message; }
    reportValidity() {}
  }
  const nodes = new Map();
  const id = name => {
    if (!nodes.has(name)) nodes.set(name, new Element());
    return nodes.get(name);
  };
  const taskButtons = ['launch', 'install', 'files', 'browser', 'recording', 'maintenance'].map(name => {
    const button = id('task-' + name);
    button.dataset.task = name;
    return button;
  });
  const document = new Element();
  Object.assign(document, {
    body: new Element(),
    getElementById: id,
    createElement: () => new Element(),
    querySelector: id,
    querySelectorAll: selector => selector === '[data-task]' ? taskButtons : [],
  });
  id('connText').textContent = connected ? 'Connected' : 'Disconnected';
  const posts = [], closePosts = [], recordingPosts = [], recordingReads = [];
  vm.runInNewContext(source, {
    document, location: {hostname: 'localhost'}, queueMicrotask, crypto: webcrypto, Date: class extends Date { static now() { return now; } },
    Event: class { constructor(type) { this.type = type; } },
    MutationObserver: class { observe() {} }, setInterval(callback) { intervals.push(callback); },
    async fetch(endpoint, options) {
      if (!options) return {ok: true, json: async () => ({available: endpoint === '/api/open-url' ? available : recordingAvailable})};
      if (endpoint.startsWith('/api/screen-recording?')) {
        assert.equal(options.cache, 'no-store');
        const target = decodeURIComponent(endpoint.split('device_id=')[1]);
        recordingReads.push(target);
        return readRecording(target);
      }
      if (endpoint === '/api/screen-recording') {
        assert.equal(options.method, 'POST');
        const payload = JSON.parse(options.body);
        recordingPosts.push(payload);
        return record(payload);
      }
      if (endpoint === '/api/browser/close-tabs') {
        assert.equal(options.method, 'POST');
        const payload = JSON.parse(options.body);
        closePosts.push(payload);
        return closeTabs(payload);
      }
      assert.equal(endpoint, '/api/open-url');
      assert.equal(options.method, 'POST');
      const payload = JSON.parse(options.body);
      posts.push(payload);
      return respond(payload);
    },
  });
  document.dispatchEvent({type: 'DOMContentLoaded'});
  await flush();
  return {
    id, posts, closePosts, recordingPosts, recordingReads, document,
    closeTabs() { return id('btnCloseBrowserTabs').click(); },
    async task(name) { id('task-' + name).click(); await flush(); },
    async tick(milliseconds = 0) { now += milliseconds; intervals.forEach(callback => callback()); await flush(); },
    record(action) { return id(action === 'start' ? 'btnRecordStart' : 'btnRecordStop').click(); },
    async select(devices, selected) {
      document.dispatchEvent({type: 'venue:state', detail: {devices, selected, groups: {}}});
      await flush();
    },
    submit() { return id('operatorBrowser').dispatchEvent({type: 'submit', preventDefault() {}}); },
  };
}

module.exports = {consoleUI, flush, headset, success};
