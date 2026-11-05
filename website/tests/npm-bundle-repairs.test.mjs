import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {test} from 'node:test';

const website = fileURLToPath(new URL('../', import.meta.url));
const npmRoot = path.join(website, 'toolchain/node_modules/npm');
const npmRequire = createRequire(path.join(npmRoot, 'package.json'));
const moduleRoot = path.join(npmRoot, 'node_modules');
const load = async (name, format, entry) => {
  const file = path.join(moduleRoot, name, 'dist', format, entry);
  return format === 'esm' ? import(pathToFileURL(file)) : npmRequire(file);
};

for (const format of ['commonjs', 'esm']) {
  test(`bounded minimatch expansion in standalone and glob bundle (${format})`, async () => {
    const minimatch = await load('minimatch', format, 'index.js');
    const glob = await load('glob', format, 'index.min.js');
    const pattern = Array(7).fill('**/../a/b').join('/');
    const options = {optimizationLevel: 2, braceExpandMax: 64};
    assert.equal(new minimatch.Minimatch(pattern, options).set.length, 64);
    assert.equal(new glob.Glob(pattern, {...options, cwd: website}).patterns.length, 64);
    const notDeduped = new minimatch.Minimatch('{x,*}/{0..999}', {optimizationLevel: 2});
    assert.equal(notDeduped.set.length, 2000);
    assert.equal(notDeduped.match('x/5'), true);
    assert.equal(notDeduped.match('y/999'), true);
    assert.equal(new glob.Glob('{x,*}/{0..999}', {optimizationLevel: 2, cwd: website}).patterns.length, 2000);
  });
  for (const entry of ['index.js', 'index.min.js']) {
    test(`glob stops traversal after cancellation (${format}, ${entry})`, async () => {
      const glob = await load('glob', format, entry);
      const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lsf-glob-abort-'));
      try {
        for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
          await fsp.mkdir(path.join(directory, `d${i}`, `d${j}`), {recursive: true});
        }
        const ordinary = await glob.glob('**', {cwd: directory, posix: true});
        assert.ok(ordinary.includes('d0/d0'));
        for (const mode of ['async', 'stream', 'sync']) {
          const controller = new AbortController();
          let calls = 0;
          let afterAbort = 0;
          let triggered = false;
          const abort = () => {
            if (!triggered) {
              triggered = true;
              controller.abort(new Error('expected-test-abort'));
            }
          };
          const customFs = {...fs, readdir(target, options, callback) {
            calls++;
            if (controller.signal.aborted) afterAbort++;
            return fs.readdir(target, options, (error, values) => { abort(); callback(error, values); });
          }, readdirSync(target, options) {
            calls++;
            if (controller.signal.aborted) afterAbort++;
            const values = fs.readdirSync(target, options);
            abort();
            return values;
          }};
          const options = {cwd: directory, fs: customFs, signal: controller.signal};
          if (mode === 'sync') {
            assert.throws(() => glob.globSync('**', options), /expected-test-abort/);
          } else if (mode === 'stream') {
            await assert.rejects(new Promise((resolve, reject) => {
              const stream = glob.globStream('**', options);
              stream.on('data', () => {});
              stream.on('end', resolve);
              stream.on('error', reject);
            }), /expected-test-abort/);
          } else {
            await assert.rejects(glob.glob('**', options), /expected-test-abort/);
          }
          await new Promise(resolve => setTimeout(resolve, 100));
          assert.equal(calls, 1, mode);
          assert.equal(afterAbort, 0, mode);
        }
      } finally {
        await fsp.rm(directory, {recursive: true, force: true});
      }
    });
  }
}

test('the original hidden workspace selection remains unchanged', async () => {
  const mapWorkspaces = npmRequire('@npmcli/map-workspaces');
  const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lsf-workspace-selection-'));
  try {
    await fsp.mkdir(path.join(directory, '.a'));
    await fsp.writeFile(path.join(directory, '.a/package.json'), JSON.stringify({name: 'hidden', version: '1.0.0'}));
    const result = await mapWorkspaces({cwd: directory, pkg: {workspaces: ['**/.*']}});
    assert.deepEqual([...result.keys()], []);
  } finally {
    await fsp.rm(directory, {recursive: true, force: true});
  }
});

test('npm pack retains normal ignore-walk behavior', async () => {
  const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lsf-npm-pack-'));
  try {
    await fsp.writeFile(path.join(directory, 'package.json'), JSON.stringify({name: 'lsf-pack-test', version: '1.0.0'}));
    await fsp.writeFile(path.join(directory, '.npmignore'), '*.log\n');
    await fsp.writeFile(path.join(directory, 'index.js'), 'module.exports = 1;\n');
    await fsp.writeFile(path.join(directory, 'debug.log'), 'excluded\n');
    const output = execFileSync(process.execPath, [path.join(npmRoot, 'bin/npm-cli.js'), 'pack', '--dry-run', '--json', '--ignore-scripts'], {
      cwd: directory, encoding: 'utf8', timeout: 30000,
      env: {...process.env, npm_config_userconfig: path.join(directory, 'empty-npmrc'), npm_config_cache: path.join(directory, 'cache')},
    });
    const files = JSON.parse(output)[0].files.map(file => file.path);
    assert.ok(files.includes('index.js'));
    assert.ok(!files.includes('debug.log'));
  } finally {
    await fsp.rm(directory, {recursive: true, force: true});
  }
});
