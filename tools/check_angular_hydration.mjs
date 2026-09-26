// Hydrate the maintained builder's exact client against real generic-cell HTML.
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

const [toolchain, build, rendered, chrome] = process.argv.slice(2);
const {chromium} = createRequire(path.join(path.resolve(toolchain), 'package.json'))('playwright-core');
const html = await readFile(rendered);
assert.ok(html.length <= 131072);
const manifest = JSON.parse(await readFile(path.join(build, 'inputs/metadata/web-application.json')));
const asset = manifest.assets.filter(item => /^\/client\/[0-9a-f]{64}\/main\.js$/.test(item.path));
assert.equal(asset.length, 1);
const selected = asset[0];
assert.equal(selected.layer, 'public' + selected.path);
const client = await readFile(path.join(build, 'inputs', selected.layer));
assert.ok(client.length <= 8 * 1024 * 1024);
assert.equal(selected.digest, 'sha256:' + createHash('sha256').update(client).digest('hex'));
assert.ok(!client.includes(Buffer.from('lsf-private-server-fixture-234')));
const origin = 'https://renderer.invalid';
const browser = await chromium.launch({executablePath: chrome, headless: true});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => { if (errors.length < 16) errors.push(String(error).slice(0, 512)); });
  await page.route('**/*', route => {
    const url = route.request().url();
    if (url === origin + '/') return route.fulfill({status: 200, contentType: 'text/html; charset=utf-8', body: html});
    if (url === origin + selected.path) return route.fulfill({status: 200, contentType: 'text/javascript; charset=utf-8', body: client});
    return route.abort();
  });
  await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 15000});
  await page.waitForFunction(() => globalThis.lsfHydrated === true, null, {timeout: 15000});
  assert.equal(await page.evaluate(() => globalThis.serverHeading === document.getElementById('greeting')), true);
  assert.equal(await page.locator('#greeting').textContent(), 'Hello Alice <unsafe>');
  assert.equal(await page.locator('#count').textContent(), 'Count 0');
  await page.locator('#count').click();
  await page.waitForFunction(() => document.getElementById('count').textContent === 'Count 1', null, {timeout: 15000});
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({browser: browser.version(), actualBuildHydrated: true,
    originalDomReused: true, escapedInputText: true, clickUpdatedSignal: true, errors}));
} finally {
  await browser.close();
}
