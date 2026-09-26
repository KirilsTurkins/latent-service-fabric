// Public, read-only publication smoke. No node credentials or Pages token.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {repositoryRoot, websiteRoot} from '../lib/repository.mjs';
import {loadSnapshots} from '../lib/versions/storage.mjs';

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
const snapshots = loadSnapshots(repositoryRoot);
assert.ok(snapshots.length > 0);
assert.deepEqual(manifest.versions.map(version => version.snapshotIdentity), snapshots.map(snapshot => snapshot.manifest.snapshotIdentity));
const latest = snapshots[0].manifest.version;
const releasedExamples = [];
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
  for (const snapshot of snapshots) {
    const selected = snapshot.manifest;
    await version(`${selected.version} (alpha)`, selected.version);
    assert.ok(new URL(page.url()).pathname.includes(`/docs/${selected.version}/`));
    if (snapshot.examples.bundle.examples.some(example => example.id === 'guest/tutorial-greeting')) {
      await visit(`docs/${selected.version}/learn/author-your-first-capsule/`);
      const greeting = page.locator('[data-example="guest/tutorial-greeting"]');
      assert.equal(await greeting.getAttribute('data-document-version'), selected.version);
      assert.equal(await greeting.getByRole('tab').count(), 6);
      for (const label of ['Rust', 'TypeScript', 'Go', 'C', 'Java', 'C#/.NET']) {
        await greeting.getByRole('tab', {name: label, exact: true}).click();
        const selectedPanel = greeting.locator('[role="tabpanel"]:not([hidden])');
        assert.ok((await selectedPanel.locator('pre code').textContent()).length > 20);
        assert.ok((await selectedPanel.locator('a[href*="/blob/"]').first().getAttribute('href')).includes(`/${selected.exampleSource}/`));
        await selectedPanel.getByRole('button', {name: `Copy ${label} snippet`, exact: true}).click();
        await selectedPanel.getByText(`${label} snippet copied.`, {exact: true}).waitFor();
        assert.ok((await page.evaluate(() => navigator.clipboard.readText())).length > 20);
      }
      releasedExamples.push({version: selected.version, languages: 6, source: selected.exampleSource, copiedCode: true});
      await visit(`docs/${selected.version}/architecture/overview/`);
    }
  }
  await version('Development', 'development');
  await visit('docs/development/website-code-examples/');
  const example = page.locator('[data-example="guest/rust-echo"]');
  assert.equal(await example.getAttribute('data-document-version'), 'development');
  const panel = example.locator('[role="tabpanel"]:not([hidden])');
  assert.ok((await panel.locator('pre code').textContent()).length > 20);
  assert.ok((await panel.getByRole('link', {name: 'View complete Rust source', exact: true}).getAttribute('href')).includes(`/${source}/`));
  await panel.getByRole('button', {name: 'Copy Rust snippet', exact: true}).click();
  await panel.getByText('Rust snippet copied.', {exact: true}).waitFor();
  assert.ok((await page.evaluate(() => navigator.clipboard.readText())).length > 20);
  await page.getByRole('link', {name: 'Search documentation', exact: true}).click();
  await page.getByLabel('Search terms', {exact: true}).fill('publication');
  await page.getByRole('button', {name: 'Search', exact: true}).click();
  await page.getByRole('status').getByText(/results? in development\./).waitFor();
  await page.getByLabel('Documentation version', {exact: true}).selectOption(latest);
  await page.getByRole('status').getByText(new RegExp(`results? in ${latest.replaceAll('.', '\\.')}\\.`)).waitFor();
  assert.ok(await page.locator('[data-search-version]').count() > 0);
  assert.deepEqual(await page.locator('[data-search-version]').evaluateAll(nodes => Array.from(new Set(nodes.map(node => node.dataset.searchVersion)))), [latest]);
  await page.locator('.lsf-search-results a').first().click();
  await page.locator(`[data-doc-version="${latest}"]`).waitFor();
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
  selectedVersionSearch: true, selectedSearchVersion: latest, releasedExamples,
  releasedVersions: snapshots.map(snapshot => snapshot.manifest.version),
  catalogue: true, missingRoute404: true, browserErrors: 0};
const output = path.join(websiteRoot, '.generated/live-review');
fs.mkdirSync(output, {recursive: true});
fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
