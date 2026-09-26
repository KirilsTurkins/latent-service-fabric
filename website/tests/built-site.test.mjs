import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {validatePublicJavaScript} from '../lib/built-site.mjs';
import {repositoryRoot} from '../lib/repository.mjs';

test('real built-bundle hygiene rejects private absolute paths rather than publishing the input index', context => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-public-fixture-'));
  context.after(() => {
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, {recursive: true});
  });
  fs.mkdirSync(path.join(root, 'assets/js'), {recursive: true});
  const target = path.join(root, 'assets/js/main.js');
  fs.writeFileSync(target, 'window.fixture = true;');
  assert.deepEqual(validatePublicJavaScript(root), {files: 1, bytes: 22});
  fs.writeFileSync(target, `window.fixture = ${JSON.stringify({privateRoot: repositoryRoot})};`);
  assert.throws(() => validatePublicJavaScript(root), /Private build path leaked/);
});
