import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {lstatSync, readFileSync, readdirSync} from 'node:fs'
import {dirname, join, resolve} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const hash = b => createHash('sha256').update(b).digest('hex')
const manifestHash = '8ecad9f742c58b6fb49ea17c0d5dcc90e5be3b9d7a6f3c5eaa6349f5e2c89f66'
const lockHash = '9fc87ce6c1e741a1745b5f1d633cc7f5d9cf44e598f99beed75a542a273b1621'

export function verify(root = defaultRoot) {
  const read = path => readFileSync(join(root, path))
  const lockRaw = read('package-lock.json')
  assert.equal(hash(lockRaw), lockHash, 'dependency lock drift')
  const owner = JSON.parse(read('package.json'))
  assert.equal(owner.dependencies.minimatch, 'file:.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar')
  assert.equal(owner.devDependencies.glob, 'file:.lsf-source/glob-10.5.0-lsf-abort-v1.tar')
  assert.equal(owner.overrides['minimatch@10'], '$minimatch')
  assert.deepEqual(owner.overrides['glob@10'], {'.': '$glob', minimatch: 'file:../../.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar'})
  assert.deepEqual(owner.overrides['@typescript-eslint/typescript-estree'], {minimatch: 'file:../../../.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar'})
  for (const script of ['build', 'release']) {
    assert.ok(owner.scripts[script].startsWith('node .lsf-source/verify-installed-deepmerge.mjs && node .lsf-source/verify-download-sources.mjs && '))
  }
  const manifestRaw = read('.lsf-source/download-source-files.json')
  assert.equal(hash(manifestRaw), manifestHash, 'source manifest drift')
  const manifest = JSON.parse(manifestRaw)
  assert.equal(manifest.schema, 1)
  assert.equal(manifest.packages.length, 4)
  const lock = JSON.parse(lockRaw)
  const result = []
  for (const pkg of manifest.packages) {
    for (const [path, expected] of [[pkg.archive, pkg.archiveSha256], [pkg.original, pkg.originalSha256], [pkg.repair, pkg.repairSha256]]) {
      assert.equal(hash(read('.lsf-source/' + path)), expected, 'source asset drift')
    }
    const entry = lock.packages[pkg.target]
    assert.equal(entry.version, pkg.version)
    assert.equal(entry.resolved, 'file:.lsf-source/' + pkg.archive)
    const installed = join(root, pkg.target)
    assert.equal(JSON.parse(readFileSync(join(installed, 'package.json'))).version, pkg.version)
    const found = {}
    function visit(base, prefix = '') {
      for (const entry of readdirSync(base, {withFileTypes: true})) {
        const rel = prefix ? prefix + '/' + entry.name : entry.name
        if (pkg.name === 'glob' && rel === 'node_modules') continue
        const file = join(base, entry.name)
        assert.ok(!lstatSync(file).isSymbolicLink(), 'source symlink refused')
        if (entry.isDirectory()) visit(file, rel)
        else {
          assert.ok(entry.isFile(), 'non-file package member refused')
          found[rel] = hash(readFileSync(file))
        }
      }
    }
    visit(installed)
    assert.deepEqual(found, pkg.files, 'installed source drift')
    result.push({name: pkg.name, version: pkg.version, files: Object.keys(found).length})
  }
  return {kind: 'installed-download-source-assertion', sourceCommit: process.env.GITHUB_SHA || null,
    node: process.versions.node, lockSha256: hash(lockRaw), packages: result}
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  console.log(JSON.stringify(verify()))
}
