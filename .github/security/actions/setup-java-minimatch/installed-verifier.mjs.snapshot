import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {dirname, join, resolve} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'

const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const archive = 'file:.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar'
const archiveIntegrity = 'sha512-d4q29f9UKl/jVXZqsE8JNas2oBfjjDeYRQEzYfbPFlEOx3cNnrJzyS48JO1wCCqcRAjOnDnkQfCKcCXFAyuLow=='
const upstreamIntegrity = 'sha512-vpLQEs+VLCr1nU0BXS07maYoFwlDAH0gngQuuttxIwutDFEMHq2blX+8vpgxDdK3J1PwjCJiep77OitTZ4Ll1A=='
const sha = value => createHash('sha256').update(value).digest('hex')
const integrity = value => 'sha512-' + createHash('sha512').update(value).digest('base64')

export function verify(root = sourceRoot) {
  const read = name => readFileSync(join(root, name))
  const tar = read('.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar')
  assert.equal(sha(tar), 'bb2b80a4759baaee01d49528b2d7d0c05fc29c1cf0d3fea41ec243de04bceedb')
  assert.equal(integrity(tar), archiveIntegrity)
  assert.equal(integrity(read('.lsf-source/minimatch-10.2.6.original.tgz')), upstreamIntegrity)
  const repairRaw = read('.lsf-source/minimatch-10.2.6-lsf-bound-v1.repair.json')
  assert.equal(sha(repairRaw), 'd6ede52113aa8cb2d4b6ee008885fd2de0d37e06d822e444846f6f905f088bf3')
  const repair = JSON.parse(repairRaw)
  assert.equal(repair.profile, 'minimatch-10.2.6-lsf-bounds-v1')
  assert.equal(repair.upstreamIntegrity, upstreamIntegrity)
  assert.deepEqual(repair.files.map(row => row.path).sort(), ['dist/commonjs/index.js', 'dist/esm/index.js'])
  const owner = JSON.parse(read('package.json'))
  const lock = JSON.parse(read('package-lock.json'))
  assert.equal(owner.devDependencies.minimatch, archive)
  assert.equal(owner.overrides['minimatch@10'], '$minimatch')
  assert.equal(lock.packages[''].devDependencies.minimatch, archive)
  const rows = Object.entries(lock.packages).filter(([name, row]) => {
    const selected = row.name || name.split('node_modules/').at(-1)
    return selected === 'minimatch' && /^10\./.test(row.version || '')
  })
  assert.deepEqual(rows.map(([name]) => name), ['node_modules/minimatch'])
  const selected = rows[0][1]
  assert.equal(selected.version, '10.2.6')
  assert.equal(selected.resolved, archive)
  assert.equal(selected.integrity, archiveIntegrity)
  const require = createRequire(join(root, 'package.json'))
  const installed = dirname(require.resolve('minimatch/package.json'))
  const manifest = readFileSync(join(installed, 'package.json'))
  assert.equal(sha(manifest), 'bb847ba240909c9a36d4eaeb4e0efdc3e31182aeef208c1611259a48f282ea75')
  assert.equal(sha(readFileSync(join(installed, 'LICENSE.md'))), '2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901')
  const actual = {}
  for (const row of repair.files) {
    actual[row.path] = sha(readFileSync(join(installed, row.path)))
    assert.equal(actual[row.path], row.afterSha256)
  }
  return {kind: 'installed-minimatch-source-assertion', sourceCommit: process.env.GITHUB_SHA || null,
    node: process.versions.node, version: selected.version, repairSha256: sha(repairRaw), installedPostimages: actual}
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  console.log(JSON.stringify(verify()))
}
