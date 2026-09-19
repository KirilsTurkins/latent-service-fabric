import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {assetRoute, basePath, canonicalPath, createRepositoryIndex, documentMetadata, parseDocument, readSource, resolveLink, routeFor, validateAssets} from '../lib/repository.mjs';
import {rehypeRepositoryLinks, transformDocument} from '../plugins/repository-links.mjs';

function fixture(context, extra = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-site-fixture-'));
  context.after(() => {
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, {recursive: true});
  });
  const files = {
    'docs/nested/start.md': '# Start\n\n## Failure cases\n',
    'docs/escaped page.md': '---\nslug: /escaped-page\n---\n# Über 東京\n\n## Detail\n',
    'adr/0001-decision.md': '# Decision\n\n## Why\n',
    'adr/README.md': '# Decisions\n',
    'sdk/source file.ts': 'export const fixture = true;\n',
    'docs/assets/safe.svg': '<svg xmlns="http://www.w3.org/2000/svg"><title>Safe</title></svg>',
    ...extra,
  };
  for (const [relative, content] of Object.entries(files)) {
    const target = path.join(root, ...relative.split('/'));
    fs.mkdirSync(path.dirname(target), {recursive: true});
    fs.writeFileSync(target, content);
  }
  const index = createRepositoryIndex(root, Object.keys(files), '1234567890abcdef1234567890abcdef12345678');
  const assets = validateAssets(root, {schema: 1, assets: [{path: 'docs/assets/safe.svg', kind: 'illustration', maxBytes: 1024}]}, index);
  return {root, index, assets};
}

