import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import MiniSearch from 'minisearch';
import {pageRecords, buildSearch, validateSearch} from '../lib/search-build.mjs';
import {channelFromPath, searchDocuments, searchOptions, searchState} from '../lib/search.mjs';

const html = (code, extra = '') => `<html><head>${extra}</head><body><nav>PRIVATE_NAV_SENTINEL</nav><article><div class="theme-doc-markdown"><h1>Client guide</h1><p>Invoke a capsule.</p><h2 id="invoke">Invoke</h2><pre><code>${code}</code></pre><div hidden>Go: invokeLegacy()</div><script>PRIVATE_SCRIPT_SENTINEL</script></div></article></body></html>`;
const page = (version = 'development') => ({source: 'docs/client.md', route: `/docs/${version}/client/`, title: 'Client guide', channel: version});

test('local search indexes rendered code and anchors while excluding scripts, navigation and no-index pages', () => {
  const records = pageRecords(html('call&lt;T&gt;()'), page(), 'Synthetic test');
  assert.ok(records.some(record => record.route.endsWith('#invoke') && record.text.includes('call<T>()')));
  assert.ok(records.some(record => record.text.includes('invokeLegacy')));
  assert.equal(JSON.stringify(records).includes('PRIVATE_'), false);
  assert.deepEqual(pageRecords(html('secret', '<meta name="robots" content="nofollow,noindex">'), page(), 'test'), []);
  assert.throws(() => pageRecords('<main>Wrong renderer</main>', page(), 'test'), /Missing rendered/);
});

test('the selected version is mandatory in results, including absent APIs and unsafe-looking queries', () => {
  const index = new MiniSearch(searchOptions);
  index.addAll([
    ...pageRecords(html('modernInvoke()'), page(), 'Development'),
    ...pageRecords(html('legacyInvoke()'), page('0.1.0-alpha.3'), 'Released alpha'),
  ].map((record, id) => ({id, ...record})));
  assert.equal(searchDocuments(index, 'modernInvoke', '0.1.0-alpha.3').length, 0);
  assert.ok(searchDocuments(index, 'legacyInvoke', '0.1.0-alpha.3').every(result => result.version === '0.1.0-alpha.3'));
  assert.equal(searchDocuments(index, '<script>alert(1)</script>', 'development').length, 0);
  assert.equal(searchDocuments(index, 'x'.repeat(129), 'development').length, 0);
  assert.match(searchState('?version=missing&q=client', ['development']).error, /not published/);
  assert.equal(channelFromPath('/project/docs/0.1.0-alpha.3/client/', '/project/', ['development', '0.1.0-alpha.3']), '0.1.0-alpha.3');
  assert.equal(channelFromPath('/project/docs/client/', '/project/', ['development']), 'development');
  assert.equal(channelFromPath('/project/guides/', '/project/', ['development']), null);
});

test('stale built content or a changed index fails the publication check', t => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-search-'));
  t.after(() => fs.rmSync(output, {recursive: true, force: true}));
  const input = page();
  const filename = path.join(output, input.route, 'index.html');
  fs.mkdirSync(path.dirname(filename), {recursive: true});
  fs.writeFileSync(filename, html('originalInvoke()'));
  const manifest = {revision: 'a'.repeat(40), baseUrl: '/project/', pages: [input], versions: []};
  const receipt = buildSearch(output, manifest);
  assert.equal(receipt.indexedPages, 1);
  assert.deepEqual(validateSearch(output, manifest), receipt);
  fs.writeFileSync(filename, html('changedInvoke()'));
  assert.throws(() => validateSearch(output, manifest), /differs from the actual built/);
  buildSearch(output, manifest);
  const index = path.join(output, 'search-index.json');
  fs.writeFileSync(index, fs.readFileSync(index, 'utf8').replace('development', 'wrong-version'));
  assert.throws(() => validateSearch(output, manifest), /differs from the actual built/);
});
