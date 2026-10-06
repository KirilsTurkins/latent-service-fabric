// One maintained frontend journey over real shared ingress. The node conductor
// selects and attests the actual guest publication before each signalled phase.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';

assert.equal(process.version, 'v24.19.0');
assert.equal(process.argv.length, 3);
const bytes = await readFile(process.argv[2]);
assert.ok(bytes.length <= 32768);
const config = JSON.parse(bytes);
assert.equal(config.schemaVersion, 'latent.stateful-reference.browser-input.v1');
assert.match(config.origin, /^http:\/\/stateful\.test:19092$/);
assert.ok(['single-backend', 'six-backend-matrix'].includes(config.scope));
const languages = ['rust', 'c', 'typescript', 'go', 'java', 'dotnet'];
assert.ok(Array.isArray(config.backends) && [1, 6].includes(config.backends.length));
assert.equal(config.backends.length, config.scope === 'single-backend' ? 1 : 6);
assert.equal(new Set(config.backends.map(row => row.language)).size, config.backends.length);
assert.ok(config.backends.every(row => languages.includes(row.language)));
if (config.scope === 'six-backend-matrix') assert.deepEqual(config.backends.map(row => row.language).sort(), [...languages].sort());
for (const row of config.backends) {
  for (const key of ['componentDigest', 'compilerInputsDigest', 'sourceSnapshotDigest', 'hostAbiDigest'])
    assert.match(row[key], /^sha256:[0-9a-f]{64}$/);
  assert.match(row.publication, /^publication:sha256:[0-9a-f]{64}$/);
}
assert.match(config.frontend.publication, /^publication:sha256:[0-9a-f]{64}$/);
assert.match(config.frontend.client.path, /^\/client\/[a-zA-Z0-9._-]+\.js$/);
assert.match(config.frontend.client.digest, /^sha256:[0-9a-f]{64}$/);
assert.ok(Number.isInteger(config.frontend.client.bytes) && config.frontend.client.bytes > 0 && config.frontend.client.bytes <= 8 * 1024 * 1024);
assert.equal(config.users.length, 2);
assert.deepEqual(config.users.map(user => user.subject).sort(), ['alice', 'bob']);
for (const user of config.users) assert.ok(typeof user.token === 'string' && /^[A-Za-z0-9._~-]{16,512}$/.test(user.token));
const alice = config.users.find(user => user.subject === 'alice');
assert.ok(typeof alice.rotatedToken === 'string' && /^[A-Za-z0-9._~-]{16,512}$/.test(alice.rotatedToken) && alice.rotatedToken !== alice.token);
const forbidden = [...config.users.map(user => user.token), alice.rotatedToken];
const {chromium} = createRequire(path.join(path.resolve(config.toolchain), 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: config.chrome, headless: true,
  args: ['--host-resolver-rules=MAP stateful.test 127.0.0.1', '--no-proxy-server']});
const deadline = setTimeout(() => { process.exitCode = 1; void browser.close(); }, 240000);
const observations = [], failures = [], assets = [], contexts = [];
let requests = 0;
const digest = value => 'sha256:' + createHash('sha256').update(value).digest('hex');

