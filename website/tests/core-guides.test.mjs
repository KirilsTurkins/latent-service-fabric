import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import sidebars from '../sidebars.ts';
import {prepare} from '../lib/prepare.mjs';
import {repositoryRoot} from '../lib/repository.mjs';

test('Start opens the decision page followed by the real first-node path', () => {
  assert.deepEqual(sidebars.start.slice(0, 2).map(item => item.id), ['start/index', 'start/first-node']);
  const expected = {
    start: ['start/index', 'start/first-node'],
    learn: ['learn/author-your-first-capsule', 'learn/deliver-and-recover-a-capsule'],
    howTo: ['how-to/operate-and-contribute'],
  };
  for (const [group, ids] of Object.entries(expected)) {
    for (const id of ids) {
      assert.ok(sidebars[group].some(item => item.type === 'doc' && item.id === id), id);
      assert.ok(!sidebars.understand.some(item => item.type === 'doc' && item.id === id), id);
    }
  }
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
