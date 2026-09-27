import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {chromium} from 'playwright-core';

const [chrome, angular, docs, output] = process.argv.slice(2);
assert.ok(chrome && angular && docs && output);
const browser = await chromium.launch({executablePath: chrome, headless: true,
  args: process.platform === 'linux' && process.getuid() === 0 ? ['--no-sandbox'] : []});
const watchdog = setTimeout(() => { process.exitCode = 1; void browser.close(); }, 150000);
const receipt = {schemaVersion: 'latent.framework.browser.v1', browser: browser.version(), pages: []};

function policy(response, hashes) {
  assert.equal(response.status(), 200);
  const headers = response.headers(), csp = headers['content-security-policy'];
  assert.match(csp, /script-src 'self';/); assert.match(csp, /base-uri 'none';/);
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|nonce-/);
  assert.equal(csp.includes("'sha256-"), hashes);
  assert.equal(headers['x-content-type-options'], 'nosniff');
}

async function protections(page) {
  const before = await page.evaluate(() => globalThis.lsfViolations.length);
  const base = await page.evaluate(() => document.baseURI);
  await page.evaluate(() => {
    const script = document.createElement('script'); script.textContent = 'globalThis.lsfUnapprovedScript = true'; document.head.append(script);
    const style = document.createElement('style'); style.textContent = 'body{--lsf-unapproved:applied}'; document.head.append(style);
    const foreign = document.createElement('script'); foreign.src = 'https://unapproved.invalid/foreign.js'; document.head.append(foreign);
    const foreignStyle = document.createElement('link'); foreignStyle.rel = 'stylesheet'; foreignStyle.href = 'https://unapproved.invalid/foreign.css'; document.head.append(foreignStyle);
    const base = document.createElement('base'); base.href = 'https://unapproved.invalid/'; document.head.append(base);
  });
  await page.waitForFunction(count => globalThis.lsfViolations.length >= count + 5, before, {timeout: 10000});
  const evidence = await page.evaluate(() => ({script: globalThis.lsfUnapprovedScript ?? false,
    style: getComputedStyle(document.body).getPropertyValue('--lsf-unapproved'), base: document.baseURI,
    denied: globalThis.lsfViolations.slice(-5)}));
  assert.equal(evidence.script, false); assert.equal(evidence.style, ''); assert.equal(evidence.base, base);
  assert.ok(evidence.denied.some(event => event.directive === 'base-uri'));
  assert.ok(evidence.denied.some(event => event.directive.startsWith('script-src') && event.blocked === 'inline'));
  assert.ok(evidence.denied.some(event => event.directive.startsWith('style-src') && event.blocked === 'inline'));
  assert.equal(evidence.denied.filter(event => event.blocked.startsWith('https://unapproved.invalid')
    && /^(script|style)-src/.test(event.directive)).length, 2);
  return evidence.denied;
}

