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
import {createProcessors, getProcessor} from '@docusaurus/mdx-loader/lib/processor.js';
import {websiteRoot} from '../lib/repository.mjs';
import config from '../docusaurus.config.ts';

test('the configured Docusaurus pipeline retains example selectors until extraction', async t => {
  const f = fixture(t, ['rust']);
  const content = '# Source example\n\n<!-- lsf-example: client/specimen invoke -->\n';
  const {bundle} = extractExamples(f.root, requestsFromTree(parseDocument(content, 'docs/specimen.md')), f.identity());
  const options = {siteDir: websiteRoot, staticDirs: [], removeContentTitle: false,
    markdownConfig: {...config.markdown, anchors: {maintainCase: false}, emoji: false},
    beforeDefaultRemarkPlugins: [() => remarkExamples({bundle, documentVersion: 'development'})]};
  options.processors = await createProcessors({options});
  const filePath = `${websiteRoot}/tests/specimen.md`;
  const processor = await getProcessor({filePath, mdxFrontMatter: {}, options});
  const result = await processor.process({content, filePath, frontMatter: {}, compilerName: 'server'});
  assert.ok(result.content.includes('alert(1)'), 'The registered snippet must survive the actual configured compiler');
  assert.ok(result.content.includes('source extraction only'));
  assert.ok(!result.content.includes('lsf-example-begin'));
});

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
  // The pinned Docusaurus CodeBlock emits a div and <br> for each Prism line,
  // whereas the plain MDX renderer above emits literal newline text nodes.
  const highlighted = html.replace(/<code([^>]*)>([\s\S]*?)<\/code>/g, (_, attributes, body) =>
    `<code${attributes}>${body.replace(/\n$/, '').split('\n').map(line => `<div class="token-line"><span>${line}</span><br></div>`).join('')}</code>`);
  assert.equal(verifyExampleHtml(highlighted, bundle, requests), 6);
  assert.throws(() => verifyExampleHtml(highlighted.replace('<br>', ''), bundle, requests), /changed built/);
});
