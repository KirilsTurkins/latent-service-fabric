import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {dirname, join, resolve} from 'node:path'
import {fileURLToPath} from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = name => readFileSync(join(root, name))
const sha = value => createHash('sha256').update(value).digest('hex')
assert.equal(sha(read('package.json')), '26a03b49371aa7c27d52c9eea23f7735c8f650d27ec57b59a2bb3691dbf9ae55')
assert.equal(sha(read('package-lock.json')), 'b33854c1c407343b348ad2fe92bb089992a4963e53be565e0eb9835a7f813c48')
const repairRaw = read('.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json')
assert.equal(sha(repairRaw), 'e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7')
const repair = JSON.parse(repairRaw)
assert.deepEqual(repair.files.map(row => row.path).sort(), ['dist/cjs.js', 'dist/umd.js', 'index.js'])
const require = createRequire(join(root, 'package.json'))
const installed = dirname(require.resolve('deepmerge/package.json'))
const manifest = JSON.parse(readFileSync(join(installed, 'package.json')))
assert.equal(manifest.name, 'deepmerge')
assert.equal(manifest.version, '4.3.1')
assert.equal(manifest.license, 'MIT')
const actual = {}
for (const row of repair.files) {
  actual[row.path] = sha(readFileSync(join(installed, row.path)))
  assert.equal(actual[row.path], row.afterSha256)
}
console.log(JSON.stringify({
  kind: 'installed-source-assertion',
  sourceCommit: process.env.GITHUB_SHA || null,
  node: process.versions.node,
  packageVersion: manifest.version,
  repairSha256: sha(repairRaw),
  installedPostimages: actual,
  actionBuildOrSignedSDKQualified: false
}))