try {
  for (const kind of ['angular', 'docs']) for (const mount of ['', kind === 'angular' ? '/app' : '/docs']) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [], badResponses = [], failedRequests = [], violations = [], scripts = new Set(), rejectedStyleHashes = new Set();
    let documents = 0;
    await page.exposeFunction('lsfRecordCsp', event => { if (violations.length < 64) violations.push(event); });
    await page.addInitScript(() => { globalThis.lsfViolations = []; document.addEventListener('securitypolicyviolation', event => {
      const record = {directive: event.effectiveDirective, blocked: event.blockedURI};
      if (globalThis.lsfViolations.length < 64) globalThis.lsfViolations.push(record);
      void globalThis.lsfRecordCsp(record);
    }); });
    page.on('pageerror', error => { if (errors.length < 16) errors.push(error.message.slice(0, 512)); });
    page.on('console', message => {
      if (rejectedStyleHashes.size >= 64) return;
      const text = message.text();
      if (text.includes('inline style')) {
        const match = text.match(/hash \('sha256-([A-Za-z0-9+/=]+)'\)/);
        if (match) rejectedStyleHashes.add('sha256:' + Buffer.from(match[1], 'base64').toString('hex'));
      }
    });
    page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++; });
    page.on('requestfailed', request => {
      if (failedRequests.length < 16) failedRequests.push({path: new URL(request.url()).pathname.slice(1),
        reason: request.failure()?.errorText.slice(0, 128)});
    });
    page.on('response', response => {
      if (response.status() >= 400 && badResponses.length < 16) badResponses.push({url: new URL(response.url()).pathname, status: response.status()});
      if (response.request().resourceType() === 'script' && response.status() === 200) scripts.add(response.url());
    });
    const origin = kind === 'angular' ? angular : docs;
    policy(await page.goto(origin + mount + '/', {waitUntil: 'networkidle', timeout: 20000}), kind === 'angular');
    if (kind === 'angular') {
      await page.locator('#view').filter({hasText: 'Order dashboard'}).waitFor();
      assert.equal(await page.locator('h1').evaluate(element => getComputedStyle(element).fontSize), '32px');
      const before = documents;
      await page.getByRole('link', {name: 'Order 42'}).click();
      await page.locator('#view').filter({hasText: 'Order 42'}).waitFor();
      assert.equal(documents, before, 'Angular navigates through its lazy route');
      assert.equal(await page.locator('#view').evaluate(element => getComputedStyle(element).color), 'rgb(24, 64, 100)');
      await page.getByRole('button', {name: 'Confirm order', exact: true}).click();
      await page.locator('#confirmation').filter({hasText: 'Confirmed'}).waitFor();
      for (const expected of ['Lara', 'Aura']) {
        await page.getByRole('button', {name: 'Change theme', exact: true}).click();
        await page.locator('#theme').filter({hasText: expected}).waitFor();
        assert.notEqual(await page.getByRole('button', {name: 'Change theme', exact: true})
          .evaluate(element => getComputedStyle(element).backgroundColor), 'rgba(0, 0, 0, 0)');
      }
      assert.ok(scripts.size >= 3, 'actual entry/shared/lazy chunks loaded');
      assert.equal((await page.evaluate(() => globalThis.lsfViolations)).length, 0,
        'unapproved Angular style identities: ' + JSON.stringify([...rejectedStyleHashes]));
      policy(await page.reload({waitUntil: 'networkidle'}), true);
      await page.locator('#view').filter({hasText: 'Order 42'}).waitFor();
    } else {
      await page.getByRole('heading', {name: 'Welcome to the handbook', exact: true}).waitFor();
      await page.getByRole('link', {name: 'release guide', exact: true}).click();
      await page.getByRole('heading', {name: 'Release guide', exact: true}).waitFor();
      await page.waitForLoadState('networkidle', {timeout: 15000});
      const theme = page.getByRole('button', {name: /Switch between dark and light mode/});
      const originalTheme = await page.locator('html').getAttribute('data-theme');
      // Docusaurus cycles system -> light -> dark; system and light may render identically.
      for (let changes = 0; changes < 3 && await page.locator('html').getAttribute('data-theme') === originalTheme; changes++) {
        const choice = await page.locator('html').getAttribute('data-theme-choice');
        await theme.click();
        await page.waitForFunction(previous => document.documentElement.getAttribute('data-theme-choice') !== previous, choice);
      }
      assert.notEqual(await page.locator('html').getAttribute('data-theme'), originalTheme);
      policy(await page.goto(origin + mount + '/de/', {waitUntil: 'networkidle'}), false);
      await page.getByRole('heading', {name: 'Willkommen im Handbuch', exact: true}).waitFor();
      await page.getByRole('link', {name: 'Anleitung', exact: true}).click();
      await page.getByRole('heading', {name: /^Anleitung/}).waitFor();
      await page.waitForLoadState('networkidle', {timeout: 15000});
      policy(await page.goto(origin + mount + '/guide', {waitUntil: 'networkidle'}), false);
      assert.equal(new URL(page.url()).pathname, mount + '/guide/');
      await page.getByRole('heading', {name: 'Release guide', exact: true}).waitFor();
      assert.ok(scripts.size >= 4, 'actual localized and lazy generator chunks loaded');
    }
    assert.deepEqual(errors, [], 'framework must run without browser errors: ' + JSON.stringify({kind, mount, badResponses, failedRequests}));
    assert.deepEqual(badResponses, [], 'required framework requests succeed');
    assert.deepEqual(violations, [], 'all previous pages and transitions satisfy CSP');
    assert.deepEqual(await page.evaluate(() => globalThis.lsfViolations), [], 'legitimate framework behavior satisfies CSP');
    const denied = await protections(page);
    receipt.pages.push({kind, mount: mount || '/', scripts: scripts.size, denied, visibleFunctionality: true});
    await context.close();
  }
  receipt.passed = true;
  await writeFile(output, JSON.stringify(receipt), {flag: 'wx', mode: 0o600});
} finally { clearTimeout(watchdog); await browser.close(); }
