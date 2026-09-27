// Review-time observation of these fixed maintained sources. A captured hash
// is not approval or runtime learning; signing and the host opt-in are separate.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, writeFile, stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {chromium} from 'playwright-core';

const [input, selectedMount, chrome, output] = process.argv.slice(2);
assert.ok(input && ['/', '/app'].includes(selectedMount) && chrome && output);
const directory = path.resolve(input), mount = selectedMount === '/' ? '' : selectedMount;
const server = createServer(async (request, response) => {
  try {
    assert.equal(request.method, 'GET');
    const url = new URL(request.url, 'http://127.0.0.1');
    assert.ok(url.pathname.startsWith(mount + '/'));
    const name = url.pathname.slice(mount.length + 1);
    assert.match(name, /^[A-Za-z0-9_./-]*$/);
    assert.ok(!name.split('/').some(part => part === '..' || part === '.'));
    const file = name.startsWith('assets/') ? name : 'index.html';
    const source = path.join(directory, file), info = await stat(source);
    assert.ok(info.isFile() && info.size < 8 * 1024 * 1024);
    const bytes = await readFile(source);
    response.writeHead(200, {'content-type': file.endsWith('.js') ? 'text/javascript' : 'text/html', 'connection': 'close'});
    response.end(bytes);
  } catch { response.writeHead(404).end(); }
});
server.maxConnections = 8; server.requestTimeout = 5000; server.headersTimeout = 5000;
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({executablePath: chrome, headless: true});
const timer = setTimeout(() => { void browser.close(); server.closeAllConnections(); server.close(); }, 60000);
const styles = new Map(), failures = [];
let capturedBytes = 0;
try {
  const page = await browser.newPage();
  page.on('pageerror', error => failures.push(error.message.slice(0, 256)));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const capture = async () => {
    for (const text of await page.locator('style').allTextContents()) {
      if (!text) continue;
      const digest = 'sha256:' + createHash('sha256').update(text).digest('hex');
      if (!styles.has(digest)) capturedBytes += Buffer.byteLength(text);
      styles.set(digest, Buffer.byteLength(text));
      assert.ok(styles.size <= 64 && capturedBytes <= 1024 * 1024);
    }
  };
  await page.goto(origin + mount + '/', {waitUntil: 'networkidle'});
  await page.locator('#view').filter({hasText: 'Order dashboard'}).waitFor(); await capture();
  await page.getByRole('link', {name: 'Order 42'}).click();
  await page.locator('#view').filter({hasText: 'Order 42'}).waitFor(); await capture();
  await page.getByRole('button', {name: 'Confirm order', exact: true}).click();
  await page.locator('#confirmation').filter({hasText: 'Confirmed'}).waitFor();
  for (const expected of ['Lara', 'Aura']) {
    await page.getByRole('button', {name: 'Change theme', exact: true}).click();
    await page.locator('#theme').filter({hasText: expected}).waitFor(); await capture();
  }
  assert.deepEqual(failures, []);
  const receipt = {schemaVersion: 'latent.framework.styles.v1', mount, styleHashes: [...styles.keys()].sort(),
    styles: [...styles].sort().map(([digest, bytes]) => ({digest, bytes})), capturedBytes,
    fixedSourceBrowserWalkthrough: true, nativeRuntimeQualified: false, approved: false};
  await writeFile(output, JSON.stringify(receipt));
  console.log(JSON.stringify({styles: styles.size, capturedBytes, mount, approved: false}));
} finally {
  clearTimeout(timer); await browser.close(); server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
