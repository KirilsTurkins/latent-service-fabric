import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {dirname, join, resolve} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const expectedLockSha256 = '73ab20e6b215286eaf3c3060dfe66c4e9e426b0533ab907299bf9386aa91022a'
const sha256 = value => createHash('sha256').update(value).digest('hex')
const deepmergeSource = /(?:^|[/\\:])deepmerge(?:[/\\@-]|$)/i
const deepmergeAlias = /^npm:deepmerge(?:@|$)/i

export function verifyDeepmergeGraph(lock) {
  assert.ok(lock && typeof lock.packages === 'object' && lock.packages !== null, 'invalid-lock-packages')
  const matches = []
  for (const [path, row] of Object.entries(lock.packages)) {
    assert.ok(row && typeof row === 'object' && !Array.isArray(row), 'invalid-lock-package')
    const parts = path.split('node_modules/')
    const pathName = parts.length > 1 ? parts.at(-1) : ''
    if (pathName === 'deepmerge' || row.name === 'deepmerge' ||
        (typeof row.resolved === 'string' && deepmergeSource.test(row.resolved))) matches.push(path)
    for (const section of ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']) {
      for (const [name, spec] of Object.entries(row[section] || {})) {
        assert.ok(name === 'deepmerge' || typeof spec !== 'string' || !deepmergeAlias.test(spec),
          'deepmerge-lock-alias')
      }
    }
  }
  assert.deepEqual(matches, ['node_modules/deepmerge'], 'deepmerge-lock-duplicate-or-alias')
}

export function verifyLock(raw) {
  const normalized = raw.toString('utf8').replaceAll('\r\n', '\n')
  const lock = JSON.parse(normalized)
  verifyDeepmergeGraph(lock)
  assert.equal(sha256(Buffer.from(normalized)), expectedLockSha256, 'rust-cache-lock-drift')
  return {kind: 'rust-cache-lock-source-assertion', sourceCommit: process.env.GITHUB_SHA || null,
    lockSha256: expectedLockSha256, deepmergePaths: ['node_modules/deepmerge']}
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  console.log(JSON.stringify(verifyLock(readFileSync(join(root, 'package-lock.json')))))
}
