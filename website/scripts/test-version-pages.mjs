import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {generatedDirectory} from '../lib/prepare.mjs';
import {websiteRoot} from '../lib/repository.mjs';

const fixtures = process.argv[2] === '--fixtures';
assert.equal(process.argv.length, fixtures ? 3 : 2);
const expectations = fixtures ? JSON.parse(fs.readFileSync(path.join(websiteRoot, '.generated/version-fixture-expectations.json'), 'utf8')) : null;
const output = generatedDirectory('.generated/version-review');
const browser = await chromium.launch({headless: true, timeout: 15000});
const results = [];
async function selectVersion(page, label) {
  const dropdown = page.locator('.navbar__item.dropdown').filter({has: page.locator('[aria-haspopup="true"]')});
  await dropdown.getByRole('button').click();
  const link = dropdown.getByRole('link', {name: label, exact: true});
  const target = new URL(await link.getAttribute('href'), page.url());
  await link.click();
  await page.waitForURL(url => url.pathname === target.pathname);
  const version = label === 'Development' ? 'development' : label.replace(/ \(alpha\)$/, '');
  await page.locator(`[data-doc-version="${version}"]`).waitFor();
  await page.waitForLoadState('networkidle');
}
try {
  for (const variant of ['project', 'root']) {
    console.log(`[versions] validate ${fixtures ? 'fixtures' : 'publication'} ${variant}`);
    const directory = path.join(websiteRoot, 'build', variant);
    const built = validateBuiltSite(directory);
    const server = await serveBuiltSite(directory, built.manifest.baseUrl);
    const context = await browser.newContext({permissions: ['clipboard-read', 'clipboard-write'], viewport: {width: 1280, height: 900}});
    context.setDefaultTimeout(15000);
    context.setDefaultNavigationTimeout(15000);
    await context.addInitScript(() => {
      if (!navigator.clipboard) return;
      const writeText = navigator.clipboard.writeText.bind(navigator.clipboard);
      navigator.clipboard.writeText = text => { window.__lsfCopiedText = text; return writeText(text); };
    });
    const errors = [];
    try {
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      if (fixtures) {
        const [first, second] = expectations.versions;
        await page.goto(server.origin + built.manifest.baseUrl + `docs/${first.version}/development/website-code-examples/`, {waitUntil: 'networkidle'});
        const block = page.locator('[data-example="client/specimen"]');
        const panel = block.locator('[role="tabpanel"]:not([hidden])');
        const support = page.getByRole('complementary', {name: 'Documentation support'});
        async function verify(expected) {
          console.log(`[versions] verify ${variant} ${expected.version}`);
          assert.equal(await block.getAttribute('data-document-version'), expected.version);
          assert.equal(await support.getAttribute('data-doc-version'), expected.version);
          assert.match(await support.innerText(), /synthetic-fixture/);
          assert.equal(await support.getByRole('link', {name: 'Exact documentation source'}).getAttribute('href'),
            `https://github.com/KirilsTurkins/latent-service-fabric/tree/${expected.source}`);
          // The theme renders each line as a block span, so textContent omits
          // its visual line breaks. Verify exact source bytes at the real copy
          // boundary, including the trailing newline and Unicode characters.
          assert.equal(await panel.locator('pre code').textContent(), expected.snippet.replace(/\n/g, ''));
          await panel.getByRole('button', {name: 'Copy Rust snippet', exact: true}).click();
          await panel.getByText('Rust snippet copied.', {exact: true}).waitFor();
          assert.equal(await page.evaluate(() => window.__lsfCopiedText), expected.snippet);
          assert.match(await panel.getByRole('link', {name: 'View complete Rust source', exact: true}).getAttribute('href'), new RegExp(`/${expected.source}/`));
          const image = page.getByRole('img', {name: 'Synthetic version asset'});
          const src = await image.getAttribute('src');
          assert.ok(src.includes(`/content-assets/${expected.version}/${expected.assetSha256}/`));
          const asset = await context.request.get(new URL(src, page.url()).href);
          assert.equal(asset.status(), 200);
          assert.match(await asset.text(), new RegExp(expected.assetText));
          assert.equal(await block.getByRole('tab').count(), expected.languages);
        }
        await verify(first);
        await block.getByRole('tab', {name: 'Go', exact: true}).click();
        await selectVersion(page, `${second.version} (alpha)`);
        await verify(second);
        assert.match(await panel.innerText(), /requested language is unavailable.*Showing Rust/s);
        await page.reload({waitUntil: 'networkidle'});
        await verify(second);
        await selectVersion(page, `${first.version} (alpha)`);
        await block.getByRole('tab', {name: 'Rust', exact: true}).click();
        await verify(first);
        await selectVersion(page, 'Development');
        assert.equal(await page.locator('[data-example="client/ui-syntax"]').first().getAttribute('data-document-version'), 'development');
        assert.equal(await page.locator('[data-example="client/specimen"]').count(), 0);
        results.push({variant, fixtureOnly: true, sourceRevision: built.manifest.revision, versions: expectations.versions,
          switchedVersions: true, exactCode: true, distinctAssets: true, absentLanguage: true, sourceLinks: true,
          notices: true, directReload: true, returnedToDevelopment: true, browserErrors: errors.length});
      } else {
        assert.ok(built.manifest.versions.every(version => version.profile !== 'synthetic-fixture'));
        await page.goto(server.origin + built.manifest.baseUrl + 'docs/architecture/overview/', {waitUntil: 'networkidle'});
        assert.equal(await page.locator('[data-doc-version]').getAttribute('data-doc-version'), 'development');
        const released = built.manifest.versions.find(version => version.version === '0.1.0-alpha.3');
        assert.ok(released);
        await selectVersion(page, '0.1.0-alpha.3 (alpha)');
        assert.ok(new URL(page.url()).pathname.includes('/docs/0.1.0-alpha.3/architecture/overview/'));
        const support = page.getByRole('complementary', {name: 'Documentation support'});
        assert.equal(await support.getAttribute('data-doc-version'), released.version);
        assert.match(await support.innerText(), /Historical source snapshot/);
        assert.ok((await support.getByRole('link', {name: 'Exact documentation source'}).getAttribute('href')).includes(released.documentationSource));
        assert.equal(await page.locator('[data-document-version="development"]').count(), 0);
        await page.reload({waitUntil: 'networkidle'});
        await selectVersion(page, 'Development');
        assert.equal(await page.locator('[data-doc-version]').getAttribute('data-doc-version'), 'development');
        results.push({variant, fixtureOnly: false, sourceRevision: built.manifest.revision, releasedSnapshot: released.snapshotIdentity,
          releasedSource: released.documentationSource, switchedVersions: true, honestHistoricalAvailability: true,
          notices: true, directReload: true, browserErrors: errors.length});
      }
      assert.deepEqual(errors, []);
    } finally { await context.close(); await server.close(); }
  }
} finally { await browser.close(); }
fs.writeFileSync(path.join(output, fixtures ? 'fixtures.json' : 'publication.json'), JSON.stringify({schema: 1, browser: browser.version(), results}, null, 2) + '\n');
console.log(JSON.stringify(results));
