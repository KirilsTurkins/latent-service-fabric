import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {generatedDirectory, prepare} from '../lib/prepare.mjs';
import {websiteRoot} from '../lib/repository.mjs';

const output = generatedDirectory('.generated/code-example-review');
const {examples} = prepare();
const specimen = examples.bundle.examples.find(example => example.id === 'client/ui-syntax');
const browser = await chromium.launch({headless: true, timeout: 15000});
const results = [];
try {
  for (const variant of ['project', 'root']) {
    const directory = path.join(websiteRoot, 'build', variant);
    const built = validateBuiltSite(directory);
    const server = await serveBuiltSite(directory, built.manifest.baseUrl);
    const url = server.origin + built.manifest.baseUrl + 'docs/development/website-code-examples/';
    const context = await browser.newContext({permissions: ['clipboard-read', 'clipboard-write'], viewport: {width: 1280, height: 900}});
    await context.addInitScript(() => {
      const writeText = navigator.clipboard.writeText.bind(navigator.clipboard);
      navigator.clipboard.writeText = text => {
        window.__lsfCopiedText = text;
        return writeText(text);
      };
    });
    const errors = [];
    context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
    try {
      const page = await context.newPage();
      await page.goto(url, {waitUntil: 'networkidle'});
      const blocks = page.locator('[data-example="client/ui-syntax"]');
      assert.equal(await blocks.count(), 2);
      assert.equal(await blocks.first().getByRole('tab').count(), 6);
      await blocks.first().getByRole('tab', {name: 'Java', exact: true}).click();
      await blocks.last().getByRole('tab', {name: 'Java', exact: true}).waitFor();
      assert.equal(await blocks.last().getByRole('tab', {name: 'Java', exact: true}).getAttribute('aria-selected'), 'true');
      assert.equal(new URL(page.url()).searchParams.get('lsf-client-language'), 'java');
      assert.match(await page.locator('[data-example="client/ui-subset"] [role="tabpanel"]:not([hidden])').innerText(), /unavailable.*Showing Rust/s);
      assert.equal(await page.locator('[data-example="guest/rust-echo"]').getByRole('tab', {name: 'Rust'}).getAttribute('aria-selected'), 'true');
      await page.reload({waitUntil: 'networkidle'});
      assert.equal(await blocks.first().getByRole('tab', {name: 'Java', exact: true}).getAttribute('aria-selected'), 'true');
      for (const language of ['Rust', 'TypeScript', 'Go', 'C', 'Java', 'C#/.NET']) {
        await blocks.first().getByRole('tab', {name: language, exact: true}).click();
        const panel = blocks.first().locator('[role="tabpanel"]:not([hidden])');
        const id = await panel.getAttribute('id');
        const tab = blocks.first().getByRole('tab', {name: language, exact: true});
        assert.equal(await tab.getAttribute('aria-controls'), id);
        assert.equal(await panel.getAttribute('aria-labelledby'), await tab.getAttribute('id'));
        await panel.getByRole('button', {name: `Copy ${language} snippet`, exact: true}).click();
        await panel.getByText(`${language} snippet copied.`, {exact: true}).waitFor();
        const key = await panel.locator('[data-example-language]').getAttribute('data-example-language');
        const expected = specimen.regions[0].variants.find(v => v.language === key).snippet.code;
        assert.equal(await page.evaluate(() => window.__lsfCopiedText), expected);
        // Windows' native clipboard converts LF to CRLF. The API input above
        // must still be byte-for-byte source text, before that OS conversion.
        const nativeText = await page.evaluate(() => navigator.clipboard.readText());
        assert.equal(nativeText.replace(/\r\n/g, '\n'), expected);
      }
      const remembered = await context.newPage();
      await remembered.goto(url, {waitUntil: 'networkidle'});
      assert.equal(await remembered.locator('[data-example="client/ui-syntax"]').first().getByRole('tab', {name: 'C#/.NET', exact: true}).getAttribute('aria-selected'), 'true');
      await remembered.close();
      await page.goto(url + '?lsf-client-language=invalid&lsf-guest-language=c', {waitUntil: 'networkidle'});
      const selected = blocks.first().getByRole('tab', {name: 'Rust', exact: true});
      await selected.focus();
      await page.keyboard.press('ArrowRight');
      await page.keyboard.press('Enter');
      assert.equal(await blocks.first().getByRole('tab', {name: 'TypeScript', exact: true}).getAttribute('aria-selected'), 'true');
      assert.equal(await page.evaluate(() => window.__lsfUnsafeExample), undefined);
      await page.setViewportSize({width: 390, height: 844});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({path: path.join(output, `${variant}-mobile.png`), fullPage: true});
      const denied = await browser.newContext();
      try {
        await denied.addInitScript(() => {
          Storage.prototype.getItem = () => { throw new DOMException('Storage disabled', 'SecurityError'); };
          Storage.prototype.setItem = () => { throw new DOMException('Storage disabled', 'SecurityError'); };
          Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('Clipboard disabled'))}});
        });
        const deniedPage = await denied.newPage();
        deniedPage.on('pageerror', error => errors.push(error.message));
        await deniedPage.goto(url, {waitUntil: 'networkidle'});
        const block = deniedPage.locator('[data-example="client/ui-syntax"]').first();
        await block.getByRole('tab', {name: 'Go', exact: true}).click();
        await block.getByRole('button', {name: 'Copy Go snippet', exact: true}).click();
        await block.getByText('Clipboard unavailable. Select and copy the code below.', {exact: true}).waitFor();
      } finally { await denied.close(); }
      assert.deepEqual(errors, []);
      results.push({variant, sourceRevision: built.manifest.revision, documentVersion: examples.bundle.documentVersion, languages: 6,
        staticVariants: true, synchronizedBlocks: 2, separateTargets: true, exactCopyPayload: true, nativeClipboard: true, deniedApis: true,
        keyboardRelations: true, mobileWidth: 390, hydrationErrors: 0});
    } finally { await context.close(); await server.close(); }
  }
} finally { await browser.close(); }
fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify({schema: 1, browser: browser.version(), results}, null, 2));
console.log(JSON.stringify(results));
