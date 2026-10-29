import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {dirname, join, resolve} from 'node:path'
import {fileURLToPath} from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = name => readFileSync(join(root, name))
const sha = value => createHash('sha256').update(value).digest('hex')
assert.equal(sha(read('package.json')), '64f50ca0c2e03efe66a47042c2347978b66d64ce3585d0a9f1f3047ac95e1484')
assert.equal(sha(read('package-lock.json')), '150804961399dd5d5689b87aaf7d1f7963dbb14dd4993851ee4a34893d860be3')
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
