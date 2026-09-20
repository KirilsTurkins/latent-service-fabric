import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import {chromium} from '@playwright/test';
import {serveBuiltSite, validateBuiltSite} from '../lib/built-site.mjs';
import {generatedDirectory} from '../lib/prepare.mjs';
import {websiteRoot} from '../lib/repository.mjs';

const output = generatedDirectory('.generated/discovery-review');
const results = [];
const browser = await chromium.launch({headless: true, timeout: 15000});
try {
  for (const variant of ['project', 'root']) {
    const directory = path.join(websiteRoot, 'build', variant);
    const built = validateBuiltSite(directory);
    const server = await serveBuiltSite(directory, built.manifest.baseUrl);
    const context = await browser.newContext({viewport: {width: 1280, height: 900}, reducedMotion: 'reduce'});
    const errors = [];
    const accessibility = [];
    try {
      await context.route('**/*', route => {
        if (new URL(route.request().url()).origin !== server.origin) { errors.push('Unexpected external request'); return route.abort(); }
        return route.continue();
      });
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      async function audit(name) {
        const result = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
        const serious = result.violations.filter(item => ['serious', 'critical'].includes(item.impact));
        assert.deepEqual(serious.map(item => ({id: item.id, impact: item.impact, nodes: item.nodes.map(node => node.target)})), [], `Accessibility: ${name}`);
        accessibility.push({name, serious: 0, other: result.violations.map(item => item.id)});
      }
      const prefix = server.origin + built.manifest.baseUrl;
      await page.goto(prefix, {waitUntil: 'networkidle'});
      await audit('home-light');
      await page.locator('main').getByRole('link', {name: 'Start', exact: true}).click();
      await page.waitForURL(`${prefix}docs/development/standalone-quickstart/`);
      await page.locator('[data-doc-version="development"]').waitFor();
      assert.equal((await page.reload({waitUntil: 'networkidle'})).status(), 200);
      await audit('first-guide');
      const search = page.getByRole('link', {name: 'Search documentation', exact: true});
      await search.focus();
      await page.keyboard.press('Enter');
      await page.waitForURL(url => url.pathname.endsWith('/search/'));
      await page.getByLabel('Search terms', {exact: true}).fill('publication');
      await page.getByRole('button', {name: 'Search', exact: true}).click();
      await page.getByRole('status').getByText(/results? in development\./).waitFor();
      assert.equal(new URL(page.url()).searchParams.get('q'), 'publication');
      await page.getByLabel('Documentation version', {exact: true}).selectOption('0.1.0-alpha.3');
      await page.getByRole('status').getByText(/results? in 0\.1\.0-alpha\.3\./).waitFor();
      assert.ok(await page.locator('[data-search-version]').count() > 0);
      assert.deepEqual(await page.locator('[data-search-version]').evaluateAll(nodes => [...new Set(nodes.map(node => node.dataset.searchVersion))]), ['0.1.0-alpha.3']);
      await audit('released-search');
      await page.locator('.lsf-search-results a').first().click();
      await page.locator('[data-doc-version="0.1.0-alpha.3"]').waitFor();
      assert.equal((await page.reload({waitUntil: 'networkidle'})).status(), 200);
      assert.ok((await page.getByRole('link', {name: 'Search documentation', exact: true}).getAttribute('href')).includes('version=0.1.0-alpha.3'));
      await page.getByRole('link', {name: 'Search documentation', exact: true}).click();
      await page.getByLabel('Search terms', {exact: true}).fill('zzzzmissingtermzzzz');
      await page.getByRole('button', {name: 'Search', exact: true}).click();
      await page.getByRole('status').getByText(/No results in 0\.1\.0-alpha\.3/).waitFor();
      await page.goto(`${prefix}search/?q=publication&version=not-published`, {waitUntil: 'networkidle'});
      await page.getByRole('status').getByText(/not published/).waitFor();
      assert.equal(await page.locator('[data-search-version]').count(), 0);
      await page.goto(`${prefix}guides/`, {waitUntil: 'networkidle'});
      await page.getByLabel('SDK language', {exact: true}).selectOption('Go');
      assert.equal(await page.locator('[data-guide]').count(), 1);
      assert.equal(await page.locator('[data-guide]').getAttribute('data-guide'), 'client-go');
      await page.getByLabel('Topic', {exact: true}).selectOption('angular-browser');
      await page.getByRole('status').getByText(/No tasks match/).waitFor();
      await page.getByRole('link', {name: 'Clear filters', exact: true}).click();
      await page.getByRole('status').getByText(/27 tasks/).waitFor();
      await audit('catalogue-light');
      const toggle = page.getByRole('button', {name: /Switch between dark and light mode/});
      for (let attempt = 0; attempt < 3 && await page.locator('html').getAttribute('data-theme') !== 'dark'; attempt++) await toggle.click();
      assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
      await audit('catalogue-dark');
      await page.setViewportSize({width: 390, height: 844});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await audit('catalogue-mobile');
      await page.screenshot({path: path.join(output, `${variant}-catalogue-mobile.png`), fullPage: true});
      await page.setViewportSize({width: 640, height: 900});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
      await page.setViewportSize({width: 1280, height: 900});
      await page.goto(`${prefix}docs/component-development/creating-a-capsule/`, {waitUntil: 'networkidle'});
      const original = new URL(page.url()).pathname;
      const next = page.locator('.pagination-nav__link--next');
      await next.click();
      await page.waitForURL(url => url.pathname !== original);
      await page.locator('.pagination-nav__link--prev').click();
      await page.waitForURL(url => url.pathname === original);
      assert.deepEqual(errors, []);
      results.push({variant, sourceRevision: built.manifest.revision, search: built.search,
        firstGuide: true, selectedVersionSearch: true, queryUrl: true, noResults: true, missingVersion: true,
        filteredCatalogue: true, previousNext: true, directReload: true, keyboardSearch: true,
        mobileWidth: 390, reflowWidth: 640, reducedMotion: true, externalRequests: 0, browserErrors: 0, accessibility});
    } finally { await context.close(); await server.close(); }
  }
} finally { await browser.close(); }
fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify({schema: 1, browser: browser.version(), results}, null, 2) + '\n');
console.log(JSON.stringify(results));
