import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {websiteRoot} from '../lib/repository.mjs';

const results = [];
const browser = await chromium.launch({headless: true, timeout: 15000});
try {
  for (const variant of ['project', 'root']) {
    const output = path.join(websiteRoot, 'build', variant);
    const result = validateBuiltSite(output);
    const server = await serveBuiltSite(output, result.manifest.baseUrl);
    const context = await browser.newContext({viewport: {width: 1280, height: 900}});
    const errors = [];
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== server.origin) {
        errors.push('Unexpected external browser request');
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.setDefaultTimeout(10000);
    try {
      const prefix = server.origin + result.manifest.baseUrl.slice(0, -1);
      const response = await page.goto(`${prefix}/`, {waitUntil: 'networkidle', timeout: 15000});
      assert.equal(response.status(), 200);
      assert.match(await page.locator('main').innerText(), /development/);
      await page.screenshot({path: path.join(websiteRoot, `.generated/${variant}-home.png`)});
      await page.getByRole('link', {name: 'Understand', exact: true}).last().click();
      await page.waitForURL(`${prefix}/docs/architecture/overview/`);
      assert.equal((await page.reload({waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      assert.ok(await page.locator('article img').count() >= 1);
      await page.locator('article img').first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll('article img')].some(image => image.complete && image.naturalWidth > 0));
      for (const route of ['/docs/protocol/invocation-service/', '/docs/runtime/capability-broker/', '/decisions/0041-publish-single-source-version-bound-documentation/']) {
        assert.equal((await page.goto(`${prefix}${route}`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
        assert.equal((await page.reload({waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      }
      assert.equal((await page.goto(`${prefix}/docs/development/website/`, {waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      assert.equal((await page.reload({waitUntil: 'networkidle', timeout: 15000})).status(), 200);
      await page.locator('article .docusaurus-mermaid-container svg').waitFor({state: 'visible'});
      assert.match(await page.locator('article .docusaurus-mermaid-container').innerText(), /Static website output/);
      await page.setViewportSize({width: 390, height: 844});
      assert.ok(await page.locator('main').isVisible());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
      await page.screenshot({path: path.join(websiteRoot, `.generated/${variant}-mobile.png`)});
      assert.equal((await page.request.get(`${prefix}/not-a-real-page/`)).status(), 404);
      assert.deepEqual(errors, []);
      results.push({variant, source: result.manifest.revision, dirty: result.manifest.dirty, baseUrl: result.manifest.baseUrl, pages: result.pages, checkedLinks: result.checkedLinks, publicJavaScript: result.publicJavaScript, nestedReloads: 5, approvedAssetBytes: 'unchanged', mermaid: 'rendered', browserErrors: 0, screenshots: [`${variant}-home.png`, `${variant}-mobile.png`]});
    } finally {
      await context.close();
      await server.close();
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(websiteRoot, '.generated/build-evidence.json'), `${JSON.stringify({schema: 1, results}, null, 2)}\n`);
console.log(JSON.stringify({status: 'pass', results}));
