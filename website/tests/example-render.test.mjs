import assert from 'node:assert/strict';
import test from 'node:test';
import {extractExamples} from '../plugins/examples/extract.mjs';
import {exampleNodes, remarkExamples, requestsFromTree} from '../plugins/examples/remark.mjs';
import {resolveExample} from '../plugins/examples/resolve.mjs';
import {fixture} from './example-fixtures.mjs';

const marker = '<!-- lsf-example: client/specimen invoke -->';
const request = {documentVersion: 'development', example: 'client/specimen', region: 'invoke'};

test('only explicit comment nodes request source data; fenced authoring examples are inert', () => {
  const tree = {type: 'root', children: [{type: 'code', value: marker}, {type: 'html', value: marker}]};
  assert.deepEqual(requestsFromTree(tree), [{example: 'client/specimen', region: 'invoke'}]);
  assert.throws(() => requestsFromTree({type: 'html', value: '<!-- lsf-example: client/specimen invoke extra -->'}), /Malformed/);
  assert.throws(() => requestsFromTree({type: 'root', children: Array(257).fill({type: 'html', value: marker})}), /limit/);
});

test('dangerous-looking source becomes code values, never HTML, MDX or executable imports', t => {
  const f = fixture(t);
  const {bundle} = extractExamples(f.root, f.requests, f.identity());
  const tree = {type: 'root', children: [{type: 'blockquote', children: [{type: 'html', value: marker}]}]};
  remarkExamples({bundle, documentVersion: 'development'})(tree);
  const codes = [], unsafe = [];
  const walk = node => { if (node.type === 'code') codes.push(node); if (/html|mdx|expression|esm/i.test(node.type)) unsafe.push(node); for (const child of node.children ?? []) walk(child); };
  walk(tree);
  assert.equal(codes.length, 6); assert.deepEqual(unsafe, []);
  assert.ok(codes.every(node => node.value.includes('<script>alert(1)</script>')));
  assert.ok(codes.every(node => node.value.includes("{import('node:fs')}")));
  assert.deepEqual(codes.map(node => node.value), resolveExample(bundle, request).variants.map(variant => variant.snippet.code));
  assert.doesNotMatch(JSON.stringify(tree), /UNREFERENCED_SENTINEL/);
});

test('resolver refuses absent versions, scenarios and regions instead of using development', t => {
  const f = fixture(t, ['rust']); const {bundle} = extractExamples(f.root, f.requests, f.identity());
  for (const change of [{documentVersion: 'alpha.1'}, {documentVersion: undefined}, {example: 'guest/elsewhere'}, {region: 'private'}]) {
    assert.throws(() => resolveExample(bundle, {...request, ...change}), /version/);
  }
  assert.equal(resolveExample(bundle, request).variants.length, 1);
});

test('two independent snapshots select their own source, code and verification notice', t => {
  const f = fixture(t, ['rust']);
  const older = extractExamples(f.root, f.requests, {...f.identity(), documentVersion: 'alpha.1'}).bundle;
  f.write(f.scenario.variants[0].source, f.read(f.scenario.variants[0].source).replace('alert(1)', 'alert(2)'));
  f.commit();
  const newer = extractExamples(f.root, f.requests, {...f.identity(), documentVersion: 'alpha.2'}).bundle;
  for (const [bundle, label, number] of [[older, 'alpha.1', 1], [newer, 'alpha.2', 2]]) {
    const nodes = exampleNodes(bundle, {...request, documentVersion: label});
    assert.ok(nodes.find(node => node.type === 'code').value.includes(`alert(${number})`));
    assert.match(JSON.stringify(nodes), /source extraction only/);
  }
  assert.notEqual(older.sourceRevision, newer.sourceRevision);
  assert.throws(() => resolveExample(older, {...request, documentVersion: 'alpha.2'}), /identity/);
});

test('CodeExample accepts only literal registered data requests', () => {
  const node = {type: 'mdxJsxFlowElement', name: 'CodeExample', attributes: [
    {type: 'mdxJsxAttribute', name: 'example', value: 'client/specimen'},
    {type: 'mdxJsxAttribute', name: 'region', value: 'invoke'},
  ]};
  assert.deepEqual(requestsFromTree(node), [{example: 'client/specimen', region: 'invoke'}]);
  for (const attributes of [[...node.attributes, {type: 'mdxJsxExpressionAttribute', value: '...secret'}],
    [node.attributes[0], node.attributes[0]], [node.attributes[0], {type: 'mdxJsxAttribute', name: 'region', value: {type: 'mdxJsxAttributeValueExpression', value: 'getRegion()'}}]]) {
    assert.throws(() => requestsFromTree({...node, attributes}), /literal/);
  }
});

test('CodeExample receives the exact document version and rejects a mismatched snapshot', t => {
  const f = fixture(t, ['rust']);
  const {bundle} = extractExamples(f.root, f.requests, {...f.identity(), documentVersion: 'alpha.1'});
  const document = () => ({type: 'root', children: [{type: 'mdxJsxFlowElement', name: 'CodeExample', attributes: [
    {type: 'mdxJsxAttribute', name: 'example', value: 'client/specimen'},
    {type: 'mdxJsxAttribute', name: 'region', value: 'invoke'},
  ]}]});
  const tree = document();
  remarkExamples({bundle, documentVersion: 'alpha.1'})(tree);
  assert.deepEqual(tree.children[0].attributes.at(-1), {type: 'mdxJsxAttribute', name: 'documentVersion', value: 'alpha.1'});
  assert.throws(() => remarkExamples({bundle, documentVersion: 'alpha.2'})(document()), /identity/);
  const forged = document();
  forged.children[0].attributes.push({type: 'mdxJsxAttribute', name: 'documentVersion', value: 'development'});
  assert.throws(() => remarkExamples({bundle, documentVersion: 'alpha.1'})(forged), /literal/);
});