test('cross-root documents, ADR identities, escaped paths and source links bind to one revision', context => {
  const {index, assets} = fixture(context);
  assert.equal(resolveLink(index, 'docs/nested/start.md', '../../adr/0001-decision.md#why'), '/latent-service-fabric/decisions/0001-decision/#why');
  assert.equal(resolveLink(index, 'docs/nested/start.md', '../escaped%20page.md#detail'), '/latent-service-fabric/docs/escaped-page/#detail');
  assert.match(resolveLink(index, 'docs/nested/start.md', '../../sdk/source%20file.ts#L1'), /\/blob\/1234567890abcdef1234567890abcdef12345678\/sdk\/source%20file.ts#L1$/);
  assert.equal(resolveLink(index, 'docs/nested/start.md', '#failure-cases', {baseUrl: '/'}), '/docs/nested/start/#failure-cases');
  assert.equal(resolveLink(index, 'docs/nested/start.md', '../assets/safe.svg', {assets, image: true}), `/latent-service-fabric${assetRoute(assets[0])}`);
  assert.equal(routeFor('adr/README.md'), '/decisions/');
});

test('missing, wrongly cased, escaped and unsafe links fail instead of silently becoming source links', context => {
  const {index} = fixture(context);
  for (const url of ['missing.md', '../Escaped%20page.md', '#absent', '../../../outside', '../%2e%2e/secret', '../../sdk%2fsource%20file.ts', 'javascript:alert(1)', 'file:///tmp/secret', '//remote.invalid/file']) {
    assert.throws(() => resolveLink(index, 'docs/nested/start.md', url), undefined, url);
  }
  assert.throws(() => resolveLink(index, 'docs/nested/start.md', 'https://example.invalid/image.svg', {image: true}), /Remote image/);
  assert.throws(() => resolveLink(index, 'docs/nested/start.md', '../../sdk/source%20file.ts', {image: true}), /not individually approved/);
  assert.throws(() => basePath('/../'), /Base path/);
  assert.throws(() => canonicalPath('docs/../secret'), /Noncanonical/);
  assert.throws(() => resolveLink(index, 'docs/nested/start.md', '../../sdk/source%20file.ts#L99'), /Missing source line/);
  assert.throws(() => resolveLink(index, 'docs/nested/start.md', '/latent-service-fabric/docs/nested/start/', {image: true}), /not approved image/);
});

test('route collisions, case collisions and asset expansion are rejected', context => {
  assert.throws(() => fixture(context, {'adr/index.md': '# Duplicate index\n'}), /route collision/);
  const {root, index} = fixture(context);
  assert.throws(() => createRepositoryIndex(root, [...index.paths, 'docs/NESTED/start.md'], index.revision), /Case-colliding/);
  assert.throws(() => validateAssets(root, {schema: 1, assets: [{path: 'sdk/source file.ts', kind: 'illustration', maxBytes: 1024}]}, index), /Unapproved asset/);
  assert.throws(() => readSource(root, 'docs/assets/safe.svg', 4), /oversized/);
});

test('symlink inputs cannot escape into an unowned source or asset', context => {
  const {root, index} = fixture(context);
  try {
    fs.symlinkSync(path.join(root, 'sdk/source file.ts'), path.join(root, 'docs/linked.md'));
  } catch (error) {
    if (error.code === 'EPERM') { context.skip('This Windows host cannot construct symlinks; run this negative fixture on Linux.'); return; }
    throw error;
  }
  assert.throws(() => createRepositoryIndex(root, [...index.paths, 'docs/linked.md'], index.revision), /Linked input/);
});

test('Unicode, repeat headings, CommonMark prose and explicit HTML anchors retain their identities', () => {
  const metadata = documentMetadata('# Über 東京\n\n## Repeat\n\n## Repeat\n\n<a id="explicit"></a>\n', 'docs/example.md');
  assert.deepEqual(metadata.anchors, ['über-東京', 'repeat', 'repeat-1', 'explicit']);
  assert.doesNotThrow(() => parseDocument('# Prose\n\nLiteral {notJavaScript} <T>\n', 'docs/example.md'));
  assert.throws(() => parseDocument('---\nformat: mdx\n---\n{sideEffect()}\n', 'docs/example.md'), /execution mode/);
  assert.throws(() => parseDocument('---\nslug: one\nslug: two\n---\n# Duplicate\n', 'docs/example.md'));
});

test('approved bounded downloads use both base paths; unapproved source material is never copied', context => {
  const {root, index} = fixture(context, {'docs/assets/example.txt': 'Harmless download fixture\n'});
  const assets = validateAssets(root, {schema: 1, assets: [{path: 'docs/assets/example.txt', kind: 'download', maxBytes: 1024}]}, index);
  for (const baseUrl of ['/', '/latent-service-fabric/']) {
    const download = `${baseUrl.slice(0, -1)}${assetRoute(assets[0])}`;
    assert.equal(resolveLink(index, 'docs/nested/start.md', '../assets/example.txt', {baseUrl, assets}), download);
    assert.throws(() => resolveLink(index, 'docs/nested/start.md', download, {baseUrl, assets, image: true}), /not an approved image/);
  }
});

test('global approved brand assets are independent of the development illustration channel', context => {
  const {root, index} = fixture(context, {'website/static/brand/logo.svg': '<svg xmlns="http://www.w3.org/2000/svg"><title>Brand fixture</title></svg>'});
  const assets = validateAssets(root, {schema: 1, assets: [{path: 'website/static/brand/logo.svg', kind: 'brand', maxBytes: 1024}]}, index);
  assert.equal(assetRoute(assets[0], 'development'), assetRoute(assets[0], 'released-alpha'));
  for (const baseUrl of ['/', '/latent-service-fabric/']) {
    assert.equal(resolveLink(index, 'docs/nested/start.md', '../../website/static/brand/logo.svg', {baseUrl, assets, image: true}), `${baseUrl.slice(0, -1)}${assetRoute(assets[0])}`);
  }
});

test('approved file links use static navigation, including mixed image/link references, without an unchecked escape hatch', context => {
  const {index, assets} = fixture(context);
  const source = 'docs/nested/start.md';
  for (const baseUrl of ['/', '/latent-service-fabric/']) {
    const tree = transformDocument(parseDocument('[Download][asset]\n\n![Diagram][asset]\n\n[asset]: ../assets/safe.svg\n', source), index, source, {baseUrl, assets});
    const target = `${baseUrl.slice(0, -1)}${assetRoute(assets[0])}`;
    assert.equal(tree.children[0].children[0].url, `pathname://${target}`);
    assert.equal(tree.children[1].children[0].attributes.find(attribute => attribute.name === 'src').value, target);
    const htmlTree = {type: 'root', children: [{type: 'element', tagName: 'a', properties: {href: `pathname://${target}`}, children: []}]};
    const transform = rehypeRepositoryLinks({index, baseUrl, assets});
    transform(htmlTree, {path: path.join(index.root, source)});
    assert.equal(htmlTree.children[0].properties.href, `pathname://${target}`);
    htmlTree.children[0].properties.href = 'pathname:///unapproved.txt';
    assert.throws(() => transform(htmlTree, {path: path.join(index.root, source)}), /Only approved static/);
    assert.throws(() => transformDocument(parseDocument(`[Unchecked](pathname://${target})\n`, source), index, source, {baseUrl, assets}), /unsafe URL scheme/);
  }
});

test('directory symlinks or Windows junctions cannot be used as source escapes', context => {
  const {root, index} = fixture(context);
  fs.symlinkSync(path.join(root, 'sdk'), path.join(root, 'docs/redirect'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createRepositoryIndex(root, [...index.paths, 'docs/redirect/source file.md'], index.revision), /Linked input/);
});

test('reviewed MDX cannot use links as remote includes or import arbitrary repository code', context => {
  const {index, assets} = fixture(context);
  const source = 'docs/nested/start.md';
  for (const payload of ['<script>neverExecuted()</script>', '<img src="https://example.invalid/image.svg">', '<a href="javascript:neverExecuted()">bad</a>']) {
    assert.throws(() => transformDocument(parseDocument(payload, source), index, source, {assets, baseUrl: '/'}));
  }
  const mdx = 'docs/nested/start.mdx';
  assert.throws(() => transformDocument(parseDocument('import value from "../../sdk/source.ts"\n\n# Bad\n', mdx), index, mdx, {}), /reviewed site components/);
  assert.throws(() => transformDocument(parseDocument('<a href={"dynamic"}>Bad</a>\n', mdx), index, mdx, {}), /must be literals/);
});
