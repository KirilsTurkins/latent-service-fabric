import assert from 'node:assert/strict'
import {cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {tmpdir} from 'node:os'
import {basename, dirname, join, relative, resolve} from 'node:path'
import {test} from 'node:test'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {verify} from './verify-installed-minimatch.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(root, 'package.json'))

test('bounded matcher retains glob compatibility in both entry points', async () => {
  for (const format of ['commonjs', 'esm']) {
    const file = join(root, 'node_modules/minimatch/dist', format, 'index.js')
    const m = format === 'esm' ? await import(pathToFileURL(file)) : require(file)
    const matcher = new m.Minimatch(Array(7).fill('**/../a/b').join('/'), {optimizationLevel: 2, braceExpandMax: 64})
    assert.equal(matcher.set.length, 64)
    assert.equal(typeof matcher.matchOne, 'function')
    const many = new m.Minimatch('{x,*}/{0..999}', {optimizationLevel: 2})
    assert.equal(many.set.length, 2000)
    assert.equal(many.match('x/5'), true)
    assert.equal(many.match('y/999'), true)
  }
})

test('installed source verifier rejects lock, archive and installed-file drift', () => {
  const scratch = mkdtempSync(join(tmpdir(), 'lsf-minimatch-source-'))
  const inner = relative(resolve(tmpdir()), resolve(scratch))
  assert.ok(inner && !inner.startsWith('..') && basename(scratch).startsWith('lsf-minimatch-source-'))
  try {
    for (const path of ['package.json', 'package-lock.json', '.lsf-source', 'node_modules/minimatch']) {
      const target = join(scratch, path)
      cpSync(join(root, path), target, {recursive: true})
    }
    assert.equal(verify(scratch).version, '10.2.6')
    const lockPath = join(scratch, 'package-lock.json')
    const lockRaw = readFileSync(lockPath)
    const lock = JSON.parse(lockRaw)
    lock.packages['node_modules/untrusted/node_modules/minimatch'] = {...lock.packages['node_modules/minimatch'], resolved: 'https://registry.npmjs.org/minimatch/-/minimatch-10.2.6.tgz'}
    writeFileSync(lockPath, JSON.stringify(lock))
    assert.throws(() => verify(scratch))
    writeFileSync(lockPath, lockRaw)
    const installed = join(scratch, 'node_modules/minimatch/dist/esm/index.js')
    const original = readFileSync(installed)
    writeFileSync(installed, Buffer.concat([original, Buffer.from('\n// drift\n')]))
    assert.throws(() => verify(scratch))
    writeFileSync(installed, original)
    const archive = join(scratch, '.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar')
    writeFileSync(archive, 'drift')
    assert.throws(() => verify(scratch))
  } finally {
    if (existsSync(scratch)) rmSync(scratch, {recursive: true, force: true})
  }
})
