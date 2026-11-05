import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {existsSync, lstatSync, readFileSync, readdirSync} from 'node:fs'
import {dirname, join, relative, resolve} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sha256 = value => createHash('sha256').update(value).digest('hex')
const sha512 = value => 'sha512-' + createHash('sha512').update(value).digest('base64')
const ownerHash = '0aca1ae0279456064de8ff3e61bf8db2921c1aea54b036690a1f752f0d5bf9ee'
const lockHash = '85c2e5de3af4b1539e89d4bab1a7da6962abafa7dc8c87d7852ef690c004f947'
const manifestHash = '2bba9695beb83b99501e6ac6c58c35d6f7079d59740aa11c94996ca912e3c7fd'

export function verify(root = defaultRoot, {allowMissingDev = false} = {}) {
  root = resolve(root)
  const read = path => readFileSync(join(root, path))
  const ownerRaw = read('package.json'), lockRaw = read('package-lock.json')
  const manifestRaw = read('.lsf-source/attest-source-files.json')
  assert.equal(sha256(ownerRaw), ownerHash, 'manifest drift')
  assert.equal(sha256(lockRaw), lockHash, 'lock drift')
  assert.equal(sha256(manifestRaw), manifestHash, 'source inventory drift')
  const owner = JSON.parse(ownerRaw), lock = JSON.parse(lockRaw), manifest = JSON.parse(manifestRaw)
  const command = 'node .lsf-source/verify-attest-sources.mjs'
  assert.equal(owner.scripts.prepare, command + ' --runtime-install')
  for (const script of ['prepackage', 'pretest']) assert.equal(owner.scripts[script], command)
  assert.equal(owner.scripts['test:security-source'], 'node --test .lsf-source/attest-sources.test.mjs')
  assert.equal(manifest.schema, 1)
  assert.deepEqual(manifest.packages.map(p => `${p.name}@${p.version}`).sort(), [
    'deepmerge@4.3.1', 'glob@10.5.0', 'glob@13.0.6', 'minimatch@10.2.5', 'minimatch@10.2.6', 'minimatch@9.0.9'
  ])
  const wanted = new Map(manifest.packages.map(pkg => [`${pkg.name}@${pkg.version}`, pkg.targets.slice().sort()]))
  const installed = new Map([...wanted.keys()].map(key => [key, []]))
  function inspectPackage(dir) {
    const stat = lstatSync(dir)
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), 'linked package refused')
    const meta = JSON.parse(readFileSync(join(dir, 'package.json')))
    const key = `${meta.name}@${meta.version}`
    if (installed.has(key)) installed.get(key).push(relative(root, dir).replaceAll('\\', '/'))
    visitModules(join(dir, 'node_modules'))
  }
  function visitModules(dir) {
    if (!existsSync(dir)) return
    assert.ok(!lstatSync(dir).isSymbolicLink(), 'linked node_modules refused')
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
      if (entry.name.startsWith('.')) continue
      const item = join(dir, entry.name)
      if (entry.name.startsWith('@')) {
        assert.ok(entry.isDirectory() && !entry.isSymbolicLink(), 'linked scope refused')
        for (const scoped of readdirSync(item, {withFileTypes: true})) {
          if (scoped.name.startsWith('.')) continue
          inspectPackage(join(item, scoped.name))
        }
      } else if (entry.isDirectory() || entry.isSymbolicLink()) inspectPackage(item)
    }
  }
  visitModules(join(root, 'node_modules'))
  const results = []
  for (const pkg of manifest.packages) {
    const key = `${pkg.name}@${pkg.version}`
    const actual = installed.get(key).sort(), expected = wanted.get(key)
    const required = expected.filter(target => !allowMissingDev || lock.packages[target].dev !== true)
    assert.ok(actual.every(target => expected.includes(target)) && required.every(target => actual.includes(target)),
      'unexpected missing, nested or aliased package')
    for (const [path, expected] of [[pkg.archive, pkg.archiveSha256], [pkg.original, pkg.originalSha256], [pkg.repair, pkg.repairSha256]]) {
      assert.equal(sha256(read('.lsf-source/' + path)), expected, 'source asset drift')
    }
    assert.equal(sha512(read('.lsf-source/' + pkg.archive)), pkg.archiveIntegrity, 'archive integrity drift')
    const lockTargets = []
    for (const [path, row] of Object.entries(lock.packages)) {
      const leaf = path.includes('node_modules/') ? path.split('node_modules/').at(-1) : ''
      if ((row.name || leaf) === pkg.name && row.version === pkg.version) lockTargets.push(path)
    }
    assert.deepEqual(lockTargets.sort(), wanted.get(key), 'lock package coverage drift')
    for (const target of actual) {
      const entry = lock.packages[target]
      assert.equal(entry.resolved, 'file:.lsf-source/' + pkg.archive)
      assert.equal(entry.integrity, pkg.archiveIntegrity)
      const found = {}
      function visit(base, prefix = '') {
        for (const item of readdirSync(base, {withFileTypes: true})) {
          const rel = prefix ? prefix + '/' + item.name : item.name
          if (rel === 'node_modules') continue
          const file = join(base, item.name), meta = lstatSync(file)
          assert.ok(!meta.isSymbolicLink(), 'linked source refused')
          if (meta.isDirectory()) visit(file, rel)
          else {
            assert.ok(meta.isFile(), 'non-file source refused')
            found[rel] = sha256(readFileSync(file))
          }
        }
      }
      visit(join(root, target))
      assert.deepEqual(found, pkg.files, 'installed source drift')
    }
    results.push({name: pkg.name, version: pkg.version, copies: actual.length, members: Object.keys(pkg.files).length})
  }
  return {kind: 'installed-attest-source-assertion', sourceCommit: process.env.GITHUB_SHA || null,
    node: process.versions.node, lockSha256: sha256(lockRaw), packages: results}
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  assert.ok(process.argv.length === 2 || (process.argv.length === 3 && process.argv[2] === '--runtime-install'), 'unreviewed verifier mode')
  console.log(JSON.stringify(verify(defaultRoot, {allowMissingDev: process.argv[2] === '--runtime-install'})))
}
