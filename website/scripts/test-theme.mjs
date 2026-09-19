import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {generatedDirectory} from '../lib/prepare.mjs';
import {assetRoute, readSource, repositoryRoot, sha256, websiteRoot} from '../lib/repository.mjs';
import {loadPalette, palettePath, validatePalette} from '../lib/palette.mjs';
import {assertColorPair, assertFocus, assertReflow, assertTextContrast, cssHex, textSamples} from '../lib/theme-review.mjs';
import {reviewZoomReflow} from '../lib/zoom-reflow-review.mjs';

const palette = loadPalette();
const inventory = JSON.parse(readSource(repositoryRoot, 'docs/assets/illustrations.json'));
const directory = generatedDirectory('.generated/theme-review');
const results = [];
const zoomReflow = [];
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
        const hydrationRequests = [];
        let allowHydration = false;
        await context.route('**/*', route => {
          if (new URL(route.request().url()).origin !== server.origin) { errors.push('External theme dependency'); return route.abort(); }
          if (!allowHydration && new URL(route.request().url()).pathname.endsWith('.js')) return new Promise(resolve => hydrationRequests.push(() => resolve(route.continue())));
          return route.continue();
        });
        await context.addInitScript(() => {
          const observer = new PerformanceObserver(list => {
            if (list.getEntries().some(entry => entry.name === 'first-contentful-paint')) {
              const style = getComputedStyle(document.body);
              const background = style.backgroundColor === 'rgba(0, 0, 0, 0)' ? getComputedStyle(document.documentElement).backgroundColor : style.backgroundColor;
              window.__lsfFirstPaint = {theme: document.documentElement.dataset.theme, color: style.color, background};
              observer.disconnect();
            }
          });
          observer.observe({type: 'paint', buffered: true});
        });
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        page.on('pageerror', error => errors.push(error.message));
        try {
          assert.equal((await page.goto(`${prefix}/components/`, {waitUntil: 'commit', timeout: 15000})).status(), 200);
          await page.waitForFunction(() => window.__lsfFirstPaint !== undefined);
          assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
          const firstFrame = await page.evaluate(() => window.__lsfFirstPaint);
          assert.equal(firstFrame.theme, mode, 'System theme must initialize before first contentful paint, with hydration held');
          assertColorPair(firstFrame.color, firstFrame.background);
          assert.equal(cssHex(firstFrame.background), palette.modes[mode].canvas);
          allowHydration = true;
          for (const resume of hydrationRequests.splice(0)) resume();
          await page.waitForLoadState('networkidle', {timeout: 15000});
          const actual = await page.evaluate(() => Object.fromEntries(Array.from(getComputedStyle(document.documentElement)).filter(name => name.startsWith('--lsf-')).map(name => [name, getComputedStyle(document.documentElement).getPropertyValue(name).trim()])));
          for (const [token, value] of Object.entries(palette.modes[mode])) assert.equal(actual[`--lsf-${token.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`].toUpperCase(), value, token);
          const reading = assertTextContrast(await textSamples(page));
          const lineNumber = await page.locator('[class*="codeLineNumber"]').first().evaluate(element => ({color: getComputedStyle(element, '::before').color, opacity: getComputedStyle(element, '::before').opacity, background: getComputedStyle(element).backgroundColor}));
          assert.equal(lineNumber.opacity, '1');
          assertColorPair(lineNumber.color, lineNumber.background);
          const selection = await page.locator('main p').first().evaluate(element => ({color: getComputedStyle(element, '::selection').color, background: getComputedStyle(element, '::selection').backgroundColor}));
          assertColorPair(selection.color, selection.background);
          await page.getByRole('button', {name: 'Exercise control', exact: true}).hover();
          assertTextContrast(await textSamples(page, '.lsf-controls'));
          await page.getByRole('link', {name: 'links remain visibly underlined', exact: true}).hover();
          assertTextContrast(await textSamples(page, 'main'));
          await page.mouse.move(0, 0);
          await page.evaluate(() => window.scrollTo(0, 0));
          await screenshot(page, `${variant}-${mode}-gallery`);
          await page.locator('.lsf-muted').evaluate(element => { element.style.color = getComputedStyle(document.body).backgroundColor; });
          assert.throws(() => assertTextContrast([{text: 'invisible canary', foreground: palette.modes[mode].canvas, background: palette.modes[mode].canvas}]), /contrast/);
          const canary = await textSamples(page, '.lsf-muted');
          assert.throws(() => assertTextContrast(canary), /contrast/);
          await page.locator('.lsf-muted').evaluate(element => element.style.removeProperty('color'));
          await page.getByRole('tab', {name: 'Contract', exact: true}).focus();
          await page.keyboard.press('ArrowRight');
          assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Evidence');
          await page.keyboard.press('Enter');
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
          await page.waitForFunction(() => window.__lsfFirstPaint !== undefined);
          assert.equal((await page.evaluate(() => window.__lsfFirstPaint)).theme, 'dark', 'Persisted theme initializes before first contentful paint');
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
          await visit(page, `${prefix}/docs/development/website/`);
          await page.locator('.docusaurus-mermaid-container svg').waitFor({state: 'visible'});
          assert.equal(await page.locator('.docusaurus-mermaid-container foreignObject').count(), 0);
          const mermaid = await page.locator('.docusaurus-mermaid-container').evaluate(element => ({color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor}));
          assertColorPair(mermaid.color, mermaid.background);
          const mermaidText = await page.locator('.docusaurus-mermaid-container svg text').evaluateAll(elements => elements.map(element => getComputedStyle(element).fill));
          assert.ok(mermaidText.length >= 4);
          for (const color of mermaidText) {
            assert.equal(cssHex(color), palette.modes.dark.text);
            assertColorPair(color, palette.modes.dark.surface);
            assertColorPair(color, palette.modes.dark.raised);
          }
          await screenshot(page, `${variant}-${mode}-mermaid`);
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
          results.push({variant, mode, source: built.manifest.revision, dirty: built.manifest.dirty, reading, keyboardStops, firstPaint: 'system theme with hydration held; persisted theme on reload', reflow: '390px mobile and 640 CSS px equivalent to 1280px at 200%', requests: 'same-origin only', errors: 0});
        } finally {
          allowHydration = true;
          for (const resume of hydrationRequests.splice(0)) resume();
          await context.close();
        }
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
              const texts = [...svg.querySelectorAll('text')].map(element => { const box = element.getBBox(); return {text: element.textContent.trim().slice(0, 80), color: getComputedStyle(element).fill, left: box.x, right: box.x + box.width, top: box.y, bottom: box.y + box.height}; });
              const missingMarkers = [...svg.querySelectorAll('[marker-end]')].filter(element => !svg.querySelector(element.getAttribute('marker-end').slice(4, -1))).length;
              return {width: viewBox.width, height: viewBox.height, texts, missingMarkers};
            });
            assert.equal(geometry.missingMarkers, 0);
            assert.ok(geometry.texts.every(text => text.left >= 0 && text.right <= geometry.width && text.top >= 0 && text.bottom <= geometry.height), `SVG text clipped by viewBox: ${entry.path}`);
            if (label === 'after') {
              for (const text of geometry.texts) {
                for (const background of ['canvas', 'surface', 'raised', 'successSurface', 'warningSurface']) assertColorPair(text.color, palette.modes.dark[background]);
              }
              for (let index = 0; index < geometry.texts.length; index += 1) {
                const current = geometry.texts[index];
                for (const other of geometry.texts.slice(index + 1)) {
                  const overlapWidth = Math.min(current.right, other.right) - Math.max(current.left, other.left);
                  const overlapHeight = Math.min(current.bottom, other.bottom) - Math.max(current.top, other.top);
                  assert.ok(overlapWidth <= 0.5 || overlapHeight <= 0.5, `Overlapping SVG labels: ${current.text} / ${other.text}`);
                }
              }
            }
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
      zoomReflow.push(...await reviewZoomReflow(browser, prefix, variant, directory));
    } finally { await server.close(); }
  }
} finally { await browser.close(); }

const evidence = {schema: 1, measuredAt: new Date().toISOString(), browser: browser.version(), paletteSha256: sha256(readSource(repositoryRoot, palettePath)), pairings: validatePalette(palette), results, zoomReflow, limitations: ['Chromium headless shell on Windows only; no complete accessibility certification or screen-reader campaign.', '200% rendering is exercised by halving the CSS viewport and doubling DPR, not by native browser zoom controls. Native browser zoom remains a manual acceptance check.', 'SVG text remains a two-dimensional diagram: full-size link and zoom are required for narrow displays.', 'Wiki source snapshot is inventoried, not migrated or republished.']};
fs.writeFileSync(path.join(directory, 'evidence.json'), `${JSON.stringify(evidence, null, 2)}\n`);
console.log(JSON.stringify({results, zoomReflow, screenshots: path.relative(websiteRoot, directory)}));
