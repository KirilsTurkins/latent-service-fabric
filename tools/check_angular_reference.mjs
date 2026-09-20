import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';

const [configurationPath] = process.argv.slice(2);
assert.equal(process.argv.length, 3);
assert.equal(process.version, 'v24.19.0');
const bytes = await readFile(configurationPath);
assert.ok(bytes.length <= 32768);
const configuration = JSON.parse(bytes);
assert.equal(configuration.schemaVersion, 'latent.angular.reference.browser-input.v1');
assert.ok(['public', 'authenticated'].includes(configuration.mode));
assert.match(configuration.origin, /^http:\/\/reference\.test:[0-9]{1,5}$/);
const {chromium} = createRequire(path.join(path.resolve(configuration.toolchain), 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: configuration.chrome, headless: true,
  args: ['--host-resolver-rules=MAP reference.test 127.0.0.1', '--no-proxy-server']});
const errors = [];
const requests = [];
const scripts = [];
const scriptChecks = [];
const results = [];
const responseStatuses = [];
const consoleObservations = [];
const networkFailures = [];
const forbidden = ['lsf-private-angular-reference-v1', 'lsf-private-reference-upstream',
  'LSF-PUBLIC-PROVIDER-WORKFLOW-TEST-ONLY', ...configuration.users.map(user => user.token)];
const lifetime = setTimeout(() => { process.exitCode = 1; void browser.close(); }, 240000);

function emit(value) {
  const output = JSON.stringify(value);
  assert.ok(Buffer.byteLength(output) <= 32768);
  process.stdout.write(output + '\n');
}

function expectClean() {
  assert.deepEqual(errors, []);
  assert.ok(requests.length <= 96);
  assert.ok(requests.every(request => request.origin === configuration.origin && request.method === 'GET'));
  assert.ok(requests.every(request => !/catalog|metadata|server\/renderer|19090|19091/.test(request.path)));
}

async function context(token) {
  const selected = await browser.newContext({extraHTTPHeaders: token ? {Authorization: 'Bearer ' + token} : {},
    serviceWorkers: 'block'});
  selected.on('page', page => {
    page.on('pageerror', error => { if (errors.length < 16) errors.push('browser-page-error:' + createHash('sha256').update(error.message).digest('hex')); });
    page.on('console', message => { if (message.type() === 'error' && consoleObservations.length < 16) consoleObservations.push('browser-console-error:' + createHash('sha256').update(message.text()).digest('hex')); });
    page.on('requestfailed', request => { if (networkFailures.length < 16) networkFailures.push('browser-request-failed:' + (request.failure()?.errorText ?? 'unknown').slice(0,96)); });
    page.on('request', request => {
      const url = new URL(request.url());
      if (requests.length < 97) requests.push({origin: url.origin, path: url.pathname, method: request.method(), type: request.resourceType()});
    });
    page.on('response', response => {
      if (responseStatuses.length < 97) responseStatuses.push({path: new URL(response.url()).pathname, status: response.status()});
      if (!response.url().endsWith('/main.js')) return;
      const checked = (async () => {
        assert.equal(response.status(), 200);
        const content = await response.body();
        assert.ok(content.length > 0 && content.length <= 1024 * 1024);
        assert.ok(forbidden.every(value => !content.includes(Buffer.from(value))));
        const asset = Object.values(configuration.releases).flatMap(release => release.assets
          .map(item => ({...item, url: configuration.origin + '/_lsf/assets/' + release.publication + item.path})))
          .find(item => item.url === response.url());
        assert.ok(asset);
        assert.equal(asset.digest, 'sha256:' + createHash('sha256').update(content).digest('hex'));
        if (scripts.length < 32) scripts.push({url: new URL(response.url()).pathname, digest: asset.digest});
      })().catch(() => { if (errors.length < 16) errors.push('browser-client-identity-or-private-data'); });
      assert.ok(scriptChecks.length < 32);
      scriptChecks.push(checked);
    });
  });
  return selected;
}

async function hydrate(selected, releaseName, route = '/', status = 200, subject = 'visitor', outcome) {
  const release = configuration.releases[releaseName];
  const page = await selected.newPage();
  let continueScript;
  const scriptGate = new Promise(resolve => { continueScript = resolve; });
  const gateTimeout = setTimeout(continueScript, 15000);
  await page.route('**/main.js', async intercepted => { await scriptGate; await intercepted.continue(); });
  try {
    const response = await page.goto(configuration.origin + route, {waitUntil: 'commit', timeout: 15000});
    assert.equal(response.status(), status);
    await page.locator('#greeting').waitFor({state: 'visible', timeout: 15000});
    const body = await response.body();
    assert.ok(body.length <= 131072 && body.includes(Buffer.from('ngh=')));
    assert.ok(forbidden.every(value => !body.includes(Buffer.from(value))));
    assert.ok(body.includes(Buffer.from('/_lsf/assets/' + release.publication + '/client/')));
    assert.equal(await page.locator('#revision').textContent(), release.version);
    assert.equal(await page.locator('#subject').textContent(), subject);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.referenceHydrated), undefined);
    await page.evaluate(() => { globalThis.referenceBefore = {heading: document.getElementById('greeting'), counter: document.getElementById('count')}; });
    continueScript();
    clearTimeout(gateTimeout);
    await page.waitForFunction(() => document.documentElement.dataset.referenceHydrated === 'true', null, {timeout: 15000});
    assert.equal(await page.evaluate(() => referenceBefore.heading === document.getElementById('greeting') &&
      referenceBefore.counter === document.getElementById('count')), true);
    if (outcome) assert.equal(await page.locator('#outcome').textContent(), outcome);
    await page.locator('#count').click();
    await page.waitForFunction(() => document.getElementById('count').textContent === 'Count 1', null, {timeout: 15000});
    results.push({route, status, release: releaseName, serverBeforeJavaScript: true, originalDomReused: true,
      subject, htmlDigest: 'sha256:' + createHash('sha256').update(body).digest('hex'), counter: 1});
    await Promise.all(scriptChecks);
    expectClean();
    return page;
  } finally {
    clearTimeout(gateTimeout);
    continueScript();
  }
}

