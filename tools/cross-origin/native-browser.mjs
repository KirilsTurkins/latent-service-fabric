// Real Chromium talks directly to native TLS ingress. The sole Node HTTPS
// listener serves only the external caller document, never assets or CORS.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile, writeFile, link, unlink} from 'node:fs/promises';
import path from 'node:path';
import https from 'node:https';
import {setTimeout as delay} from 'node:timers/promises';
import {recordNetwork, policyHeaders} from './native-network.mjs';

const [toolchain, chrome, work, ...extra] = process.argv.slice(2);
assert.ok(work && !extra.length, 'native-browser.mjs TOOLCHAIN CHROME WORK');
const input = JSON.parse(await readFile(path.join(work, 'browser-input.json'), 'utf8'));
const {assets, foreign, publications} = input;
assert.match(assets, /^https:\/\/assets\.lsf\.localhost:[0-9]+$/);
assert.match(foreign, /^https:\/\/foreign\.lsf\.localhost:[0-9]+$/);
const {chromium} = createRequire(path.join(path.resolve(toolchain), 'package.json'))('playwright-core');
const tls = {key: await readFile(path.join(work, 'tls/key.pem')), cert: await readFile(path.join(work, 'tls/server.pem'))};
const deadline = Date.now() + 300000, sockets = new Set(), observations = [], wireObservations = [], cases = [];
let browser, network, failure, stage = 'startup', currentCase = 'startup', etag;
const report = {schemaVersion: 'latent.cross-origin.native-browser.v1', passed: false,
  nativeRuntimeQualified: false, productionTlsQualified: false, testIdentityOnly: true, cases, observations, wireObservations};
