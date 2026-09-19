import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {generatedDirectory} from '../lib/prepare.mjs';
import {assetRoute, readSource, repositoryRoot, sha256, websiteRoot} from '../lib/repository.mjs';
import {contrast, loadPalette, palettePath, validatePalette} from '../lib/palette.mjs';
import {assertFocus, assertReflow, assertTextContrast, textSamples} from '../lib/theme-review.mjs';

const palette = loadPalette();
const inventory = JSON.parse(readSource(repositoryRoot, 'docs/assets/illustrations.json'));
const directory = generatedDirectory('.generated/theme-review');
const results = [];
const browser = await chromium.launch({headless: true, timeout: 15000});

async function visit(page, url) {
  assert.equal((await page.goto(url, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
}

async function screenshot(page, name) {
  await page.screenshot({path: path.join(directory, `${name}.png`), fullPage: true, animations: 'disabled'});
}

try {
  for (const variant of ['project', 'root']) {
    const built = validateBuiltSite(path.join(websiteRoot, 'build', variant));
    const server = await serveBuiltSite(path.join(websiteRoot, 'build', variant), built.manifest.baseUrl);
    const prefix = server.origin + built.manifest.baseUrl.slice(0, -1);
    try {
      for (const mode of ['light', 'dark']) {
        const context = await browser.newContext({viewport: {width: 1280, height: 900}, colorScheme: mode, reducedMotion: 'reduce'});
        const errors = [];
        await context.route('**/*', route => {
          if (new URL(route.request().url()).origin !== server.origin) { errors.push('External theme dependency'); return route.abort(); }
          return route.continue();
        });
        await context.addInitScript(() => {
          function firstFrame() {
            if (!document.body) { requestAnimationFrame(firstFrame); return; }
            const style = getComputedStyle(document.body);
            window.__lsfFirstFrame = {theme: document.documentElement.dataset.theme, color: style.color, background: style.backgroundColor};
          }
          requestAnimationFrame(firstFrame);
        });
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        page.on('pageerror', error => errors.push(error.message));
        try {
          await visit(page, `${prefix}/components/`);
          assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
          assert.equal((await page.evaluate(() => window.__lsfFirstFrame)).theme, mode, 'System theme must initialize before the first rendered body frame');
          const actual = await page.evaluate(() => Object.fromEntries(Array.from(getComputedStyle(document.documentElement)).filter(name => name.startsWith('--lsf-')).map(name => [name, getComputedStyle(document.documentElement).getPropertyValue(name).trim()])));
          for (const [token, value] of Object.entries(palette.modes[mode])) assert.equal(actual[`--lsf-${token.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`].toUpperCase(), value, token);
          const reading = assertTextContrast(await textSamples(page));
          await screenshot(page, `${variant}-${mode}-gallery`);
          await page.locator('.lsf-muted').evaluate(element => { element.style.color = getComputedStyle(document.body).backgroundColor; });
          assert.throws(() => assertTextContrast([{text: 'invisible canary', foreground: palette.modes[mode].canvas, background: palette.modes[mode].canvas}]), /contrast/);
          const canary = await textSamples(page, '.lsf-muted');
          assert.throws(() => assertTextContrast(canary), /contrast/);
          await page.locator('.lsf-muted').evaluate(element => element.style.removeProperty('color'));
          await page.getByRole('tab', {name: 'Contract', exact: true}).focus();
          await page.keyboard.press('ArrowRight');
          assert.equal(await page.getByRole('tab', {name: 'Evidence', exact: true}).getAttribute('aria-selected'), 'true');
          await assertFocus(page);
          await page.getByRole('button', {name: 'Exercise control', exact: true}).focus();
          await page.keyboard.press('Enter');
          await assertFocus(page);
          assert.match(await page.getByRole('status').innerText(), /exercised 1 times/);
          assert.equal(await page.getByRole('button', {name: 'Unavailable (disabled)', exact: true}).isDisabled(), true);
          await visit(page, `${prefix}/components/`);
          let keyboardStops = 0;
          for (let step = 0; step < 32; step += 1) {
            await page.keyboard.press('Tab');
            if (await page.evaluate(() => document.activeElement === document.body)) break;
            await assertFocus(page);
            keyboardStops += 1;
          }
          assert.ok(keyboardStops >= 16);
          const toggle = page.getByRole('button', {name: /Switch between dark and light mode/}).first();
          await toggle.focus();
          await page.keyboard.press('Enter');
          assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
          await page.keyboard.press('Enter');
          assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
          await page.reload({waitUntil: 'networkidle'});
          assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
          assert.equal((await page.evaluate(() => window.__lsfFirstFrame)).theme, 'dark', 'Persisted theme initializes before the first body frame');
          await toggle.focus();
          await page.keyboard.press('Enter');
          await page.emulateMedia({colorScheme: mode});
          assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
          await visit(page, `${prefix}/`);
          assertTextContrast(await textSamples(page));
          await screenshot(page, `${variant}-${mode}-home`);
          await visit(page, `${prefix}/docs/architecture/overview/`);
          assertTextContrast(await textSamples(page));
          assert.equal(await page.locator('article img[src*="-presentation.svg"]').count(), 2);
          await visit(page, `${prefix}/components/`);
          await page.setViewportSize({width: 390, height: 844});
          await assertReflow(page);
          assertTextContrast(await textSamples(page, 'main'));
          await screenshot(page, `${variant}-${mode}-mobile`);
          await page.getByRole('button', {name: /Toggle navigation bar/}).focus();
          await page.keyboard.press('Enter');
          await page.getByRole('button', {name: /Close navigation bar/}).focus();
          await page.keyboard.press('Enter');
          await page.setViewportSize({width: 640, height: 450});
          await assertReflow(page);
          assertTextContrast(await textSamples(page, 'main'));
          await screenshot(page, `${variant}-${mode}-reflow-200`);
          assert.equal(await page.evaluate(() => [...document.querySelectorAll('*')].filter(element => getComputedStyle(element).animationName !== 'none').length), 0);
          assert.deepEqual(errors, []);
          results.push({variant, mode, source: built.manifest.revision, dirty: built.manifest.dirty, reading, keyboardStops, firstFrame: 'system and persisted theme', reflow: '390px mobile and 640 CSS px equivalent to 1280px at 200%', requests: 'same-origin only', errors: 0});
        } finally { await context.close(); }
      }
      for (const entry of inventory.outputs) {
        const context = await browser.newContext({viewport: {width: 1440, height: 760}});
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        try {
          const asset = built.manifest.assets.find(asset => asset.path === entry.path);
          const original = built.manifest.assets.find(asset => asset.path === entry.source);
          assert.ok(asset && original);
          for (const [label, selected] of [['before', original], ['after', asset]]) {
            await visit(page, `${prefix}${assetRoute(selected)}`);
            const geometry = await page.evaluate(() => {
              const svg = document.querySelector('svg');
              const viewBox = svg.viewBox.baseVal;
              const texts = [...svg.querySelectorAll('text')].map(element => { const box = element.getBBox(); return {text: element.textContent.trim().slice(0, 80), left: box.x, right: box.x + box.width, top: box.y, bottom: box.y + box.height}; });
              const missingMarkers = [...svg.querySelectorAll('[marker-end]')].filter(element => !svg.querySelector(element.getAttribute('marker-end').slice(4, -1))).length;
              return {width: viewBox.width, height: viewBox.height, texts, missingMarkers};
            });
            assert.equal(geometry.missingMarkers, 0);
            assert.ok(geometry.texts.every(text => text.left >= 0 && text.right <= geometry.width && text.top >= 0 && text.bottom <= geometry.height), `SVG text clipped by viewBox: ${entry.path}`);
            await screenshot(page, `${variant}-${path.basename(entry.path, '.svg')}-${label}`);
          }
          for (const mode of ['light', 'dark']) {
            await page.setViewportSize({width: 390, height: 844});
            await page.setContent(`<html><body style="margin:16px;background:${palette.modes[mode].canvas};color:${palette.modes[mode].text};font:16px system-ui"><h1 style="font-size:22px">Presentation copy</h1><p>${entry.caption}</p><a href="${prefix}${assetRoute(asset)}" style="color:${palette.modes[mode].link}"><img alt="Historical relationship in the maintained palette" src="${prefix}${assetRoute(asset)}" style="max-width:100%;height:auto">Open full-size diagram</a><p>The linked original remains unchanged.</p></body></html>`);
            await page.waitForFunction(() => document.querySelector('img').complete && document.querySelector('img').naturalWidth > 0);
            await assertReflow(page);
            assertTextContrast(await textSamples(page));
            await screenshot(page, `${variant}-${path.basename(entry.path, '.svg')}-${mode}-embedded`);
            await page.getByRole('link').click();
            await page.waitForURL(`${prefix}${assetRoute(asset)}`);
            await page.locator('svg').evaluate(element => { element.style.width = '2880px'; element.style.maxWidth = 'none'; });
            assert.ok((await page.locator('svg').boundingBox()).width >= 2880);
          }
        } finally { await context.close(); }
      }
    } finally { await server.close(); }
  }
} finally { await browser.close(); }

const evidence = {schema: 1, measuredAt: new Date().toISOString(), paletteSha256: sha256(readSource(repositoryRoot, palettePath)), pairings: validatePalette(palette), results, limitations: ['Chromium on Windows only; no complete accessibility certification.', '200% responsive equivalent is 640 CSS px, not a claim of a native browser zoom shortcut campaign.', 'SVG text remains a two-dimensional diagram: full-size link and zoom are required for narrow displays.', 'Wiki source snapshot is inventoried, not migrated or republished.']};
fs.writeFileSync(path.join(directory, 'evidence.json'), `${JSON.stringify(evidence, null, 2)}\n`);
console.log(JSON.stringify({results, screenshots: path.relative(websiteRoot, directory)}));
