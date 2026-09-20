// Public, read-only publication smoke. No node credentials or Pages token.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {websiteRoot} from '../lib/repository.mjs';

const source = process.env.EXPECTED_SITE_SOURCE;
assert.match(source ?? '', /^[0-9a-f]{40}$/);
assert.equal(process.argv.length, 2);
const production = 'https://kirilsturkins.github.io/latent-service-fabric/';
const base = process.env.LSF_DOCS_LIVE_FIXTURE_URL ?? production;
assert.ok(base === production || /^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}\/latent-service-fabric\/$/.test(base));
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(websiteRoot, '.generated/browsers');
const {chromium} = await import('@playwright/test');
async function json(relative, maximum) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(base + relative, {redirect: 'error', signal: controller.signal});
    assert.equal(response.status, 200);
    let length = 0;
    const chunks = [];
    for await (const chunk of response.body) {
      length += chunk.length;
      assert.ok(length <= maximum);
      chunks.push(chunk);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally { clearTimeout(timer); controller.abort(); }
}
const publication = await json('publication.json', 256 * 1024);
const manifest = await json('site-manifest.json', 4 * 1024 * 1024);
assert.equal(publication.source, source);
assert.equal(manifest.revision, source);
assert.equal(manifest.dirty, false);
assert.equal(manifest.baseUrl, '/latent-service-fabric/');
const errors = [];
const browser = await chromium.launch({headless: true, timeout: 15000});
const context = await browser.newContext({permissions: ['clipboard-read', 'clipboard-write'], viewport: {width: 1280, height: 900}});
context.setDefaultTimeout(15000);
context.setDefaultNavigationTimeout(15000);
await context.route('**/*', route => {
  if (new URL(route.request().url()).origin !== new URL(base).origin) {
    errors.push('external-request');
    return route.abort();
  }
  return route.continue();
});
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
async function visit(relative) {
  assert.equal((await page.goto(base + relative, {waitUntil: 'networkidle'})).status(), 200);
}
async function version(label, identity) {
  const dropdown = page.locator('.navbar__item.dropdown').filter({has: page.locator('[aria-haspopup="true"]')});
  await dropdown.getByRole('button').hover();
  const link = dropdown.getByRole('link', {name: label, exact: true});
  const target = new URL(await link.getAttribute('href'), page.url());
  await link.click();
  await page.waitForURL(url => url.pathname === target.pathname);
  await page.locator(`[data-doc-version="${identity}"]`).waitFor();
  await page.waitForLoadState('networkidle');
}
try {
  await visit('');
  await visit('docs/architecture/overview/');
  assert.equal((await page.reload({waitUntil: 'networkidle'})).status(), 200);
  const asset = page.locator('article img').first();
  await asset.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => [...document.querySelectorAll('article img')].some(item => item.complete && item.naturalWidth > 0));
  await version('0.1.0-alpha.3 (alpha)', '0.1.0-alpha.3');
  assert.ok(new URL(page.url()).pathname.includes('/docs/0.1.0-alpha.3/'));
  await version('Development', 'development');
  await visit('docs/development/website-code-examples/');
  const example = page.locator('[data-example="guest/rust-echo"]');
  assert.equal(await example.getAttribute('data-document-version'), 'development');
  const panel = example.locator('[role="tabpanel"]:not([hidden])');
  assert.ok((await panel.locator('pre code').textContent()).length > 20);
  assert.ok((await panel.getByRole('link', {name: /^Complete Rust source/}).getAttribute('href')).includes(`/${source}/`));
  await panel.getByRole('button', {name: 'Copy Rust snippet', exact: true}).click();
  await panel.getByText('Rust snippet copied.', {exact: true}).waitFor();
  assert.ok((await page.evaluate(() => navigator.clipboard.readText())).length > 20);
  await page.getByRole('link', {name: 'Search documentation', exact: true}).click();
  await page.getByLabel('Search terms', {exact: true}).fill('publication');
  await page.getByRole('button', {name: 'Search', exact: true}).click();
  await page.getByRole('status').getByText(/results? in development\./).waitFor();
  await page.getByLabel('Documentation version', {exact: true}).selectOption('0.1.0-alpha.3');
  await page.getByRole('status').getByText(/results? in 0\.1\.0-alpha\.3\./).waitFor();
  assert.ok(await page.locator('[data-search-version]').count() > 0);
  assert.deepEqual(await page.locator('[data-search-version]').evaluateAll(nodes => Array.from(new Set(nodes.map(node => node.dataset.searchVersion)))), ['0.1.0-alpha.3']);
  await page.locator('.lsf-search-results a').first().click();
  await page.locator('[data-doc-version="0.1.0-alpha.3"]').waitFor();
  assert.equal((await page.reload({waitUntil: 'networkidle'})).status(), 200);
  await visit('guides/');
  await page.getByLabel('SDK language', {exact: true}).selectOption('Go');
  assert.equal(await page.locator('[data-guide="client-go"]').count(), 1);
  const missing = await context.request.get(base + 'lsf-intentionally-missing-publication-smoke/');
  assert.equal(missing.status(), 404);
  assert.deepEqual(errors, []);
} finally { await context.close(); await browser.close(); }
const receipt = {schema: 1, source, url: base, browser: browser.version(), ciRun: publication.ciRun,
  ciAttempt: publication.ciAttempt, artifactDigest: publication.artifactDigest,
  livePublication: base === production, home: true, nestedReload: true, asset: true,
  versionSwitch: true, developmentSourceExample: true, copiedCode: true,
  selectedVersionSearch: true, catalogue: true, missingRoute404: true, browserErrors: 0};
const output = path.join(websiteRoot, '.generated/live-review');
fs.mkdirSync(output, {recursive: true});
fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
