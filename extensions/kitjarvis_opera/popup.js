/* Operator-present UI for the read-only KitJarvis Opera transport. */
const OPTIONAL_ORIGINS = ['http://*/*', 'https://*/*'];

function parsePairingString(value) {
  if (typeof value !== 'string') return null;
  const match = /^([1-9][0-9]{0,4})-([0-9]{8})$/.exec(value.trim());
  if (!match) return null;
  const port = Number(match[1]);
  return port <= 65535 ? { port, code: match[2] } : null;
}

function initPopup(doc = document, browser = chrome, clipboard = navigator.clipboard) {
  const get = (id) => doc.getElementById(id);
  const ui = {
    id: get('extension-id-display'), copyId: get('btn-copy-id'),
    indicator: get('status-indicator'), status: get('status-label'),
    disconnected: get('view-disconnected'), paired: get('view-paired'),
    input: get('pairing-input'), pair: get('btn-pair'), error: get('pairing-error'),
    cleanupWarning: get('cleanup-warning'),
    select: get('btn-select-tab'), selectStatus: get('tab-action-status'),
    requestAll: get('btn-request-all'), permissionStatus: get('permission-status'),
    disconnect: get('btn-disconnect'), revoke: get('btn-revoke-all'),
    revokeDisconnected: get('btn-revoke-disconnected'),
    revokeStatus: get('revoke-status'),
    disconnectedRevokeStatus: get('disconnected-revoke-status'),
  };
  let generation = 0;
  let connected = false;
  let permissionOps = 0;

  function startPermissionOp() {
    permissionOps += 1;
    ui.requestAll.disabled = true;
  }

  function finishPermissionOp() {
    permissionOps -= 1;
    ui.requestAll.disabled = permissionOps > 0;
  }

  function nextGeneration() {
    generation += 1;
    // An older callback may now be ignored; do not strand its disabled button.
    ui.pair.disabled = false;
    ui.select.disabled = false;
    ui.requestAll.disabled = permissionOps > 0;
    ui.disconnect.disabled = false;
    return generation;
  }

  function feedback(element, message) {
    element.textContent = message;
    element.classList.toggle('hidden', !message);
  }

  function send(type, fields, callback) {
    browser.runtime.sendMessage({ type, ...fields }, (response) => {
      callback(browser.runtime.lastError ? null : response);
    });
  }

  function showConnection(paired) {
    connected = paired;
    ui.disconnected.classList.toggle('active', !paired);
    ui.disconnected.classList.toggle('hidden', paired);
    ui.paired.classList.toggle('active', paired);
    ui.paired.classList.toggle('hidden', !paired);
    ui.indicator.classList.toggle('connected', paired);
    ui.indicator.classList.toggle('disconnected', !paired);
    ui.status.textContent = paired ? 'Connected' : 'Disconnected';
    if (paired) {
      ui.input.value = '';
      feedback(ui.error, '');
    }
  }

  function refreshStatus() {
    const current = nextGeneration();
    send('status', {}, (response) => {
      if (current !== generation) return;
      showConnection(!!response?.paired);
      ui.cleanupWarning.classList.toggle('hidden', !!response && response.site_permissions_cleared !== false);
    });
  }

  function verifySitePermission(element, removalErrored = false, done = () => {}) {
    browser.permissions.contains({ origins: [OPTIONAL_ORIGINS[0]] }, (httpGranted) => {
      const httpError = !!browser.runtime.lastError;
      browser.permissions.contains({ origins: [OPTIONAL_ORIGINS[1]] }, (httpsGranted) => {
        const failed = removalErrored || httpError || !!browser.runtime.lastError ||
          httpGranted || httpsGranted;
        feedback(element, failed
          ? 'Could not verify removal. Revoke site access in Opera extension settings.'
          : 'All-site website permission revoked.');
        ui.cleanupWarning.classList.toggle('hidden', !failed);
        done();
      });
    });
  }

  function removeSitePermission(element) {
    startPermissionOp();
    browser.permissions.remove({ origins: OPTIONAL_ORIGINS }, () => {
      verifySitePermission(element, !!browser.runtime.lastError, finishPermissionOp);
    });
  }

  ui.id.textContent = browser.runtime.id;
  ui.copyId.addEventListener('click', async () => {
    try {
      if (!clipboard?.writeText) throw new Error('clipboard unavailable');
      await clipboard.writeText(browser.runtime.id);
      ui.copyId.textContent = 'Copied';
    } catch (_) {
      // Clipboard access varies by browser. Select the ID for Ctrl+C instead.
      const range = doc.createRange();
      range.selectNodeContents(ui.id);
      const selection = doc.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      ui.copyId.textContent = 'Selected — press Ctrl+C';
    }
  });

  ui.pair.addEventListener('click', () => {
    const parsed = parsePairingString(ui.input.value);
    if (!parsed) {
      feedback(ui.error, 'Paste a code like 54321-12345678 from Jarvis Settings.');
      return;
    }
    const current = nextGeneration();
    ui.pair.disabled = true;
    ui.status.textContent = 'Connecting…';
    feedback(ui.error, '');
    send('pair', parsed, (response) => {
      if (current !== generation) return;
      ui.pair.disabled = false;
      if (response?.success) {
        refreshStatus();
      } else {
        ui.status.textContent = 'Disconnected';
        feedback(ui.error, 'Could not connect. Generate a fresh code in Jarvis Settings and try again.');
      }
    });
  });
  ui.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') ui.pair.click();
  });

  ui.select.addEventListener('click', () => {
    if (!connected) return;
    const current = nextGeneration();
    ui.select.disabled = true;
    send('select_current', {}, (response) => {
      if (current !== generation) return;
      ui.select.disabled = false;
      feedback(ui.selectStatus, response?.success
        ? 'This tab is selected. Jarvis can read it after you authorize selected tabs in Settings.'
        : 'This tab is unavailable. Use a normal web page and try again.');
    });
  });

  ui.requestAll.addEventListener('click', () => {
    if (!connected || permissionOps) return;
    const current = nextGeneration();
    startPermissionOp();
    browser.permissions.request({ origins: OPTIONAL_ORIGINS }, (granted) => {
      if (!granted || browser.runtime.lastError) {
        removeSitePermission(ui.permissionStatus);
        finishPermissionOp();
        if (current === generation) {
          feedback(ui.permissionStatus, 'Opera did not grant all-site access.');
        }
        return;
      }
      send('status', {}, (status) => {
        if (current !== generation || !status?.paired) {
          // A permission prompt may finish after disconnection. Fail closed.
          removeSitePermission(ui.permissionStatus);
          finishPermissionOp();
          return;
        }
        browser.permissions.contains({ origins: OPTIONAL_ORIGINS }, (stillGranted) => {
          if (current !== generation || !stillGranted || browser.runtime.lastError) {
            removeSitePermission(ui.permissionStatus);
            finishPermissionOp();
            if (current === generation) feedback(ui.permissionStatus,
              'Permission was not retained. Reconnect and try again.');
            return;
          }
          finishPermissionOp();
          feedback(ui.permissionStatus, stillGranted && !browser.runtime.lastError
            ? 'Opera granted all-site access. Authorize matching all-tabs scope in Jarvis Settings.'
            : 'Permission was not retained. Reconnect and try again.');
        });
      });
    });
  });

  ui.disconnect.addEventListener('click', () => {
    const current = nextGeneration();
    ui.disconnect.disabled = true;
    send('stop', {}, () => {
      if (current !== generation) return;
      ui.disconnect.disabled = false;
      refreshStatus();
    });
  });

  ui.revoke.addEventListener('click', () => {
    nextGeneration();
    removeSitePermission(ui.revokeStatus);
  });
  ui.revokeDisconnected.addEventListener('click', () => {
    nextGeneration();
    removeSitePermission(ui.disconnectedRevokeStatus);
  });

  refreshStatus();
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => initPopup());
}
if (typeof module !== 'undefined') module.exports = { parsePairingString, initPopup };
