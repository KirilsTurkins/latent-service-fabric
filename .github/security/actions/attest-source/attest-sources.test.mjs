import assert from 'node:assert/strict'
import {cpSync, mkdtempSync, mkdirSync, readFileSync, readdir, rmSync, writeFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {tmpdir} from 'node:os'
import {basename, dirname, join, relative, resolve} from 'node:path'
import {setTimeout as delay} from 'node:timers/promises'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {test} from 'node:test'
import {verify} from './verify-attest-sources.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(root, 'package.json'))
const inventory = JSON.parse(readFileSync(join(root, '.lsf-source/attest-source-files.json')))
const load = async (target, format, filename = 'index.js') => {
  const file = join(root, target, 'dist', format, filename)
  return format === 'esm' ? import(pathToFileURL(file)) : require(file)
}

function temporary(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  assert.ok(!relative(resolve(tmpdir()), dir).startsWith('..') && basename(dir).startsWith(prefix))
  return dir
}

test('all installed minimatch variants bound expansion in both formats', async () => {
  for (const pkg of inventory.packages.filter(row => row.name === 'minimatch')) for (const target of pkg.targets) {
    for (const format of ['commonjs', 'esm']) {
      const matcher = await load(target, format)
      const capped = new matcher.Minimatch(Array(7).fill('**/../a/b').join('/'), {optimizationLevel: 2, braceExpandMax: 64})
      assert.equal(capped.set.length, 64, `${target} ${format}`)
      const many = new matcher.Minimatch('{x,*}/{0..999}', {optimizationLevel: 2})
      assert.equal(many.set.length, 2000)
      assert.equal(many.match('x/5'), true)
      assert.equal(many.match('y/999'), true)
    }
  }
})

test('glob 13 minified and ordinary exports bound their matcher', async () => {
  const pkg = inventory.packages.find(row => row.name === 'glob' && row.version === '13.0.6')
  for (const target of pkg.targets) for (const format of ['commonjs', 'esm']) for (const file of ['index.js', 'index.min.js']) {
    const glob = await load(target, format, file)
    const value = new glob.Glob(Array(7).fill('**/../a/b').join('/'), {optimizationLevel: 2, braceExpandMax: 64})
    assert.equal(value.patterns.length, 64, `${target} ${format} ${file}`)
  }
})

test('aborted glob walkers stop issuing directory reads across all entrypoints', async () => {
  const scratch = temporary('lsf-attest-glob-')
  try {
    for (let i = 0; i < 10; i++) {
      const dir = join(scratch, `d${i}`, 'nested')
      mkdirSync(dir, {recursive: true})
      writeFileSync(join(dir, 'file.txt'), 'content')
    }
    for (const pkg of inventory.packages.filter(row => row.name === 'glob')) for (const target of pkg.targets) {
      for (const format of ['commonjs', 'esm']) for (const file of pkg.version === '13.0.6' ? ['index.js', 'index.min.js'] : ['index.js']) {
        const controller = new AbortController()
        let reads = 0
        const fs = {readdir(path, opts, cb) {
          reads++
          readdir(path, opts, (error, entries) => {
            if (reads === 1) controller.abort(new Error('cancel-attest-walk'))
            cb(error, entries)
          })
        }}
        const glob = await load(target, format, file)
        await assert.rejects(glob.glob('**/*', {cwd: scratch, signal: controller.signal, fs}), /cancel-attest-walk/)
        await delay(40)
        assert.equal(reads, 1, `${target} ${format} ${file}`)
      }
    }
  } finally { rmSync(scratch, {recursive: true, force: true}) }
})

test('deepmerge drops prototype keys from both input sides', () => {
  const merge = require(join(root, 'node_modules/deepmerge'))
  const bad = JSON.parse('{"__proto__":{"attestPolluted":true},"safe":1}')
  for (const result of [merge(bad, {}), merge({}, bad)]) {
    assert.equal(Object.hasOwn(result, '__proto__'), false)
    assert.equal(Object.getPrototypeOf(result), Object.prototype)
    assert.equal(result.attestPolluted, undefined)
    assert.equal(result.safe, 1)
  }
  assert.equal({}.attestPolluted, undefined)
})

test('guard verifies every copy and refuses tampered source, assets and aliases', () => {
  const scratch = temporary('lsf-attest-sources-')
  try {
    for (const path of ['package.json', 'package-lock.json', '.lsf-source']) cpSync(join(root, path), join(scratch, path), {recursive: true})
    const targets = inventory.packages.flatMap(pkg => pkg.targets).sort((a, b) => a.length - b.length)
    const lock = JSON.parse(readFileSync(join(root, 'package-lock.json')))
    for (const dev of [false, true]) {
      for (const target of targets.filter(path => Boolean(lock.packages[path].dev) === dev)) {
        mkdirSync(dirname(join(scratch, target)), {recursive: true})
        cpSync(join(root, target), join(scratch, target), {recursive: true})
        const parts = target.split('/node_modules/')
        for (let count = 1; count < parts.length; count++) {
          const parent = parts.slice(0, count).join('/node_modules/')
          mkdirSync(join(scratch, parent), {recursive: true})
          cpSync(join(root, parent, 'package.json'), join(scratch, parent, 'package.json'))
        }
      }
      if (!dev) {
        assert.equal(verify(scratch, {allowMissingDev: true}).packages.reduce((total, pkg) => total + pkg.copies, 0), 5)
        assert.throws(() => verify(scratch), /unexpected missing, nested or aliased package/)
      }
    }
    assert.equal(verify(scratch).packages.reduce((total, pkg) => total + pkg.copies, 0), 15)
    const paths = ['package.json', 'package-lock.json', '.lsf-source/attest-source-files.json']
    for (const pkg of inventory.packages) {
      paths.push('.lsf-source/' + pkg.original, '.lsf-source/' + pkg.archive, '.lsf-source/' + pkg.repair)
      for (const target of pkg.targets) {
        paths.push(target + (pkg.name === 'deepmerge' ? '/index.js' : pkg.name === 'glob' ? '/dist/commonjs/walker.js' : '/dist/commonjs/index.js'))
        if (pkg.name === 'glob' && pkg.version === '13.0.6') paths.push(target + '/dist/commonjs/index.min.js', target + '/dist/esm/index.min.js')
      }
    }
    for (const path of paths) {
      const file = join(scratch, path), original = readFileSync(file)
      writeFileSync(file, Buffer.concat([original, Buffer.from('\ndrift\n')]))
      assert.throws(() => verify(scratch), undefined, path)
      writeFileSync(file, original)
    }
    const alias = join(scratch, 'node_modules/lsf-unreviewed-alias')
    mkdirSync(alias, {recursive: true})
    writeFileSync(join(alias, 'package.json'), JSON.stringify({name: 'minimatch', version: '10.2.6'}))
    assert.throws(() => verify(scratch), /unexpected missing, nested or aliased package/)
  } finally { rmSync(scratch, {recursive: true, force: true}) }
})