const peer = https.createServer({...tls, maxHeaderSize: 8192}, (req, res) => {
  req.resume();
  res.writeHead(200, {'content-type': 'text/html', 'cache-control': 'no-store',
    'content-security-policy': `${req.url === '/opaque' ? 'sandbox allow-scripts; ' : ''}default-src 'none'; script-src 'self' ${assets}; style-src 'self' ${assets}; font-src ${assets}; connect-src ${assets} ${foreign}; frame-src 'self'; base-uri 'none'`});
  res.end('<!doctype html><title>Native asset caller</title><div id="sample">Example</div>');
});
peer.maxConnections = 16; peer.maxHeadersCount = 32;
peer.headersTimeout = 2000; peer.requestTimeout = 3000; peer.keepAliveTimeout = 1000;
peer.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
const watchdog = setTimeout(() => {
  failure ??= new Error('native-browser-deadline');
  for (const socket of sockets) socket.destroy();
  void browser?.close();
}, 300000);
watchdog.unref();
async function save(name, value) {
  const target = path.join(work, name), temporary = target + '.pending';
  const bytes = JSON.stringify(value) + '\n';
  assert.ok(Buffer.byteLength(bytes) <= 512 * 1024, 'receipt-byte-bound');
  await writeFile(temporary, bytes, {flag: 'wx', mode: 0o600});
  // Publish complete messages atomically without replacing any earlier result.
  try { await link(temporary, target); } finally { await unlink(temporary); }
}
async function wait(name) {
  while (Date.now() < deadline) {
    if (failure) throw failure;
    try { return JSON.parse(await readFile(path.join(work, name), 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await delay(20);
  }
  throw new Error('native-browser-command-deadline');
}
async function flush() { await network.flush(); if (failure) throw failure; }
const locator = name => '/_lsf/assets/' + publications[name] + '/app.js';
async function fetchResult(page, target = '/app.js', init = {}) {
  return page.evaluate(async ({url, init}) => {
    try {
      const response = await fetch(url, {...init, signal: AbortSignal.timeout(5000)});
      return {status: response.status, text: await response.text(), etag: response.headers.get('etag')};
    } catch (error) { return {error: error.name}; }
  }, {url: target.startsWith('https://') ? target : assets + target, init});
}
async function wire(method, target, headers = {}) {
  assert.ok(wireObservations.length < 64, 'wire-observation-bound');
  const row = {transport: 'explicit-https-wire-client', stage, case: currentCase,
    method, path: target, origin: headers.Origin ?? null,
    cookiePresent: Boolean(headers.Cookie)};
  wireObservations.push(row);
  return new Promise((resolve, reject) => {
    const request = https.request({hostname: '127.0.0.1', port: new URL(assets).port, servername: 'localhost',
      ca: tls.cert, method, path: target, agent: false, maxHeaderSize: 8192,
      headers: {Host: new URL(assets).host, Connection: 'close', ...headers}}, response => {
      let bytes = 0;
      response.on('data', chunk => { bytes += chunk.length; if (bytes > 131072) response.destroy(new Error('wire-body-bound')); });
      response.on('end', () => {
        Object.assign(row, {status: response.statusCode, headers: policyHeaders(response.headers), bytes});
        resolve({status: response.statusCode, headers: response.headers, bytes});
      });
      response.on('error', reject);
    });
    request.setTimeout(5000, () => request.destroy(new Error('wire-deadline')));
    request.on('error', reject); request.end();
  });
}
function denied(response) {
  assert.ok([400, 401, 403].includes(response.status), JSON.stringify(response));
  assert.equal(response.headers['access-control-allow-origin'], undefined);
  assert.equal(response.headers['cache-control'], 'no-store');
  assert.equal(response.headers['cross-origin-resource-policy'], 'same-origin');
  assert.equal(response.bytes, 0);
}

try {
  await new Promise((resolve, reject) => { peer.once('error', reject); peer.listen(0, '127.0.0.1', resolve); });
  const port = peer.address().port, approved = `https://portal.lsf.localhost:${port}`;
  const crossSite = `https://127.0.0.1:${port}`, unrelated = `https://unrelated.lsf.localhost:${port}`;
  browser = await chromium.launch({executablePath: path.resolve(chrome), headless: true,
    args: ['--host-resolver-rules=MAP *.lsf.localhost 127.0.0.1']});
  // Only this disposable context bypasses trust for the generated loopback
  // certificate. Wire clients verify it; no system trust store is modified.
  const context = await browser.newContext({ignoreHTTPSErrors: true});
  await context.addCookies([{name: '__Host-lsf_demo', value: 'test-only', url: assets,
    secure: true, httpOnly: true, sameSite: 'Strict'}]);
  const page = await context.newPage();
  network = await recordNetwork(await context.newCDPSession(page), {
    origins: [assets, foreign], observations, scope: () => ({stage, case: currentCase}),
    fail: error => { failure ??= error; },
  });
  await page.goto(approved, {timeout: 10000});
  await save('browser-ready.json', {approved, crossSite, unrelated});
  const common = {Origin: approved, 'Sec-Fetch-Site': 'same-site', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'};
  const conditional = {'If-None-Match': '*'};
  async function check(name, action) { currentCase = name; await action(); await flush(); cases.push({stage, name}); }
  async function unavailable() {
    for (const init of [{}, {method: 'HEAD'}, {headers: conditional}]) {
      assert.equal((await fetchResult(page, '/app.js', {...init, credentials: 'omit'})).error, 'TypeError');
    }
    denied(await wire('OPTIONS', '/app.js', {...common, 'Access-Control-Request-Method': 'GET',
      'Access-Control-Request-Headers': 'if-none-match'}));
  }
  const stages = ['default', 'allowed', 'removed', 'restored', 'new-ungranted', 'new-opted-in',
    'expiring', 'expired', 'renewed', 'revoked', 'restart-revoked'];
  for (const [index, name] of stages.entries()) {
    const command = await wait(index + '-request.json');
    assert.deepEqual(command, {stage: name}); stage = name;
    if (['default', 'removed', 'new-ungranted', 'expired', 'revoked', 'restart-revoked'].includes(stage)) {
      await check('cached-body-head-conditional-and-preflight-denied', unavailable);
      if (stage === 'new-ungranted') {
        assert.equal((await fetchResult(page, locator('a'), {credentials: 'omit'})).status, 200);
        assert.equal((await fetchResult(page, locator('b'), {credentials: 'omit'})).error, 'TypeError');
      }
    } else {
      await check('current-exact-publication-readable', async () => {
        const result = await fetchResult(page, '/app.js', {credentials: 'omit'});
        assert.equal(result.status, 200); assert.match(result.text, /lsfCrossOriginLoads/);
        if (etag) assert.equal(result.etag, etag); else etag = result.etag;
        assert.match(etag, /^"identity-sha256-[a-f0-9]{64}"$/);
        const head = await fetchResult(page, '/app.js', {method: 'HEAD', credentials: 'omit'});
        assert.equal(head.status, 200); assert.equal(head.text, ''); assert.equal(head.etag, etag);
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'omit', cache: 'no-store',
          headers: {'If-None-Match': etag}})).status, 304);
      });
    }
    if (stage === 'new-opted-in') {
      await check('old-grant-is-not-inherited-by-identical-content', async () => {
        assert.equal((await fetchResult(page, locator('a'), {credentials: 'omit'})).error, 'TypeError');
        assert.equal((await fetchResult(page, locator('b'), {credentials: 'omit'})).status, 200);
      });
    }
    if (stage === 'allowed') {
      await check('signed-native-script-style-woff2', async () => {
        await page.evaluate(async base => {
          for (const kind of ['script', 'style']) await new Promise((resolve, reject) => {
            const element = document.createElement(kind === 'script' ? 'script' : 'link');
            element.crossOrigin = 'anonymous';
            if (kind === 'script') element.src = base + '/app.js';
            else { element.rel = 'stylesheet'; element.href = base + '/style.css'; }
            element.onload = resolve; element.onerror = reject; document.head.append(element);
          });
          const face = new FontFace('LSFNativeCors', `url(${base}/font.woff2)`);
          await face.load(); document.fonts.add(face);
        }, assets);
        assert.equal(await page.evaluate(() => globalThis.lsfCrossOriginLoads), 1);
        assert.equal(await page.locator('#sample').evaluate(element => getComputedStyle(element).color), 'rgb(20, 50, 80)');
        await flush();
        assert.ok(observations.some(row => row.path === '/font.woff2' && row.status === 200));
      });
      await check('same-site-credentials-and-anonymous-only', async () => {
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'include', cache: 'no-store'})).status, 200);
        assert.equal((await fetchResult(page, locator('anonymous'), {credentials: 'omit'})).status, 200);
        assert.equal((await fetchResult(page, locator('anonymous'), {credentials: 'include'})).error, 'TypeError');
        await flush();
        assert.ok(observations.some(row => row.path === '/app.js' && row.site === 'same-site' && row.cookiePresent));
      });
      await check('cross-site-does-not-relax-samesite', async () => {
        await page.goto(crossSite);
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'include', cache: 'no-store'})).status, 200);
        assert.equal((await fetchResult(page, locator('anonymous'), {credentials: 'include'})).error, 'TypeError');
        await flush();
        const rows = observations.filter(row => row.origin === crossSite && row.path === '/app.js');
        assert.ok(rows.length > 0 && rows.every(row => row.site === 'cross-site' && !row.cookiePresent));
        await page.goto(approved);
      });
      await check('unrelated-origins-publications-and-tenants', async () => {
        for (const target of [locator('b'), locator('foreign'), foreign + locator('a'), foreign + locator('foreign')]) {
          assert.equal((await fetchResult(page, target, {credentials: 'omit'})).error, 'TypeError');
        }
        await page.goto(unrelated);
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'omit'})).error, 'TypeError');
        await page.goto(approved);
      });
      await check('head-errors-and-bounded-conditional-preflight', async () => {
        for (const method of ['GET', 'HEAD']) {
          const missing = await fetchResult(page, '/missing.js', {method, credentials: 'omit'});
          assert.equal(missing.status, 404); assert.equal(missing.text, '');
        }
        const preflight = await wire('OPTIONS', '/app.js', {...common, 'Access-Control-Request-Method': 'HEAD',
          'Access-Control-Request-Headers': 'if-modified-since, if-none-match'});
        assert.equal(preflight.status, 204); assert.equal(preflight.headers['access-control-max-age'], '0');
        assert.equal(preflight.headers['access-control-allow-origin'], approved);
        assert.equal(preflight.headers['access-control-allow-methods'], 'GET, HEAD');
        assert.equal(preflight.bytes, 0);
        for (const init of [{method: 'PUT'}, {headers: {Authorization: 'Bearer test-only'}}, {headers: {'X-Tenant': 'foreign'}}]) {
          assert.equal((await fetchResult(page, '/app.js', {...init, credentials: 'omit'})).error, 'TypeError');
        }
      });
      await check('null-origin-no-cors-and-documents-denied', async () => {
        // A sandboxed top-level response has an opaque origin, while staying
        // in the observed CDP target. No supplied/fabricated Origin is used.
        await page.goto(approved + '/opaque');
        const previous = observations.length;
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'omit'})).error, 'TypeError');
        await network.waitFor(row => observations.indexOf(row) >= previous && row.origin === 'null'
          && row.status === 403 && row.requestHeadersObserved && row.responseHeadersObserved,
        'actual-browser-null-origin-and-native-denial-required');
        await page.goto(approved);
        await fetchResult(page, '/app.js', {mode: 'no-cors', credentials: 'omit'});
        assert.equal((await fetchResult(page, '/index.html', {credentials: 'omit'})).error, 'TypeError');
        denied(await wire('GET', '/app.js', {...common, 'Sec-Fetch-Mode': 'no-cors'}));
        denied(await wire('GET', '/app.js', {...common, 'Sec-Fetch-Dest': 'document'}));
      });
      await check('browser-generated-origin-distinct-from-malformed-wire-input', async () => {
        const malformed = approved + ', https://other.example';
        assert.equal((await fetchResult(page, '/app.js', {credentials: 'omit', cache: 'no-store', headers: {Origin: malformed}})).status, 200);
        await flush(); assert.equal(observations.at(-1).origin, approved);
        denied(await wire('GET', '/app.js', {...common, Origin: malformed}));
        denied(await wire('GET', '/app.js', {...common, Origin: [approved, approved]}));
        denied(await wire('OPTIONS', '/app.js', {...common, 'Access-Control-Request-Method': 'GET',
          'Access-Control-Request-Headers': 'authorization'}));
        denied(await wire('OPTIONS', '/app.js', {...common, 'Access-Control-Request-Method': 'GET', Cookie: '__Host-lsf_demo=test-only'}));
      });
    }
    await flush();
    await save(index + '-result.json', {stage, passed: true, cases: cases.filter(row => row.stage === stage)});
  }
  for (const row of observations.filter(row => row.headers)) {
    assert.equal(row.requestHeadersObserved, true, 'response-needs-observed-wire-request');
    const fields = row.headers;
    assert.equal(fields['x-content-type-options'], 'nosniff');
    const vary = new Set(fields.vary?.toLowerCase().split(',').map(name => name.trim()));
    for (const name of ['origin', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest',
      'access-control-request-method', 'access-control-request-headers']) assert.ok(vary.has(name));
    if (fields['access-control-allow-origin']) {
      assert.equal(fields['access-control-allow-origin'], row.origin);
      assert.equal(fields['cross-origin-resource-policy'], 'cross-origin');
      assert.equal(fields['access-control-expose-headers'], 'ETag');
      assert.equal(fields['cache-control'], row.status >= 400 ? 'no-store' : 'private, no-cache');
    } else {
      assert.equal(fields['cross-origin-resource-policy'], 'same-origin');
      assert.equal(fields['cache-control'], 'no-store');
    }
  }
  report.browser = browser.version(); report.passed = true; report.nativeRuntimeQualified = true;
} catch (error) {
  report.failure = {stage, name: error.name, message: String(error.message).slice(0, 1500)};
  process.exitCode = 1;
} finally {
  clearTimeout(watchdog);
  await browser?.close();
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve => peer.close(resolve));
  report.cleanup = 'browser-and-caller-listener-closed';
  await save('browser-result.json', report);
  console.log(JSON.stringify({passed: report.passed, cases: cases.length, failure: report.failure, cleanup: report.cleanup}));
}
