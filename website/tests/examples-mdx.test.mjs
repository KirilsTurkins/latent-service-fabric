import assert from 'node:assert/strict';
import test from 'node:test';
import {compile, run} from '@mdx-js/mdx';
import * as runtime from 'react/jsx-runtime';
import {renderToStaticMarkup} from 'react-dom/server';
import {parseDocument} from '../lib/repository.mjs';
import {extractExamples} from '../plugins/examples/extract.mjs';
import {remarkExamples, requestsFromTree} from '../plugins/examples/remark.mjs';
import {verifyExampleHtml} from '../plugins/examples/built.mjs';
import {fixture} from './example-fixtures.mjs';

// Runs under the existing pinned website dependency graph, not a replacement
// Markdown renderer. The fixture target deliberately throws if ever executed.
test('actual Markdown/MDX compilation escapes six source variants as inert static code', async t => {
  const f = fixture(t);
  const markdown = '# Source example\n\n<!-- lsf-example: client/specimen invoke -->\n';
  const requests = requestsFromTree(parseDocument(markdown, 'docs/specimen.md'));
  const {bundle} = extractExamples(f.root, requests, f.identity());
  const compiled = await compile(markdown, {format: 'md', outputFormat: 'function-body',
    remarkPlugins: [() => remarkExamples({bundle, documentVersion: 'development'})]});
  const {default: Content} = await run(String(compiled), {...runtime, baseUrl: import.meta.url});
  const html = renderToStaticMarkup(runtime.jsx(Content, {}));
  assert.equal((html.match(/<pre>/g) ?? []).length, 6);
  assert.doesNotMatch(html, /<script|UNREFERENCED_SENTINEL|lsf-example-begin/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /source extraction only/);
  assert.ok(html.includes(f.initialRevision));
  assert.equal(verifyExampleHtml(html, bundle, requests), 6);
  assert.throws(() => verifyExampleHtml(html.replaceAll('alert(1)', 'changed'), bundle, requests), /changed built/);
  assert.throws(() => verifyExampleHtml(html.replaceAll('href=', 'data-removed='), bundle, requests), /link/);
});
