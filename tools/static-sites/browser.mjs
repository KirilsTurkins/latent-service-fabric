import {createRequire} from 'node:module';
import path from 'node:path';
import {readFile, writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';

const [toolchain, chrome, origin, generator, version, receipt, mode = 'navigation', ready, resume] = process.argv.slice(2);
assert.ok(['navigation', 'cutover'].includes(mode));
const {chromium} = createRequire(path.join(toolchain, 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: chrome, headless: true,
  args: process.platform === 'linux' && process.getuid() === 0 ? ['--no-sandbox'] : []});
const watchdog = setTimeout(() => { process.exitCode = 1; browser.close(); }, 90000);
const result = {schemaVersion: 'latent.static.browser.v1', browser: browser.version(), mode};
const responses = [];

async function view(page, text, build) {
  await page.waitForFunction(({text, build}) => document.querySelector('#view')?.textContent === text &&
    document.querySelector('#version')?.textContent === build, {text, build}, {timeout: 15000});
  assert.equal(await page.locator('body').evaluate(element => getComputedStyle(element).color), 'rgb(20, 50, 80)');
}

function headers(response) {
  const fields = response.headers();
  assert.match(fields['content-security-policy'], /script-src 'self'/);
  assert.match(fields['content-security-policy'], /base-uri 'none'/);
  assert.equal(fields['x-content-type-options'], 'nosniff');
  assert.equal(fields['cross-origin-resource-policy'], 'same-origin');
  assert.equal(fields['cache-control'], 'private, no-cache');
  assert.ok(fields.vary.includes('Accept') || fields.vary.includes('accept'));
  assert.equal(fields['access-control-allow-origin'], undefined);
}

try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  const scripts = new Set();
  page.on('pageerror', error => { if (errors.length < 8) errors.push(error.name); });
  page.on('response', response => {
    if (responses.length < 32) responses.push({status: response.status(), type: response.request().resourceType()});
    if (response.request().resourceType() === 'script' && response.status() === 200) scripts.add(response.url());
  });
  if (mode === 'cutover') {
    let held = false;
    await page.route('**/assets/main-*.js', async route => {
      if (held) return route.continue();
      held = true;
      await writeFile(ready, JSON.stringify({stage: 'A-document-selected', script: new URL(route.request().url()).pathname}));
      const deadline = Date.now() + 30000;
      while (true) {
        try { assert.equal(JSON.parse(await readFile(resume, 'utf8')).stage, 'B-trigger-committed'); break; }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        assert.ok(Date.now() < deadline, 'bounded cutover handoff');
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      await route.continue();
    });
    headers(await page.goto(origin + '/orders/42', {waitUntil: 'networkidle', timeout: 45000}));
    await view(page, 'Order 42', 'A');
    await page.locator('#order73').click();
    await view(page, 'Order 73', 'A');
    const fresh = await context.newPage();
    headers(await fresh.goto(origin + '/orders/42', {waitUntil: 'networkidle', timeout: 15000}));
    await view(fresh, 'Order 42', 'B');
    result.selectedADocumentCompletedAfterB = true;
    result.freshNavigationSelectedB = true;
    result.retainedContentHashedAssetsServedByB = true;
  } else {
    result.stage = 'csr-navigation';
    let documents = 0;
    page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++; });
    const response = await page.goto(origin + '/orders/42', {waitUntil: 'networkidle', timeout: 15000});
    assert.equal(response.status(), 200);
    headers(response);
    await view(page, 'Order 42', version);
    const before = documents;
    await page.locator('#order73').click();
    await view(page, 'Order 73', version);
    assert.equal(documents, before);
    await page.reload({waitUntil: 'networkidle', timeout: 15000});
    await view(page, 'Order 73', version);
    await page.locator('#home').click();
    await view(page, 'Orders home', version);
    assert.ok(scripts.size >= 3, 'entry, shared and lazy chunks were loaded');
    const missing = page.waitForResponse(response => response.url() === origin + '/assets/obsolete.js', {timeout: 10000});
    await page.evaluate(() => new Promise(resolve => {
      const script = document.createElement('script');
      script.src = '/assets/obsolete.js'; script.onerror = () => resolve();
      script.onload = () => resolve(); document.body.append(script);
    }));
    assert.equal((await missing).status(), 404);
    assert.equal(await page.evaluate(async () => (await fetch('/api/missing', {headers: {Accept: 'application/json'}})).status), 404);
    assert.equal(await page.evaluate(async () => (await fetch('/orders/42', {method: 'POST', body: ''})).status), 405);
    for (const [base, mount] of [[generator, ''], [origin, '/docs']]) {
      result.stage = mount ? 'mounted-generator' : 'root-generator';
      const site = await context.newPage();
      const response = await site.goto(base + mount + '/guide?from=browser', {waitUntil: 'networkidle', timeout: 15000});
      assert.equal(response.status(), 200);
      headers(response);
      assert.equal(site.url(), base + mount + '/guide/?from=browser');
      assert.equal((await response.request().redirectedFrom().response()).status(), 308);
      assert.equal(await site.locator('#view').textContent(), 'Static guide');
      assert.equal(await site.locator('body').evaluate(element => getComputedStyle(element).color), 'rgb(20, 50, 80)');
      const missingUrl = base + mount + '/guide/missing';
      const missingDocument = site.waitForResponse(response => response.url() === missingUrl, {timeout: 15000});
      const [notFound] = await Promise.all([missingDocument,
        site.goto(missingUrl, {timeout: 15000}).catch(error => {
          // Chromium reports an empty error document as a failed navigation.
          assert.match(error.message, /net::ERR_HTTP_RESPONSE_CODE_FAILURE/);
        })]);
      assert.equal(notFound.status(), 404);
      await site.close();
    }
    result.version = version;
    result.deepLinkRefreshAndClientNavigation = true;
    result.lazyScripts = scripts.size;
    result.missingScriptAndJsonStay404 = true;
    result.rootAndMountedGeneratorRedirects = true;
  }
  assert.deepEqual(errors, []);
  delete result.stage;
  result.pageErrors = 0;
  await context.close();
  await writeFile(receipt, JSON.stringify(result));
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(JSON.stringify({stage: result.stage ?? 'csr-navigation', responses}));
  throw error;
} finally {
  clearTimeout(watchdog);
  await browser.close();
}
