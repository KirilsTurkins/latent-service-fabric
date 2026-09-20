import assert from 'node:assert/strict';
import path from 'node:path';
import {assertFocus, assertReflow, assertTextContrast, textSamples} from './theme-review.mjs';

export async function reviewZoomReflow(browser, prefix, variant, screenshots) {
  const results = [];
  for (const mode of ['light', 'dark']) {
    const context = await browser.newContext({viewport: {width: 640, height: 450}, deviceScaleFactor: 2, colorScheme: mode, reducedMotion: 'reduce'});
    const errors = [];
    try {
      await context.route('**/*', route => {
        if (new URL(route.request().url()).origin !== new URL(prefix).origin) { errors.push('External zoom-reflow request'); return route.abort(); }
        return route.continue();
      });
      const page = await context.newPage();
      page.setDefaultTimeout(10000);
      page.on('pageerror', error => errors.push(error.message));
      assert.equal((await page.goto(`${prefix}/components/`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      const dimensions = await page.evaluate(() => ({width: innerWidth, height: innerHeight, ratio: devicePixelRatio}));
      assert.deepEqual(dimensions, {width: 640, height: 450, ratio: 2});
      assert.equal(await page.locator('html').getAttribute('data-theme'), mode);
      await assertReflow(page);
      const reading = assertTextContrast(await textSamples(page, 'main'));
      await page.getByRole('button', {name: /Toggle navigation bar/}).focus();
      await page.keyboard.press('Enter');
      await page.getByRole('button', {name: /Close navigation bar/}).focus();
      await assertFocus(page);
      await page.keyboard.press('Enter');
      const screenshot = `${variant}-${mode}-zoom-equivalent-200.png`;
      await page.screenshot({path: path.join(screenshots, screenshot), animations: 'disabled'});
      assert.equal((await page.goto(`${prefix}/docs/architecture/overview/`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      await assertReflow(page);
      assertTextContrast(await textSamples(page, 'article'));
      assert.deepEqual(errors, []);
      results.push({variant, mode, method: '640 CSS px at DPR 2: 200% rendering equivalent, not native browser zoom', dimensions, reading, screenshot, errors: 0});
    } finally { await context.close(); }
  }
  return results;
}
