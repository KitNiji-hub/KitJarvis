const test = require('node:test');
const assert = require('node:assert/strict');
const { parsePairingString, initPopup } = require('../extensions/kitjarvis_opera/popup.js');

const ids = [
  'extension-id-display', 'btn-copy-id', 'status-indicator', 'status-label',
  'view-disconnected', 'view-paired', 'pairing-input', 'btn-pair', 'pairing-error',
  'cleanup-warning', 'btn-select-tab', 'tab-action-status', 'btn-request-all',
  'permission-status', 'btn-disconnect', 'btn-revoke-all',
  'btn-revoke-disconnected', 'revoke-status', 'disconnected-revoke-status',
];

function fakeElement() {
  const classes = new Set(['hidden']);
  const listeners = new Map();
  return {
    value: '', textContent: '', disabled: false,
    classList: {
      toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, callback) { listeners.set(name, callback); },
    click() { listeners.get('click')?.({}); },
    keydown(key) { listeners.get('keydown')?.({ key }); },
  };
}

function setup({ deferPermission = false, deferSelect = false,
                 statusUnavailable = false } = {}) {
  const elements = Object.fromEntries(ids.map((id) => [id, fakeElement()]));
  const state = {
    paired: false, broad: false, messages: [], removeCalls: 0, requestCalls: 0,
    permissionCallback: null, selectCallback: null,
  };
  const doc = { getElementById: (id) => elements[id] };
  const browser = {
    runtime: {
      id: 'a'.repeat(32), lastError: null,
      sendMessage(message, callback) {
        state.messages.push(message);
        if (message.type === 'status') callback(statusUnavailable ? null :
          { paired: state.paired, site_permissions_cleared: true });
        else if (message.type === 'pair') {
          state.paired = true;
          callback({ success: true });
        } else if (message.type === 'select_current') {
          if (deferSelect) state.selectCallback = callback;
          else callback({ success: true });
        }
        else if (message.type === 'stop') {
          state.paired = false;
          callback({ success: true });
        }
      },
    },
    permissions: {
      request(_query, callback) {
        state.requestCalls++;
        if (deferPermission) state.permissionCallback = callback;
        else { state.broad = true; callback(true); }
      },
      remove(_query, callback) {
        state.removeCalls++;
        state.broad = false;
        callback(true);
      },
      contains(_query, callback) { callback(state.broad); },
    },
  };
  initPopup(doc, browser, { writeText: async () => {} });
  return { elements, state, browser };
}

test('one-paste pairing parser preserves leading-zero code and rejects ambiguous input', () => {
  assert.deepEqual(parsePairingString(' 54321-00123456 '),
    { port: 54321, code: '00123456' });
  for (const bad of ['', '12345678', '0-12345678', '65536-12345678',
                     '1234-1234567', '1234-123456789', '1234 -12345678',
                     '1e3-12345678', '1234-1234abcd']) {
    assert.equal(parsePairingString(bad), null, bad);
  }
});

test('malformed paste never reaches the pairing message', () => {
  const { elements, state } = setup();
  elements['pairing-input'].value = 'bad';
  elements['btn-pair'].click();
  assert.equal(state.messages.filter((m) => m.type === 'pair').length, 0);
  assert.match(elements['pairing-error'].textContent, /Paste a code/);
});

test('valid paste pairs and selected-tab action retains the narrow default', () => {
  const { elements, state } = setup();
  elements['pairing-input'].value = '45001-00123456';
  elements['pairing-input'].keydown('Enter');
  assert.deepEqual(state.messages.find((m) => m.type === 'pair'),
    { type: 'pair', port: 45001, code: '00123456' });
  assert.equal(elements['view-paired'].classList.contains('active'), true);
  assert.equal(elements['pairing-input'].value, '');
  elements['btn-select-tab'].click();
  assert.equal(state.messages.at(-1).type, 'select_current');
  assert.match(elements['tab-action-status'].textContent, /selected/);
  assert.equal(state.broad, false);
});

test('permission prompt completing after disconnect removes broad permission', () => {
  const { elements, state } = setup({ deferPermission: true });
  elements['pairing-input'].value = '45001-12345678';
  elements['btn-pair'].click();
  elements['btn-request-all'].click();
  assert.equal(typeof state.permissionCallback, 'function');
  elements['btn-disconnect'].click();
  state.broad = true;
  state.permissionCallback(true);
  assert.equal(state.removeCalls, 1);
  assert.equal(state.broad, false);
});

test('denied permission request cleans a partial grant and unlocks retry', () => {
  const { elements, state } = setup({ deferPermission: true });
  elements['pairing-input'].value = '45001-12345678';
  elements['btn-pair'].click();
  elements['btn-request-all'].click();
  state.broad = true;
  state.permissionCallback(false);
  assert.equal(state.broad, false);
  assert.equal(state.removeCalls, 1);
  assert.equal(elements['btn-request-all'].disabled, false);
  assert.match(elements['permission-status'].textContent, /did not grant/);
});

test('pending permission request cannot overlap and late grant after revoke is removed', () => {
  const { elements, state } = setup({ deferPermission: true });
  elements['pairing-input'].value = '45001-12345678';
  elements['btn-pair'].click();
  elements['btn-request-all'].click();
  elements['btn-request-all'].click();
  assert.equal(state.requestCalls, 1);
  elements['btn-revoke-all'].click();
  state.broad = true;
  state.permissionCallback(true);
  assert.equal(state.broad, false);
  assert.equal(state.removeCalls, 2);
  assert.equal(elements['btn-request-all'].disabled, false);
});

test('manual revoke remains available while disconnected', () => {
  const { elements, state } = setup();
  state.broad = true;
  elements['btn-revoke-disconnected'].click();
  assert.equal(state.removeCalls, 1);
  assert.equal(state.broad, false);
  assert.match(elements['disconnected-revoke-status'].textContent, /revoked/);
});

test('unknown extension status visibly offers manual permission cleanup', () => {
  const { elements } = setup({ statusUnavailable: true });
  assert.equal(elements['view-disconnected'].classList.contains('active'), true);
  assert.equal(elements['cleanup-warning'].classList.contains('hidden'), false);
});

test('superseded action leaves its button usable and ignores late callback', () => {
  const { elements, state } = setup({ deferSelect: true });
  elements['pairing-input'].value = '45001-12345678';
  elements['btn-pair'].click();
  elements['btn-select-tab'].click();
  assert.equal(elements['btn-select-tab'].disabled, true);
  elements['btn-revoke-all'].click();
  assert.equal(elements['btn-select-tab'].disabled, false);
  state.selectCallback({ success: true });
  assert.equal(elements['tab-action-status'].textContent, '');
});
