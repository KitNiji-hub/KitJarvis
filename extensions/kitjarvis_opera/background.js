/* A paired, read-only MV3 transport. No page script can call this worker. */
let connection = null;
let generation = 0;
const SITE_ORIGINS = ['http://*/*', 'https://*/*'];

async function removeOptionalSites() {
  if (typeof chrome === 'undefined' || !chrome.permissions?.remove ||
      !chrome.permissions?.contains) return false;
  try {
    await chrome.permissions.remove({ origins: SITE_ORIGINS });
    const remaining = await Promise.all(SITE_ORIGINS.map(
      (origin) => chrome.permissions.contains({ origins: [origin] })));
    return remaining.every((granted) => !granted);
  } catch (_) { return false; }
}

// Optional host grants outlive MV3 worker globals. On every worker start,
// remove a grant left by an abrupt previous worker termination before pairing.
let permissionCleanup = typeof chrome === 'undefined'
  ? Promise.resolve(true) : removeOptionalSites();

function stopBridge() {
  generation += 1;
  const old = connection;
  if (old?.abort) old.abort.abort();
  connection = null;
  if (old?.token) {
    void fetch(`http://127.0.0.1:${old.port}/disconnect`, {
      method: 'POST', headers: { 'Content-Type': 'application/json',
                                Authorization: `Bearer ${old.token}` },
      body: '{}', credentials: 'omit', cache: 'no-store',
    }).catch(() => {});
  }
  // Serialize cleanup so an old removal cannot finish after a new pair.
  permissionCleanup = permissionCleanup.then(removeOptionalSites, removeOptionalSites);
  return permissionCleanup;
}

function normalOrigin(url) {
  if (typeof url !== 'string') throw new Error('unavailable');
  const parsed = new URL(url);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error('unavailable');
  }
  return parsed.origin;
}

async function profileId() {
  const saved = await chrome.storage.local.get('profileId');
  if (typeof saved.profileId === 'string' && /^[0-9a-f]{32}$/.test(saved.profileId)) {
    return saved.profileId;
  }
  const value = crypto.randomUUID().replaceAll('-', '');
  await chrome.storage.local.set({ profileId: value });
  return value;
}

async function post(path, body, token = null, active = connection) {
  if (!active) throw new Error('disconnected');
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`http://127.0.0.1:${active.port}${path}`, {
    method: 'POST', headers, body: JSON.stringify(body), signal: active.abort.signal,
    cache: 'no-store', credentials: 'omit',
  });
  if (!response.ok) throw new Error('bridge refused');
  return response.json();
}

async function pair(port, code) {
  const cleanup = stopBridge();
  const current = generation;
  if (!Number.isInteger(port) || port < 1 || port > 65535 ||
      typeof code !== 'string' || !/^\d{8}$/.test(code)) return { success: false };
  try {
    if (!(await cleanup) || current !== generation) return { success: false };
    const active = { port, abort: new AbortController(), token: null, profileId: null };
    active.profileId = await profileId();
    const response = await post('/pair', { code, profile_id: active.profileId }, null, active);
    if (current !== generation || typeof response.bearer_token !== 'string' ||
        response.bearer_token.length < 32) return { success: false };
    active.token = response.bearer_token;
    connection = active;
    void poll(current, active);
    return { success: true, profile_id: active.profileId };
  } catch (_) {
    return { success: false };
  }
}

function injectedRead(expectedOrigin, maxChars) {
  // This runs in the isolated extension world, only for the documentId target.
  if (location.origin !== expectedOrigin || !document.body) return null;
  return { origin: location.origin, text: document.body.innerText.slice(0, maxChars) };
}

async function readDocument(command, browser = chrome) {
  const { tab_id: tabId, document_id: documentId, expected_origin: origin,
          max_chars: maxChars } = command;
  if (!Number.isInteger(tabId) || tabId < 0 || typeof documentId !== 'string' ||
      !documentId || typeof origin !== 'string' || !Number.isInteger(maxChars) ||
      maxChars < 1 || maxChars > 8192) throw new Error('invalid read');
  const tab = await browser.tabs.get(tabId);
  if (!tab || tab.incognito !== false || normalOrigin(tab.url) !== origin) {
    throw new Error('tab changed');
  }
  const frame = await browser.webNavigation.getFrame({ tabId, frameId: 0 });
  if (!frame || frame.documentId !== documentId || normalOrigin(frame.url) !== origin) {
    throw new Error('document changed');
  }
  // documentIds is essential: a URL check followed by a tabId-only injection
  // could read a new document after navigation. Unsupported API fails closed.
  const result = await browser.scripting.executeScript({
    target: { tabId, documentIds: [documentId] },
    func: injectedRead, args: [origin, maxChars], world: 'ISOLATED',
  });
  if (!Array.isArray(result) || result.length !== 1 ||
      result[0].documentId !== documentId || result[0].frameId !== 0 ||
      !result[0].result || result[0].result.origin !== origin ||
      typeof result[0].result.text !== 'string' ||
      result[0].result.text.length > maxChars) throw new Error('result changed');
  const finalTab = await browser.tabs.get(tabId);
  const finalFrame = await browser.webNavigation.getFrame({ tabId, frameId: 0 });
  if (!finalTab || finalTab.incognito !== false || normalOrigin(finalTab.url) !== origin ||
      !finalFrame || finalFrame.documentId !== documentId ||
      normalOrigin(finalFrame.url) !== origin) throw new Error('document changed');
  return result[0].result.text;
}

