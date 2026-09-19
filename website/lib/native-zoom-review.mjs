import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {generatedDirectory} from './prepare.mjs';
import {websiteRoot} from './repository.mjs';
import {assertFocus, assertReflow, assertTextContrast, textSamples} from './theme-review.mjs';

export async function reviewNativeZoom(prefix, variant, screenshots) {
  const profileRoot = generatedDirectory('.generated/browser-profiles');
  const profile = fs.mkdtempSync(path.join(profileRoot, 'zoom-'));
  const extension = path.join(websiteRoot, 'tests/fixtures/native-zoom');
  const results = [];
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: 'chromium', headless: true, viewport: null, timeout: 15000,
      args: ['--window-size=1280,900', `--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
      reducedMotion: 'reduce',
    });
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker', {timeout: 10000});
    const page = context.pages()[0] ?? await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== new URL(prefix).origin) { errors.push('External native-zoom request'); return route.abort(); }
      return route.continue();
    });
    async function zoom(factor) {
      return worker.evaluate(async ({url, factor}) => {
        const matches = (await chrome.tabs.query({})).filter(tab => tab.url === url);
        if (matches.length !== 1 || !url.startsWith('http://127.0.0.1:')) throw new Error('Zoom fixture only owns one exact loopback tab');
        await chrome.tabs.setZoomSettings(matches[0].id, {mode: 'automatic', scope: 'per-tab'});
        await chrome.tabs.setZoom(matches[0].id, factor);
        return chrome.tabs.getZoom(matches[0].id);
      }, {url: page.url(), factor});
    }
    for (const mode of ['light', 'dark']) {
      await page.emulateMedia({colorScheme: mode});
      assert.equal((await page.goto(`${prefix}/components/`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      assert.equal(await zoom(1), 1);
      await page.waitForFunction(() => innerWidth >= 1200);
      const baseline = await page.evaluate(() => ({width: innerWidth, ratio: devicePixelRatio}));
      assert.equal(await zoom(2), 2);
      await page.waitForFunction(width => innerWidth <= width / 2 + 2, baseline.width);
      const magnified = await page.evaluate(() => ({width: innerWidth, ratio: devicePixelRatio}));
      assert.ok(Math.abs(magnified.ratio / baseline.ratio - 2) < 0.05);
      assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
      await assertReflow(page);
      assertTextContrast(await textSamples(page, 'main'));
      await page.getByRole('button', {name: /Toggle navigation bar/}).focus();
      await page.keyboard.press('Enter');
      await page.getByRole('button', {name: /Close navigation bar/}).focus();
      await assertFocus(page);
      await page.keyboard.press('Enter');
      await page.screenshot({path: path.join(screenshots, `${variant}-${mode}-native-zoom-200.png`), fullPage: true, animations: 'disabled'});
      assert.equal((await page.goto(`${prefix}/docs/architecture/overview/`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      await assertReflow(page);
      assertTextContrast(await textSamples(page, 'article'));
      assert.equal(await zoom(2), 2);
      results.push({variant, mode, browser: context.browser().version(), nativeZoom: 2, baseline, magnified, profile: 'isolated temporary profile', externalRequests: errors.length});
      assert.deepEqual(errors, []);
    }
    return results;
  } finally {
    await context?.close();
    assert.equal(path.dirname(fs.realpathSync(profile)), fs.realpathSync(profileRoot), 'Refuse cleanup outside the owned profile directory');
    assert.ok(!fs.lstatSync(profile).isSymbolicLink(), 'Refuse linked profile cleanup');
    fs.rmSync(profile, {recursive: true, force: true, maxRetries: 3, retryDelay: 200});
  }
}
