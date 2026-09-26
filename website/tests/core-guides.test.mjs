import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import sidebars from '../sidebars.ts';
import {prepare} from '../lib/prepare.mjs';
import {repositoryRoot} from '../lib/repository.mjs';
import {buildSidebars} from '../lib/navigation.mjs';

const flatten = entries => entries.flatMap(entry => entry.type === 'category' ? flatten(entry.items) : [entry]);

test('Start leads to packaged application development and retains the source-node path', () => {
  assert.equal(sidebars.start[0].label, 'Your first application');
  assert.deepEqual(flatten(sidebars.start).slice(0, 4).map(item => item.id),
    ['start/index', 'start/application-development', 'start/developer-setup', 'start/development-workspace']);
  const expected = {
    start: ['start/index', 'start/application-development', 'start/developer-setup', 'start/first-node'],
    learn: ['learn/author-your-first-capsule', 'learn/deliver-and-recover-a-capsule'],
    howTo: ['how-to/operate-and-contribute'],
  };
  for (const [group, ids] of Object.entries(expected)) {
    for (const id of ids) {
      assert.ok(flatten(sidebars[group]).some(item => item.type === 'doc' && item.id === id), id);
      assert.ok(!flatten(sidebars.understand).some(item => item.type === 'doc' && item.id === id), id);
    }
  }
});

test('task subsections preserve every current document once and separate compiler references', () => {
  const pages = prepare().index.pages.filter(page => page.source.startsWith('docs/'));
  const navigation = buildSidebars(pages);
  const actual = Object.values(navigation).flatMap(flatten).filter(item => item.type === 'doc').map(item => item.id);
  assert.equal(new Set(actual).size, actual.length);
  assert.deepEqual([...actual].sort(), pages.map(page => page.id).sort());
  for (const group of ['start', 'learn', 'howTo', 'reference', 'understand', 'contribute']) {
    assert.ok(navigation[group].some(item => item.type === 'category'), group);
  }
  const profiles = navigation.reference.find(item => item.label === 'Capsule language profiles');
  assert.equal(profiles.collapsed, true);
  assert.deepEqual(profiles.items.map(item => item.id), ['rust', 'c', 'typescript', 'go', 'java', 'dotnet']
    .map(language => `component-development/${language}-authoring`));
  assert.ok(flatten(navigation.learn).every(item => !item.id?.endsWith('-authoring')));
  assert.ok(!actual.some(id => /(?:windows-application|linux-workspace|packaged-languages)$/.test(id)));
});

test('core guide coverage resolves actual source-backed published routes', () => {
  const index = prepare().index;
  const rows = JSON.parse(fs.readFileSync(path.join(repositoryRoot, 'website/content/coverage.json'), 'utf8')).rows.filter(row => row.guideIssue === 357);
  assert.equal(rows.length, 6);
  for (const row of rows) {
    const guides = row.pages.filter(page => page.role === 'guide');
    assert.ok(guides.length > 0, row.id);
    for (const guide of guides) assert.ok(index.pages.some(page => page.source === guide.path), guide.path);
  }
  assert.equal(index.pages.find(page => page.source === 'docs/start/index.md').route, '/docs/start/');
});