function emit(value) {
  const data = JSON.stringify(value);
  assert.ok(Buffer.byteLength(data) <= 32768);
  assert.ok(forbidden.every(secret => !data.includes(secret)));
  process.stdout.write(data + '\n');
}
function nextBackend(language) {
  return new Promise(resolve => {
    process.once('SIGUSR1', resolve);
    emit({event: 'waiting', phase: 'backend-selected', language});
  });
}
async function context(user) {
  const selected = await browser.newContext({extraHTTPHeaders: {Authorization: 'Bearer ' + user.token}, serviceWorkers: 'block'});
  contexts.push(selected);
  selected.on('page', page => {
    page.on('pageerror', error => { if (failures.length < 16) failures.push(digest(error.message)); });
    page.on('request', request => {
      assert.ok(++requests <= 256);
      const url = new URL(request.url());
      assert.equal(url.origin, config.origin);
      assert.ok(!/catalog|metadata|renderer|alice-read|bob-read|latent-effects/.test(url.pathname));
      assert.ok(['GET', 'POST'].includes(request.method()));
    });
  });
  return selected;
}
async function hydrate(selected, subject) {
  const page = await selected.newPage();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const timeout = setTimeout(() => release(), 15000);
  const script = config.origin + '/_lsf/assets/' + config.frontend.publication + config.frontend.client.path;
  await page.route(script, async route => { await gate; await route.continue(); });
  try {
    const response = await page.goto(config.origin + '/drafts/' + subject, {waitUntil: 'commit', timeout: 15000});
    assert.equal(response.status(), 200);
    await page.locator('#draft-revision').waitFor({state: 'visible', timeout: 15000});
    const html = await response.body();
    assert.ok(html.length <= 131072 && html.includes(Buffer.from('ngh=')));
    assert.ok(forbidden.every(value => !html.includes(Buffer.from(value))));
    assert.ok(!/public|immutable/.test(response.headers()['cache-control'] ?? ''));
    assert.ok(/no-store/.test(response.headers()['cache-control'] ?? ''));
    assert.equal(response.headers()['set-cookie'], undefined);
    await page.evaluate(() => { globalThis.orderDraftBeforeHydration = document.querySelector('#draft-revision'); });
    const original = await revision(page);
    const assetResponse = page.waitForResponse(script, {timeout: 15000});
    release();
    await page.waitForFunction(() => document.documentElement.dataset.orderDraftHydrated === 'true', undefined, {timeout: 15000});
    assert.equal(await page.evaluate(() => globalThis.orderDraftBeforeHydration === document.querySelector('#draft-revision')), true);
    const actualAsset = await assetResponse;
    assert.equal(actualAsset.status(), 200);
    const actualBytes = await actualAsset.body();
    assert.equal(actualBytes.length, config.frontend.client.bytes);
    assert.equal(digest(actualBytes), config.frontend.client.digest);
    assert.ok(forbidden.every(value => !actualBytes.includes(Buffer.from(value))));
    assets.push(digest(actualBytes));
    return {page, original, ssrDigest: digest(html)};
  } finally { clearTimeout(timeout); release(); await page.unroute(script); }
}
async function revision(page) {
  const text = await page.locator('#draft-revision').textContent();
  assert.match(text, /^Revision (0|[1-9][0-9]{0,19})$/);
  const value = BigInt(text.slice(9));
  assert.ok(value < (1n << 64n));
  return value;
}
async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('#query-draft').disabled, undefined, {timeout: 15000});
}
async function status(page, expected) {
  await page.waitForFunction(value => document.querySelector('#command-status').textContent === value, expected, {timeout: 15000});
  await idle(page);
}
async function submit(page, units) {
  await page.locator('#units').fill(String(units));
  await page.locator('#submit-draft').click();
}
async function responseLoss(page, expectedDisposition) {
  const route = config.origin + '/drafts/alice/edit';
  const observed = {};
  let calls = 0;
  await page.route(route, async intercepted => {
    assert.equal(++calls, 1);
    const request = intercepted.request();
    observed.key = request.headers()['idempotency-key'];
    observed.bodyDigest = digest(request.postDataBuffer());
    // Obtain the actual node's terminal reply, then deliberately lose delivery.
    // No substitute response is produced and the browser receives an error.
    const headers = await request.allHeaders();
    headers.host = new URL(config.origin).host;
    // Playwright's API transport does not use Chromium's host-resolver rules.
    // Reach the same listener directly while retaining the original signed
    // Host, Origin, credentials, method, body and original command headers.
    const actual = await intercepted.fetch({url: 'http://127.0.0.1:19092/drafts/alice/edit',
      headers, maxRetries: 0, maxRedirects: 0, timeout: 15000});
    assert.equal(actual.status(), expectedDisposition === 'committed' ? 200 : 422);
    const body = await actual.body(); assert.ok(body.length <= 192 * 1024);
    assert.ok(forbidden.every(value => !body.includes(Buffer.from(value))));
    const envelope = JSON.parse(body);
    assert.equal(envelope.profile, 'transaction-http-v1');
    assert.equal(envelope.disposition, expectedDisposition);
    assert.match(envelope['command-id'], /^[0-9a-f]{64}$/);
    observed.commandId = envelope['command-id'];
    observed.effectIds = envelope['effect-ids'];
    observed.result = envelope.result;
    assert.equal(actual.headers()['set-cookie'], undefined);
    await intercepted.abort('failed');
  });
  return {observed, close: async () => { assert.equal(calls, 1); await page.unroute(route); }};
}
async function recover(page, observed, expectedDisposition) {
  const url = config.origin + '/drafts/alice/result';
  const arrived = page.waitForResponse(url, {timeout: 15000});
  await page.locator('#recover-draft').click();
  const response = await arrived;
  assert.equal(response.request().method(), 'GET');
  assert.equal(response.request().headers()['idempotency-key'], observed.key);
  assert.equal(response.headers()['set-cookie'], undefined);
  const value = await response.json();
  assert.equal(value.disposition, expectedDisposition);
  assert.equal(value['command-id'], observed.commandId);
  assert.deepEqual(value['effect-ids'], observed.effectIds);
  assert.deepEqual(value.result, observed.result);
  await status(page, expectedDisposition);
  return value;
}

