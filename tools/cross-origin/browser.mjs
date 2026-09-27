// Real Chromium feasibility experiment. The HTTPS peer implements the proposed
// contract, not LSF ingress; the receipt explicitly excludes native qualification.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {resolve, join} from 'node:path';
import {readFile, writeFile} from 'node:fs/promises';
import https from 'node:https';
import {configuration, decide, vary} from './contract.mjs';

const [toolchain, chrome, tls, font, output, ...extra] = process.argv.slice(2);
assert.ok(output && !extra.length, 'usage: browser.mjs TOOLCHAIN CHROME TLS_DIRECTORY WOFF2 NEW_RECEIPT');
const {chromium} = createRequire(join(resolve(toolchain), 'package.json'))('playwright-core');
const options = {key: await readFile(join(tls, 'key.pem')), cert: await readFile(join(tls, 'server.pem')),
  maxHeaderSize: 8192};
const fontBytes = await readFile(font);
assert.ok(fontBytes.length <= 128 * 1024 && fontBytes.subarray(0, 4).toString() === 'wOF2');
const observations = [], sockets = new Set(), servers = [], cases = [];
const ids = Object.fromEntries(['a', 'b', 'public'].map((name, i) => [name, 'publication:sha256:' + String(i + 1).repeat(64)]));
let rows = [], assets, browser, currentCase = 'startup', transport = 'chromium', expired = false;
const report = {schemaVersion: 'latent.cross-origin.feasibility.v1', passed: false,
  nativeRuntimeQualified: false, productionTlsQualified: false, cases, observations};

