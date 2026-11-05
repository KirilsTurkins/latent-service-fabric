import assert from 'node:assert/strict'
import {cpSync, mkdtempSync, mkdirSync, readFileSync, readdir, rmSync, writeFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {tmpdir} from 'node:os'
import {basename, dirname, join, relative, resolve} from 'node:path'
import {setTimeout as delay} from 'node:timers/promises'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {test} from 'node:test'
import {verify} from './verify-upload-sources.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(root, 'package.json'))

test('both runtime matcher versions bound pattern amplification', async () => {
  for (const base of ['node_modules/minimatch', 'node_modules/glob/node_modules/minimatch']) {
    for (const format of ['commonjs', 'esm']) {
      const file = join(root, base, 'dist', format, 'index.js')
      const m = format === 'esm' ? await import(pathToFileURL(file)) : require(file)
      const value = new m.Minimatch(Array(7).fill('**/../a/b').join('/'), {optimizationLevel: 2, braceExpandMax: 64})
      assert.equal(value.set.length, 64)
      const many = new m.Minimatch('{x,*}/{0..999}', {optimizationLevel: 2})
      assert.equal(many.set.length, 2000)
      assert.equal(many.match('x/5'), true)
      assert.equal(many.match('y/999'), true)
    }
  }
})

test('aborted recursive glob stops issuing directory reads', async () => {
  const scratch = mkdtempSync(join(tmpdir(), 'lsf-upload-glob-'))
  assert.ok(!relative(resolve(tmpdir()), scratch).startsWith('..') && basename(scratch).startsWith('lsf-upload-glob-'))
  try {
    for (let i = 0; i < 12; i++) {
      const dir = join(scratch, `d${i}`, 'nested')
      mkdirSync(dir, {recursive: true})
      writeFileSync(join(dir, 'file.txt'), 'content')
    }
    const controller = new AbortController()
    let reads = 0
    const fs = {readdir(path, opts, cb) {
      reads++
      readdir(path, opts, (error, entries) => {
        if (reads === 1) controller.abort(new Error('cancel-upload-walk'))
        cb(error, entries)
      })
    }}
    const {glob} = await import('glob')
    await assert.rejects(glob('**/*', {cwd: scratch, signal: controller.signal, fs}), /cancel-upload-walk/)
    await delay(100)
    assert.equal(reads, 1, 'aborted walk continued reading directories')
  } finally { rmSync(scratch, {recursive: true, force: true}) }
})

test('source guard rejects lock, archive and installed source drift', () => {
  const scratch = mkdtempSync(join(tmpdir(), 'lsf-upload-sources-'))
  assert.ok(!relative(resolve(tmpdir()), scratch).startsWith('..') && basename(scratch).startsWith('lsf-upload-sources-'))
  try {
    for (const p of ['package.json', 'package-lock.json', '.lsf-source', 'node_modules/glob', 'node_modules/minimatch']) {
      cpSync(join(root, p), join(scratch, p), {recursive: true})
    }
    assert.equal(verify(scratch).packages.length, 3)
    for (const p of ['package-lock.json', '.lsf-source/glob-10.5.0-lsf-abort-v1.tar', 'node_modules/glob/dist/esm/walker.js', 'node_modules/minimatch/dist/commonjs/index.js', 'node_modules/glob/node_modules/minimatch/dist/esm/index.js']) {
      const file = join(scratch, p)
      const original = readFileSync(file)
      writeFileSync(file, Buffer.concat([original, Buffer.from('\ndrift\n')]))
      assert.throws(() => verify(scratch))
      writeFileSync(file, original)
    }
  } finally { rmSync(scratch, {recursive: true, force: true}) }
})