try {
  for (const backend of config.backends) {
    await nextBackend(backend.language);
    const first = await context(alice), second = await context(alice);
    const a = await hydrate(first, 'alice'), b = await hydrate(second, 'alice');
    assert.equal(a.original, b.original);
    let commandPosts = 0;
    for (const selected of [first, second]) selected.on('request', request => {
      if (new URL(request.url()).pathname === '/drafts/alice/edit' && request.method() === 'POST') commandPosts++;
    });
    await submit(a.page, 3); await status(a.page, 'committed');
    assert.equal(await revision(a.page), a.original + 1n);
    assert.equal(await a.page.locator('#draft-units').textContent(), 'Units 3');
    assert.equal(await a.page.locator('#effect-status').textContent(), '2 original effects');

    const lostRejection = await responseLoss(b.page, 'rejected');
    await submit(b.page, 4); await status(b.page, 'uncertain'); await lostRejection.close();
    await a.page.locator('#finish-original-draft').click();
    await submit(a.page, 5); await status(a.page, 'committed');
    assert.equal(await revision(a.page), a.original + 2n);
    await b.page.locator('#query-draft').click(); await idle(b.page);
    assert.equal(await revision(b.page), a.original + 2n);
    await recover(b.page, lostRejection.observed, 'rejected');
    assert.equal(await b.page.locator('#application-message').textContent(), 'stale-edit');
    assert.equal(await b.page.locator('#retry-aborted-draft').isDisabled(), true);

    await a.page.locator('#finish-original-draft').click();
    const lostCommit = await responseLoss(a.page, 'committed');
    await submit(a.page, 6); await status(a.page, 'uncertain'); await lostCommit.close();
    await first.setExtraHTTPHeaders({Authorization: 'Bearer ' + alice.rotatedToken});
    await recover(a.page, lostCommit.observed, 'committed');
    await a.page.locator('#query-draft').click(); await idle(a.page);
    assert.equal(await revision(a.page), a.original + 3n);
    assert.equal(await a.page.locator('#draft-units').textContent(), 'Units 6');
    assert.equal(commandPosts, 4);

    const bob = await context(config.users.find(user => user.subject === 'bob'));
    const own = await hydrate(bob, 'bob');
    const denied = await bob.request.get('http://127.0.0.1:19092/drafts/alice/result', {
      headers: {host: new URL(config.origin).host, 'idempotency-key': lostCommit.observed.key},
      maxRetries: 0, maxRedirects: 0, timeout: 15000});
    assert.equal(denied.status(), 403);
    const refusal = await denied.body(); assert.ok(refusal.length <= 192 * 1024);
    assert.ok(!refusal.includes(Buffer.from(lostCommit.observed.commandId)));
    assert.equal(denied.headers()['set-cookie'], undefined);
    observations.push({language: backend.language, backendInput: backend, ssrDigest: a.ssrDigest,
      revisions: [a.original.toString(), (a.original + 3n).toString()], commandPosts,
      lostCommit: {commandId: lostCommit.observed.commandId, bodyDigest: lostCommit.observed.bodyDigest},
      lostRejection: {commandId: lostRejection.observed.commandId, bodyDigest: lostRejection.observed.bodyDigest},
      bobSsrDigest: own.ssrDigest, sameTenantForeignResultStatus: denied.status(), tokenRotationSameCommand: true});
    for (const selected of [first, second, bob]) await selected.close();
    emit({event: 'complete', phase: 'backend-browser', language: backend.language,
      originalCommandIds: [lostCommit.observed.commandId, lostRejection.observed.commandId]});
  }
  assert.deepEqual(failures, []);
  assert.ok(assets.every(value => value === config.frontend.client.digest));
  emit({schemaVersion: 'latent.stateful-reference.browser.v1', passed: true, scope: config.scope,
    transport: 'real-node-http', responseLoss: 'actual-terminal-reply-then-abort', requests,
    observedFrontendAssetDigest: config.frontend.client.digest, observations,
    backendSelectionRequiresConductorAttestation: true});
} finally {
  clearTimeout(deadline);
  for (const selected of contexts) await selected.close();
  await browser.close();
}
