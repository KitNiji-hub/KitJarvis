const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { normalOrigin, readDocument } = require('../extensions/kitjarvis_opera/background.js');

const command = { tab_id: 7, document_id: 'doc-1', expected_origin: 'https://example.test', max_chars: 20 };

function browser({ incognito = false, url = 'https://example.test/page', frameId = 'doc-1',
                   resultId = 'doc-1', afterUrl = url } = {}) {
  let reads = 0;
  let tabGets = 0;
  const fake = {
    tabs: { get: async () => ({ url: ++tabGets === 1 ? url : afterUrl, incognito }) },
    webNavigation: { getFrame: async () => ({ url, documentId: frameId }) },
    scripting: { executeScript: async ({ target }) => {
      reads++;
      assert.deepEqual(target, { tabId: 7, documentIds: ['doc-1'] });
      return [{ frameId: 0, documentId: resultId,
                result: { origin: 'https://example.test', text: 'synthetic page' } }];
    } },
  };
  return { fake, reads: () => reads };
}

test('normal web origin is required', () => {
  assert.equal(normalOrigin('https://example.test/page'), 'https://example.test');
  assert.throws(() => normalOrigin('opera://settings'));
  assert.throws(() => normalOrigin('https://u:p@example.test'));
});

test('same document yields bounded synthetic content', async () => {
  const { fake, reads } = browser();
  assert.equal(await readDocument(command, fake), 'synthetic page');
  assert.equal(reads(), 1);
});

test('private tab and stale document fail before DOM access', async () => {
  for (const opts of [{ incognito: true }, { frameId: 'new-doc' }, { url: 'file:///private' }]) {
    const { fake, reads } = browser(opts);
    await assert.rejects(readDocument(command, fake));
    assert.equal(reads(), 0);
  }
});

test('navigation and wrong injection document discard content', async () => {
  for (const opts of [{ afterUrl: 'https://other.test/' }, { resultId: 'new-doc' }]) {
    const { fake, reads } = browser(opts);
    await assert.rejects(readDocument(command, fake));
    assert.equal(reads(), 1);
  }
});

function syntheticWorker({ firstRemoveGate = null, httpPermissionStuck = false } = {}) {
  let broadPermission = true;
  let removeCalls = 0;
  const pollRejects = [];
  const calls = [];
  const chrome = {
    permissions: {
      remove: async () => {
        if (++removeCalls === 1 && firstRemoveGate) await firstRemoveGate;
        broadPermission = false;
        return true;
      },
      contains: async ({ origins }) =>
        httpPermissionStuck && origins.length === 1 && origins[0] === 'http://*/*'
          ? true : broadPermission,
    },
    storage: { local: { get: async () => ({ profileId: 'b'.repeat(32) }) } },
    runtime: { onMessage: { addListener: () => {} } },
  };
  const fetch = async (url) => {
    calls.push(url);
    if (url.endsWith('/pair')) {
      return { ok: true, json: async () => ({ bearer_token: 'x'.repeat(40) }) };
    }
    if (url.endsWith('/poll')) return new Promise((_resolve, reject) => pollRejects.push(reject));
    return { ok: true, json: async () => ({}) };
  };
  const source = fs.readFileSync(require.resolve('../extensions/kitjarvis_opera/background.js'), 'utf8');
  const context = vm.createContext({ chrome, fetch, AbortController, URL, module: { exports: {} } });
  vm.runInContext(source, context);
  return { context, pollRejects, calls,
           get broadPermission() { return broadPermission; },
           grantBroadPermission() { broadPermission = true; } };
}

test('new worker removes stale broad permission before accepting a pair', async () => {
  const worker = syntheticWorker();
  assert.equal(await vm.runInContext('permissionCleanup', worker.context), true);
  assert.equal(worker.broadPermission, false);
  const paired = await vm.runInContext('pair(43001, "12345678")', worker.context);
  assert.equal(paired.success, true);
  worker.grantBroadPermission();
  assert.equal(await vm.runInContext('stopBridge()', worker.context), true);
  assert.equal(worker.broadPermission, false);
});

test('pair waits for startup permission cleanup', async () => {
  let releaseCleanup;
  const gate = new Promise((resolve) => { releaseCleanup = resolve; });
  const worker = syntheticWorker({ firstRemoveGate: gate });
  const pairing = vm.runInContext('pair(43001, "12345678")', worker.context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(worker.calls.filter((url) => url.endsWith('/pair')).length, 0);
  releaseCleanup();
  assert.equal((await pairing).success, true);
  assert.equal(worker.broadPermission, false);
  await vm.runInContext('stopBridge()', worker.context);
});

test('a single retained site permission fails pairing closed', async () => {
  const worker = syntheticWorker({ httpPermissionStuck: true });
  assert.equal(await vm.runInContext('permissionCleanup', worker.context), false);
  assert.equal((await vm.runInContext('pair(43001, "12345678")', worker.context)).success, false);
  assert.equal(worker.calls.filter((url) => url.endsWith('/pair')).length, 0);
});

test('late failure from old poll cannot revoke a newer pairing', async () => {
  const worker = syntheticWorker();
  assert.equal((await vm.runInContext('pair(43001, "12345678")', worker.context)).success, true);
  assert.equal((await vm.runInContext('pair(43002, "12345678")', worker.context)).success, true);
  assert.equal(worker.pollRejects.length, 2);
  worker.pollRejects[0](new Error('old poll aborted'));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(vm.runInContext('connection.port', worker.context), 43002);
  assert.equal(worker.calls.filter((url) => url.endsWith('/pair')).length, 2);
  await vm.runInContext('stopBridge()', worker.context);
});
