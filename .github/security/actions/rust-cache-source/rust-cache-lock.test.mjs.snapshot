import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {dirname, join, resolve} from 'node:path'
import {test} from 'node:test'
import {fileURLToPath} from 'node:url'
import {verifyDeepmergeGraph, verifyLock} from './verify-rust-cache-lock.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const original = readFileSync(join(root, 'package-lock.json'))
const lock = JSON.parse(original)
const upstream = {
  ...lock.packages['node_modules/deepmerge'],
  resolved: 'https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz',
  integrity: 'sha512-3sUqbMEc77XqpdNO7FRyRog+eW3ph+GYCbj+rK+uYyRMuwsVy0rMiVtPn+QJlKFvWP/1PYpapqYn0Me2knFn+A=='
}

test('reviewed lock and Windows line endings pass the exact graph guard', () => {
  assert.equal(verifyLock(original).deepmergePaths[0], 'node_modules/deepmerge')
  assert.equal(verifyLock(Buffer.from(original.toString('utf8').replaceAll('\n', '\r\n'))).lockSha256,
    '73ab20e6b215286eaf3c3060dfe66c4e9e426b0533ab907299bf9386aa91022a')
})

test('nested, named and resolved aliases cannot pass the graph guard', () => {
  for (const [path, row] of [
    ['node_modules/foreign/node_modules/deepmerge', upstream],
    ['node_modules/alias', {...upstream, name: 'deepmerge'}],
    ['node_modules/alias', {...upstream}]
  ]) {
    const changed = structuredClone(lock)
    changed.packages[path] = row
    assert.throws(() => verifyDeepmergeGraph(changed), /deepmerge-lock-duplicate-or-alias/)
    assert.throws(() => verifyLock(Buffer.from(JSON.stringify(changed))), /deepmerge-lock-duplicate-or-alias/)
  }
  const aliasedDependency = structuredClone(lock)
  aliasedDependency.packages[''].devDependencies.alias = 'npm:deepmerge@4.3.1'
  assert.throws(() => verifyDeepmergeGraph(aliasedDependency), /deepmerge-lock-alias/)
  const missing = structuredClone(lock)
  delete missing.packages['node_modules/deepmerge']
  assert.throws(() => verifyDeepmergeGraph(missing), /deepmerge-lock-duplicate-or-alias/)
})

test('unrelated lock changes and disguised aliases fail the exact lock binding', () => {
  const changed = structuredClone(lock)
  changed.packages['node_modules/example'] = {version: '1.0.0', resolved: 'file:unreviewed.tar'}
  assert.doesNotThrow(() => verifyDeepmergeGraph(changed))
  assert.throws(() => verifyLock(Buffer.from(JSON.stringify(changed))), /rust-cache-lock-drift/)
})