async function handleRead(command, current, active) {
  if (command?.type !== 'read' || command.profile_id !== active.profileId ||
      typeof command.request_id !== 'string') return;
  let success = false;
  let text = '';
  try {
    text = await readDocument(command);
    success = true;
  } catch (_) {
    // Browser/DOM errors can contain page text. Never forward or log them.
  }
  if (generation !== current || connection !== active) return;
  try {
    await post('/result', {
      request_id: command.request_id, success, profile_id: active.profileId,
      tab_id: command.tab_id, document_id: command.document_id,
      origin: command.expected_origin, text,
    }, active.token, active);
  } catch (_) { /* disconnected or revoked */ }
}

async function currentTabMetadata(tab, active) {
  if (!tab || tab.incognito !== false) return null;
  try {
    const origin = normalOrigin(tab.url);
    const frame = await chrome.webNavigation.getFrame({ tabId: tab.id, frameId: 0 });
    if (!frame || typeof frame.documentId !== 'string' || !frame.documentId ||
        normalOrigin(frame.url) !== origin) return null;
    return { profile_id: active.profileId, tab_id: tab.id,
             document_id: frame.documentId, origin, incognito: false };
  } catch (_) { return null; }
}

async function selectCurrent() {
  const active = connection;
  if (!active) return { success: false };
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const metadata = tabs.length === 1 ? await currentTabMetadata(tabs[0], active) : null;
    if (!metadata || active !== connection) return { success: false };
    await post('/select', metadata, active.token, active);
    return { success: true };
  } catch (_) { return { success: false }; }
}

async function handleCatalogue(command, current, active) {
  if (command.profile_id !== active.profileId || typeof command.request_id !== 'string' ||
      !Array.isArray(command.excluded_tab_ids) || !Array.isArray(command.excluded_origins)) return;
  try {
    const granted = await chrome.permissions.contains({ origins: ['http://*/*', 'https://*/*'] });
    if (!granted) return;
    const excludedIds = new Set(command.excluded_tab_ids);
    const excludedOrigins = new Set(command.excluded_origins);
    const tabs = [];
    for (const tab of await chrome.tabs.query({})) {
      if (tabs.length >= 128) break;
      if (excludedIds.has(tab.id)) continue;
      const metadata = await currentTabMetadata(tab, active);
      if (metadata && !excludedOrigins.has(metadata.origin)) tabs.push(metadata);
    }
    if (generation !== current || connection !== active) return;
    await post('/result', { kind: 'catalogue', request_id: command.request_id,
                            profile_id: active.profileId, tabs }, active.token, active);
  } catch (_) { /* fail closed; requester times out */ }
}

async function poll(current, active) {
  while (generation === current && connection === active) {
    try {
      const response = await post('/poll', {}, active.token, active);
      if (generation !== current || connection !== active) break;
      if (response.command?.type === 'read') await handleRead(response.command, current, active);
      else if (response.command?.type === 'catalogue') await handleCatalogue(response.command, current, active);
      else if (response.command?.type === 'stop') { stopBridge(); break; }
    } catch (_) {
      if (generation === current && connection === active) void stopBridge();
      break;
    }
  }
}

if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'status') {
      permissionCleanup.then((cleared) => sendResponse({
        paired: !!connection, port: connection?.port ?? null,
        site_permissions_cleared: cleared,
      }));
      return true;
    } else if (message?.type === 'pair') {
      pair(message.port, message.code).then(sendResponse);
      return true;
    } else if (message?.type === 'stop') {
      stopBridge().then((success) => sendResponse({ success }));
      return true;
    } else if (message?.type === 'select_current') {
      selectCurrent().then(sendResponse);
      return true;
    }
  });
  if (chrome.runtime.onSuspend?.addListener) {
    chrome.runtime.onSuspend.addListener(() => { void stopBridge(); });
  }
}

if (typeof module !== 'undefined') module.exports = { normalOrigin, readDocument, injectedRead };