async function listen(handler) {
  const server = https.createServer(options, handler);
  server.maxConnections = 16;
  server.maxHeadersCount = 32;
  server.headersTimeout = 2000;
  server.requestTimeout = 3000;
  server.keepAliveTimeout = 1000;
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  servers.push(server);
  await new Promise((accept, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', accept); });
  return server.address().port;
}

const assetPort = await listen((req, res) => {
  req.resume();
  if (observations.length >= 128) return req.destroy();
  const [_, publication, file] = req.url.split('/');
  const input = {authority: req.headers.host, tenant: 'example', publication: ids[publication],
    method: req.method, headers: req.headers, eligible: file !== 'retired.js'};
  const decision = decide(rows, input);
  const headers = {...decision.headers};
  let status = decision.status, body = Buffer.alloc(0);
  if (status === 200) {
    const found = {
      'main.js': ['text/javascript', Buffer.from('globalThis.lsfExternalLoaded = true;')],
      'theme.css': ['text/css', Buffer.from('#sample {color: rgb(20, 50, 80)}')],
      'icons.woff2': ['font/woff2', fontBytes],
    }[file];
    if (!found) { status = 404; headers['cache-control'] = 'no-store'; }
    else {
      headers['content-type'] = found[0];
      headers.etag = '"feasibility-asset-v1"';
      headers['content-length'] = String(found[1].length);
      if (req.headers['if-none-match'] === headers.etag) status = 304;
      else if (req.method !== 'HEAD') body = found[1];
    }
  }
  observations.push({case: currentCase, transport, method: req.method, publication, file, status,
    origin: req.headers.origin ?? null, site: req.headers['sec-fetch-site'] ?? null,
    mode: req.headers['sec-fetch-mode'] ?? null, destination: req.headers['sec-fetch-dest'] ?? null,
    cookiePresent: Boolean(req.headers.cookie), headers});
  res.writeHead(status, headers);
  res.end(body);
});
assets = `https://assets.lsf.localhost:${assetPort}`;
const pagePort = await listen((req, res) => {
  req.resume();
  res.writeHead(200, {'content-type': 'text/html', 'cache-control': 'no-store',
    'content-security-policy': `default-src 'none'; script-src 'self' ${assets}; style-src 'self' ${assets}; font-src ${assets}; connect-src ${assets}; frame-src 'self'; base-uri 'none'`});
  res.end('<!doctype html><title>External asset feasibility</title><div id="sample">Example</div>');
});
const approved = `https://portal.lsf.localhost:${pagePort}`;
const crossSite = `https://127.0.0.1:${pagePort}`;
const unrelated = `https://unrelated.lsf.localhost:${pagePort}`;
rows = configuration(['a', 'public'].map(publication => ({authority: new URL(assets).host,
  tenant: 'example', publication: ids[publication], origins: [approved, crossSite],
  credentials: publication === 'a' ? 'include' : 'omit'})));
const watchdog = setTimeout(() => {
  expired = true;
  for (const socket of sockets) socket.destroy();
  void browser?.close();
}, 90000);
watchdog.unref();

async function fetchResult(page, path, init = {}) {
  return page.evaluate(async ({url, init}) => {
    try {
      const response = await fetch(url, {...init, signal: AbortSignal.timeout(5000)});
      return {status: response.status, text: await response.text(), etag: response.headers.get('etag')};
    } catch (error) { return {error: error.name}; }
  }, {url: assets + path, init});
}
async function check(name, action) {
  currentCase = name;
  await action();
  cases.push(name);
}

try {
  browser = await chromium.launch({executablePath: resolve(chrome), headless: true,
    args: ['--host-resolver-rules=MAP *.lsf.localhost 127.0.0.1',
      ...(process.platform === 'linux' && process.getuid() === 0 ? ['--no-sandbox'] : [])]});
  report.browser = browser.version();
  // Only these disposable loopback peers use an untrusted ephemeral certificate.
  const context = await browser.newContext({ignoreHTTPSErrors: true});
  await context.addCookies([{name: '__Host-lsf_demo', value: 'test-only', url: assets,
    secure: true, httpOnly: true, sameSite: 'Strict'}]);
  const page = await context.newPage();
  await page.goto(approved);
  await check('approved-cross-origin-script-style-and-font', async () => {
    await page.evaluate(async base => {
      await new Promise((ok, fail) => {
        const script = document.createElement('script');
        script.crossOrigin = 'anonymous'; script.src = base + '/a/main.js';
        script.onload = ok; script.onerror = fail; document.head.append(script);
      });
      await new Promise((ok, fail) => {
        const style = document.createElement('link'); style.rel = 'stylesheet';
        style.crossOrigin = 'anonymous'; style.href = base + '/a/theme.css';
        style.onload = ok; style.onerror = fail; document.head.append(style);
      });
      const face = new FontFace('LSFFeasibility', `url(${base}/a/icons.woff2)`);
      await face.load(); document.fonts.add(face);
    }, assets);
    assert.equal(await page.evaluate(() => globalThis.lsfExternalLoaded), true);
    assert.equal(await page.locator('#sample').evaluate(element => getComputedStyle(element).color), 'rgb(20, 50, 80)');
    assert.ok(observations.some(row => row.destination === 'font' && row.status === 200));
  });
  await check('approved-cross-site-read-without-credentials', async () => {
    await page.goto(crossSite);
    assert.equal((await fetchResult(page, '/a/main.js', {credentials: 'omit'})).status, 200);
    assert.equal(observations.at(-1).site, 'cross-site');
  });
  await check('same-site-credentials-include-and-omit', async () => {
    await page.goto(approved);
    assert.equal((await fetchResult(page, '/a/main.js', {credentials: 'include', cache: 'no-store'})).status, 200);
    assert.equal(observations.at(-1).cookiePresent, true);
    assert.equal((await fetchResult(page, '/a/main.js', {credentials: 'omit', cache: 'no-store'})).status, 200);
    assert.equal(observations.at(-1).cookiePresent, false);
  });
  await check('cors-does-not-override-strict-samesite-cookie', async () => {
    await page.goto(crossSite);
    assert.equal((await fetchResult(page, '/a/main.js', {credentials: 'include', cache: 'no-store'})).status, 200);
    assert.equal(observations.at(-1).cookiePresent, false);
  });
  await check('anonymous-only-grant-rejects-credential-mode', async () => {
    assert.equal((await fetchResult(page, '/public/main.js', {credentials: 'omit'})).status, 200);
    assert.equal((await fetchResult(page, '/public/main.js', {credentials: 'include'})).error, 'TypeError');
  });
  await check('unrelated-origin-and-ungranted-publication', async () => {
    await page.goto(approved);
    assert.equal((await fetchResult(page, '/b/main.js', {credentials: 'omit'})).error, 'TypeError');
    await page.goto(unrelated);
    assert.equal((await fetchResult(page, '/a/main.js', {credentials: 'omit'})).error, 'TypeError');
    assert.equal(observations.at(-1).status, 403);
  });
  await check('conditional-preflight-head-304-and-errors', async () => {
    await page.goto(approved);
    assert.equal((await fetchResult(page, '/a/main.js', {method: 'HEAD', credentials: 'omit'})).text, '');
    const result = await fetchResult(page, '/a/main.js', {credentials: 'omit', cache: 'no-store',
      headers: {'If-None-Match': '"feasibility-asset-v1"'}});
    assert.equal(result.status, 304);
    assert.equal(result.text, '');
    assert.ok(observations.some(row => row.case === currentCase && row.method === 'OPTIONS' && row.status === 204));
    assert.equal((await fetchResult(page, '/a/missing.js', {credentials: 'omit'})).status, 404);
    assert.equal((await fetchResult(page, '/a/retired.js', {credentials: 'omit'})).error, 'TypeError');
  });
  await check('unsafe-and-authorization-preflights-cannot-dispatch', async () => {
    for (const init of [{method: 'PUT'}, {headers: {Authorization: 'Bearer test-only'}}, {headers: {'X-Tenant': 'other'}}]) {
      assert.equal((await fetchResult(page, '/a/main.js', {...init, credentials: 'omit'})).error, 'TypeError');
    }
    const requests = observations.filter(row => row.case === currentCase);
    assert.equal(requests.length, 3);
    assert.ok(requests.every(row => row.method === 'OPTIONS' && row.status === 403 && !row.cookiePresent));
  });
  await check('opaque-null-origin-and-no-cors-are-denied', async () => {
    await page.evaluate(() => {
      const frame = document.createElement('iframe'); frame.sandbox = 'allow-scripts';
      frame.srcdoc = '<!doctype html><title>Opaque origin</title>'; document.body.append(frame);
    });
    const frame = page.frames().find(value => value !== page.mainFrame());
    assert.ok(frame);
    assert.equal((await fetchResult(frame, '/a/main.js', {credentials: 'omit'})).error, 'TypeError');
    assert.equal(observations.at(-1).origin, 'null');
    await fetchResult(page, '/a/main.js', {mode: 'no-cors', credentials: 'omit'});
    assert.equal(observations.at(-1).status, 403);
  });
  await check('browser-origin-is-fixed-and-malformed-wire-origin-is-denied', async () => {
    // Fetch discards a script's forbidden Origin header. Malformed wire input
    // therefore needs a separate HTTPS client, explicitly labelled in evidence.
    const malformed = approved + ', https://other.example';
    const result = await fetchResult(page, '/a/main.js', {credentials: 'omit', cache: 'no-store', headers: {Origin: malformed}});
    assert.equal(result.status, 200);
    assert.equal(observations.at(-1).origin, approved);
    transport = 'explicit-https-wire-client';
    try {
      const wire = await new Promise((accept, reject) => {
        const request = https.request({hostname: '127.0.0.1', port: assetPort, path: '/a/main.js',
          method: 'GET', rejectUnauthorized: false, agent: false, headers: {
            Host: new URL(assets).host, Origin: malformed, 'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Dest': 'empty',
          }}, response => {
          response.resume();
          response.on('end', () => accept({status: response.statusCode, headers: response.headers}));
          response.on('error', reject);
        });
        request.setTimeout(5000, () => request.destroy(new Error('wire fixture deadline')));
        request.on('error', reject); request.end();
      });
      assert.equal(wire.status, 403);
      assert.equal(wire.headers['access-control-allow-origin'], undefined);
      assert.equal(observations.at(-1).origin, malformed);
      assert.equal(observations.at(-1).status, 403);
    } finally { transport = 'chromium'; }
  });
  await check('every-variant-has-exact-cors-and-cache-boundaries', async () => {
    for (const row of observations) {
      assert.equal(row.headers.vary, vary);
      assert.equal(row.headers['x-content-type-options'], 'nosniff');
      if (row.status === 403) {
        assert.equal(row.headers['access-control-allow-origin'], undefined);
        assert.equal(row.headers['cache-control'], 'no-store');
      } else {
        assert.equal(row.headers['access-control-allow-origin'], row.origin);
        assert.equal(row.headers['cross-origin-resource-policy'], 'cross-origin');
        assert.ok(['private, no-cache', 'no-store'].includes(row.headers['cache-control']));
      }
    }
  });
  assert.equal(expired, false);
  report.passed = true;
} catch (error) {
  report.failure = {case: currentCase, name: error.name, message: String(error.message).slice(0, 1500)};
  process.exitCode = 1;
} finally {
  clearTimeout(watchdog);
  await browser?.close();
  for (const socket of sockets) socket.destroy();
  await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))));
  report.cleanup = 'browser-and-loopback-listeners-closed';
  await writeFile(output, JSON.stringify(report, null, 2) + '\n', {flag: 'wx', mode: 0o600});
  console.log(JSON.stringify({passed: report.passed, cases: cases.length, failure: report.failure,
    nativeRuntimeQualified: false, cleanup: report.cleanup}));
}
