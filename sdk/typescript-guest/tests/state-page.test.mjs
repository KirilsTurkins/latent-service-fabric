import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';

const capabilities = new URL('../capabilities/', import.meta.url);
test('state page close preserves its parent on borrow and uncertain destructor', () => {
  const parent = resolve(tmpdir());
  const root = resolve(mkdtempSync(join(parent, 'lsf-state-page-')));
  if (dirname(root) !== parent || !basename(root).startsWith('lsf-state-page-')) throw new Error('invalid-test-directory');
  try {
    for (const name of ['state.ts', 'owner.ts', 'result.ts', 'state-internal.ts']) {
      const source = readFileSync(new URL(name, capabilities), 'utf8')
        .replaceAll("from 'latent:state/key-value@0.2.0'", "from './raw.ts'")
        .replaceAll("from './owner.js'", "from './owner.ts'")
        .replaceAll("from './state-internal.js'", "from './state-internal.ts'")
        .replaceAll("from './result.js'", "from './result.ts'");
      writeFileSync(join(root, name), source);
    }
    writeFileSync(join(root, 'raw.ts'), 'export {};');
    writeFileSync(join(root, 'check.mjs'), `
      import assert from 'node:assert/strict';
      import {Owner} from './owner.ts';
      import {Page} from './state.ts';
      let closed = 0, attempts = 0;
      const view = {guard: f => f(), pageClosed: () => closed++};
      const owner = new Owner({}, () => { attempts++; });
      const page = new Page(owner, view);
      owner.borrow(() => assert.throws(() => page.close(), /owner-closed-or-busy/));
      assert.equal(closed, 0); page.close(); assert.equal(closed, 1); assert.equal(attempts, 1);
      const failed = new Owner({}, () => { throw new Error('uncertain destructor'); });
      const failedPage = new Page(failed, view);
      assert.throws(() => failedPage.close(), /uncertain destructor/);
      assert.throws(() => failedPage.close(), /owner-closed-or-busy/);
      assert.equal(closed, 1);
    `);
    const result = spawnSync(process.execPath, ['--experimental-transform-types', join(root, 'check.mjs')], {encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr);
  } finally { rmSync(root, {recursive: true, force: true}); }
});
