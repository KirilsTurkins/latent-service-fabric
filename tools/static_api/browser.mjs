import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';

const [tools, chrome, origin] = process.argv.slice(2);
const {chromium} = createRequire(path.resolve(tools, 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: chrome, headless: true});
const watchdog = setTimeout(() => {process.exitCode = 1; browser.close();}, 45000);
const errors = [], requests = [];
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.name));
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  const response = await page.goto(origin + '/', {waitUntil: 'networkidle', timeout: 20000});
  assert.equal(response.status(), 200);
  assert.match(response.headers()['content-security-policy'], /script-src 'self'/);
  assert.equal(await page.locator('#result').textContent(), 'Ready to check.');
  const api = page.waitForResponse(response => response.url() === origin + '/api/status');
  await page.locator('#check').click();
  assert.equal((await api).status(), 200);
  await page.waitForFunction(() => document.querySelector('#result').textContent === 'Service is available.');
  assert.equal((await page.request.get(origin + '/api/missing')).status(), 404);
  assert.equal((await page.request.post(origin + '/api/status', {headers: {Origin: origin}})).status(), 405);
  assert.ok(requests.includes('/status.js') && requests.includes('/style.css') && requests.includes('/api/status'));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({executed: true, passed: true, browser: browser.version(),
    staticScriptExecuted: true, actualButtonAndCapsule: true, apiFallbackExcluded: true, pageErrors: errors.length}));
  await context.close();
} finally {
  clearTimeout(watchdog);
  await browser.close();
}
