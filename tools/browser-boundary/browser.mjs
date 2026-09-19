import {createRequire} from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';

const [toolchain, chrome, origin, home, wrongMime, receipt] = process.argv.slice(2);
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
    navigationHydrated: true, escapedDataRoundTrip: true, inlineAndRemoteScriptsBlocked: true,
    baseOverrideBlocked: true, wrongScriptMimeBlocked: true, sameOriginPostReachedMethodPolicy: true, errors: errors.length};
  await writeFile(receipt, JSON.stringify(observations));
  console.log(JSON.stringify(observations));
  await context.close();
} finally {
  clearTimeout(watchdog);
  await browser.close();
}