async function navigate(page) {
  const documents = requests.filter(request => request.type === 'document').length;
  await page.locator('#about-link').click();
  await page.locator('#about-view').waitFor({state: 'visible'});
  assert.equal(new URL(page.url()).pathname, '/about');
  await page.locator('#home-link').click();
  await page.locator('#main-view').waitFor({state: 'visible'});
  assert.equal(new URL(page.url()).pathname, '/');
  assert.equal(await page.locator('#count').textContent(), 'Count 1');
  assert.equal(await page.evaluate(() => referenceBefore.heading === document.getElementById('greeting') &&
    referenceBefore.counter === document.getElementById('count')), true);
  assert.equal(requests.filter(request => request.type === 'document').length, documents);
}

function advance(phase) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { process.off('SIGUSR1', receive); reject(new Error('reference-browser-stage-timeout')); }, 120000);
    const receive = () => { clearTimeout(timeout); resolve(); };
    process.once('SIGUSR1', receive);
    emit({event: 'waiting', phase});
  });
}

try {
  if (configuration.mode === 'public') {
    const selected = await context();
    const original = await hydrate(selected, 'green');
    await navigate(original);
    for (const [route, status, outcome] of [['/about', 200], ['/account', 403, 'denied'],
      ['/failure', 422, 'application-error'], ['/data', 200, 'allowed'], ['/denied', 403, 'permission-denied']]) {
      const page = await hydrate(selected, 'green', route, status, 'visitor', outcome);
      if (route === '/data') assert.equal(await page.locator('#message').textContent(), 'Hello from the scoped provider');
      await page.close();
    }
    const staticPage = await selected.newPage();
    const staticResponse = await staticPage.goto(configuration.origin + '/offline', {waitUntil: 'load', timeout: 15000});
    assert.equal(staticResponse.status(), 200);
    assert.equal(await staticPage.locator('h1').textContent(), 'Static delivery');
    assert.equal(await staticPage.locator('script').count(), 0);
    await staticPage.close();
    await advance('promoted');
    assert.equal(await original.locator('#revision').textContent(), configuration.releases.green.version);
    assert.equal(await original.locator('#count').textContent(), 'Count 1');
    const promoted = await hydrate(selected, 'blue');
    await promoted.close();
    await advance('rolled-back');
    assert.equal(await original.locator('#revision').textContent(), configuration.releases.green.version);
    const restored = await hydrate(selected, 'green');
    await restored.close();
    await original.locator('#count').click();
    await original.waitForFunction(() => document.getElementById('count').textContent === 'Count 2');
    await selected.close();
  } else {
    const anonymous = await context();
    const denied = await anonymous.newPage();
    assert.equal((await denied.goto(configuration.origin + '/account', {waitUntil: 'load'})).status(), 401);
    await anonymous.close();
    for (const user of configuration.users) {
      const selected = await context(user.token);
      const page = await hydrate(selected, 'green', '/account', 200, user.displayName, 'authenticated');
      for (const other of configuration.users.filter(other => other.subject !== user.subject)) {
        assert.ok(!(await page.locator('body').textContent()).includes(other.displayName));
      }
      await selected.close();
    }
  }
  await Promise.all(scriptChecks);
  expectClean();
  emit({event: 'complete', schemaVersion: 'latent.angular.reference.browser.v1', passed: true,
    transport: 'real-http', mode: configuration.mode, node: process.version, browser: browser.version(),
    results, scripts, requests, errors, directNodeCatalogAccess: false, privateClientMaterialAbsent: true});
} catch (error) {
  const diagnosis = {event: 'failed', schemaVersion: 'latent.angular.reference.browser.v1', passed: false, mode: configuration.mode, errors, consoleObservations, networkFailures, responses: responseStatuses, results, scripts};
  const serialized = JSON.stringify(diagnosis);
  if (Buffer.byteLength(serialized) <= 32768) process.stderr.write(serialized + '\n');
  throw error;
} finally {
  clearTimeout(lifetime);
  await browser.close();
}
