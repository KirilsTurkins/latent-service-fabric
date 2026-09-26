import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {createProcessors, getProcessor} from '@docusaurus/mdx-loader/lib/processor.js';
import {websiteRoot} from '../lib/repository.mjs';

const options = {
  siteDir: websiteRoot,
  staticDirs: [],
  removeContentTitle: false,
  markdownConfig: {
    format: 'detect',
    anchors: {maintainCase: false},
    emoji: false,
    mermaid: true,
    mdx1Compat: {comments: false},
    hooks: {onBrokenMarkdownLinks: 'throw', onBrokenMarkdownImages: 'throw'},
  },
};
options.processors = await createProcessors({options});

test('the pinned Docusaurus compiler actually selects CommonMark for .md and preserves repository constructs', async () => {
  const filePath = path.join(websiteRoot, 'tests/fixtures/commonmark.md');
  const processor = await getProcessor({filePath, mdxFrontMatter: {}, options});
  assert.equal(processor, options.processors.mdProcessor);
  const result = await processor.process({content: fs.readFileSync(filePath, 'utf8'), filePath, frontMatter: {}, compilerName: 'server'});
  for (const expected of ['notJavaScript', 'Über 東京', 'table', 'summary', 'details', 'mermaid']) assert.ok(result.content.includes(expected), expected);
  assert.match(result.content, /Literal \{notJavaScript\}/);
});

test('the same pinned compiler selects reviewed interactive MDX, not prose mode', async () => {
  const filePath = path.join(websiteRoot, 'tests/fixtures/interactive.mdx');
  const processor = await getProcessor({filePath, mdxFrontMatter: {}, options});
  assert.equal(processor, options.processors.mdxProcessor);
  const result = await processor.process({content: fs.readFileSync(filePath, 'utf8'), filePath, frontMatter: {}, compilerName: 'server'});
  assert.match(result.content, /2 \+ 3/);
  assert.match(result.content, /data-fixture/);
});
