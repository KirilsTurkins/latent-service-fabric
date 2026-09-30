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
  const initialScripts = [];
  const syntheticToken = 'browser-policy-synthetic-token';
  context.on('request', request => {
    if (request.resourceType() === 'script' && initialScripts.length < 32) initialScripts.push(request);
  });
  page.on('pageerror', error => { if (errors.length < 8) errors.push(error.name); });
  const loaded = await page.goto(origin + home + '?synthetic-token=' + syntheticToken,
    {waitUntil: 'networkidle', timeout: 15000});
  assert.equal(loaded.status(), 200);
  const headers = loaded.headers();
  assert.match(headers['content-security-policy'], /script-src 'self'/);
  assert.match(headers['content-security-policy'], /base-uri 'none'/);
  assert.equal(headers['x-content-type-options'], 'nosniff');
  assert.equal(headers['cross-origin-resource-policy'], 'same-origin');
  assert.equal(headers['referrer-policy'], 'same-origin');
  assert.ok(!headers['access-control-allow-origin']);
  await page.waitForFunction(() => globalThis.boundaryHydrated === true, null, {timeout: 15000});
  assert.equal(await page.locator('meta[name="referrer"]').getAttribute('content'), 'no-referrer');
  assert.ok(initialScripts.length > 0 && initialScripts.length < 32);
  for (const request of initialScripts) assert.equal((await request.allHeaders()).referer, undefined);
  assert.equal(await page.evaluate(() => globalThis.boundaryTokenRemoved), true);
  assert.equal(page.url(), origin + home);
  const tokenFetchUrl = origin + home + '?synthetic-token=' + syntheticToken;
  const [tokenRequest, tokenFetch] = await Promise.all([
    page.waitForRequest(request => request.url() === tokenFetchUrl, {timeout: 5000}),
    page.evaluate(async target => {
      const response = await fetch(target, {mode: 'same-origin', credentials: 'omit',
        referrerPolicy: 'no-referrer', cache: 'no-store'});
      return {status: response.status, referrer: response.headers.get('referrer-policy')};
    }, tokenFetchUrl),
  ]);
  assert.deepEqual(tokenFetch, {status: 200, referrer: 'same-origin'});
  assert.equal((await tokenRequest.allHeaders()).referer, undefined);
  const expected = '</ScRiPt><script>globalThis.breakout=true</script><img src=x onerror=globalThis.breakout=true>&\u2028\u2029';
  assert.equal(await page.locator('#greeting').textContent(), 'Hello ' + expected);
  assert.equal(await page.evaluate(() => globalThis.breakout), undefined);
  assert.equal(await page.locator('#page').textContent(), 'Home');
  assert.equal(await page.evaluate(async url => (await fetch(url, {method: 'POST', mode: 'same-origin',
    referrerPolicy: 'same-origin', body: ''})).status, origin + home), 405);
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
    assert.ok(!String(requestHeaders.referer ?? '').includes(syntheticToken));
    assert.equal(applicationResponse.status(), 200);
    assert.equal(applicationResponse.headers()['x-app-principal'], 'browser-fixture');
    assert.equal(applicationResponse.headers()['cache-control'], 'no-store');
    assert.equal(applicationResponse.headers()['access-control-allow-origin'], undefined);
    for (const forbidden of ['/latent.invocation.v1.InvocationService/Invoke',
      '/latent.control.v1.PolicyService/ApplyPolicy', '/admin', '/api/greeting/extra']) {
      assert.equal(await page.evaluate(async target => (await fetch(target, {
        method: 'POST', mode: 'same-origin', credentials: 'omit', referrerPolicy: 'same-origin', body: '', redirect: 'error',
      })).status, forbidden), 404);
    }
    assert.equal(await page.evaluate(async () => (await fetch('/api/greeting', {
      method: 'GET', mode: 'same-origin', credentials: 'omit',
    })).status), 404);
    assert.equal(await page.evaluate(async () => (await fetch('/api/greeting', {
      method: 'POST', mode: 'same-origin', credentials: 'omit', referrerPolicy: 'same-origin', body: '{"name":"Browser"}',
      headers: {'content-type': 'application/json', authorization: 'Bearer synthetic-not-a-credential'},
    })).status), 401);
    const anonymous = await page.evaluate(async () => {
      const response = await fetch('/api/greeting', {
        method: 'POST', mode: 'same-origin', credentials: 'include', referrerPolicy: 'same-origin', body: '{"name":"Browser"}',
        headers: {'content-type': 'application/json'}, redirect: 'error', cache: 'no-store',
      });
      return {status: response.status, principal: response.headers.get('x-app-principal'), body: await response.json()};
    });
    assert.deepEqual(anonymous, {status: 200, principal: 'browser-fixture', body: {greeting: 'Hello Browser'}});
    const [noReferrerPost, rejectedOrigin] = await Promise.all([
      page.waitForRequest(request => request.url() === origin + '/api/greeting' &&
        request.method() === 'POST', {timeout: 5000}),
      page.evaluate(async () => {
        const response = await fetch('/api/greeting', {method: 'POST', mode: 'same-origin',
          credentials: 'omit', referrerPolicy: 'no-referrer', headers: {'content-type': 'application/json'},
          body: '{"name":"Browser"}', cache: 'no-store', redirect: 'error'});
        return {status: response.status, body: await response.text()};
      }),
    ]);
    assert.equal((await noReferrerPost.allHeaders()).origin, 'null');
    assert.deepEqual(rejectedOrigin, {status: 403, body: ''});
    for (const policy of ['referrer', 'casing', 'duplicate-location', 'duplicate-encoding',
      'header-case', 'crlf', 'header-bound']) {
      const rejected = await page.evaluate(async policy => {
        const response = await fetch('/api/greeting?header-policy=' + policy, {
          method: 'POST', mode: 'same-origin', credentials: 'omit', referrerPolicy: 'same-origin',
          headers: {'content-type': 'application/json'}, body: '{"name":"Browser"}',
          cache: 'no-store', redirect: 'error'});
        return {status: response.status, body: await response.text(),
          referrer: response.headers.get('referrer-policy'), cache: response.headers.get('cache-control'),
          principal: response.headers.get('x-app-principal'), cors: response.headers.get('access-control-allow-origin')};
      }, policy);
      assert.deepEqual(rejected, {status: 502, body: '', referrer: 'same-origin', cache: 'no-store',
        principal: null, cors: null});
    }
    const cacheResponses = await page.evaluate(async () => {
      const replies = [];
      for (let index = 0; index < 2; index++) {
        const response = await fetch('/api/greeting?header-policy=cache', {method: 'POST', mode: 'same-origin',
          credentials: 'omit', referrerPolicy: 'same-origin', body: '{"name":"Browser"}',
          headers: {'content-type': 'application/json'}, cache: 'no-store', redirect: 'error'});
        replies.push({status: response.status, cache: response.headers.get('cache-control'),
          referrer: response.headers.get('referrer-policy'), activation: response.headers.get('x-app-activation'),
          body: await response.json()});
      }
      return replies;
    });
    for (const response of cacheResponses) {
      assert.equal(response.status, 200);
      assert.equal(response.cache, 'no-store');
      assert.equal(response.referrer, 'same-origin');
      assert.deepEqual(response.body, {greeting: 'Hello Browser'});
      assert.ok(response.activation);
    }
    assert.notEqual(cacheResponses[0].activation, cacheResponses[1].activation);
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
  await page.evaluate(token => {
    history.replaceState(null, '', location.pathname + '?synthetic-token=' + token);
  }, syntheticToken);
  assert.equal(await page.locator('#next').getAttribute('rel'), 'noreferrer');
  assert.equal(await page.locator('#next').getAttribute('referrerpolicy'), 'no-referrer');
  const [navigation] = await Promise.all([
    page.waitForRequest(request => request.isNavigationRequest() && request.url().endsWith('/next.html'), {timeout: 15000}),
    page.waitForURL('**/next.html', {timeout: 15000}), page.locator('#next').click(),
  ]);
  assert.equal((await navigation.allHeaders()).referer, undefined);
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
    fixedSameOriginReferrerPolicy: true, buildTimeNoReferrerBeforeResources: true,
    syntheticTokenNavigationAndFetchDoNotBecomeReferrers: true,
    consumedTokenRemovedBeforeApplicationFetch: true,
    unsafeSameOriginNoReferrerOriginRejected: mode === 'public-application',
    applicationCacheInputQualified: mode === 'public-application',
    reservedHeadersRejectedAndRecoveryQualified: mode === 'public-application',
    navigationHydrated: true, escapedDataRoundTrip: true, inlineAndRemoteScriptsBlocked: true,
    baseOverrideBlocked: true, wrongScriptMimeBlocked: true, sameOriginPostReachedMethodPolicy: true, errors: errors.length};
  await writeFile(receipt, JSON.stringify(observations));
  console.log(JSON.stringify(observations));
  await context.close();
} finally {
  clearTimeout(watchdog);
  await browser.close();
}
