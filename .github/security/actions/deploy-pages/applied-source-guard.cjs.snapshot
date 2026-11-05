'use strict'

// Keep the installed dependency graph intact while applying the two specific
// upstream fixes. Every package member is checked before any file is written.
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const zlib = require('node:zlib')

const root = path.resolve(__dirname, '..')
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex')
const sha512 = bytes => `sha512-${crypto.createHash('sha512').update(bytes).digest('base64')}`
const pins = {
  'package.json': '1f1ba01a30c2f8aa80e60493e6e154bb59e4ff94b1010371447816f609eac771',
  'package-lock.json': '88d39a5c99be6e0ba2af6cd8ca6535acd4ef645ee297c51735c64078246513fa'
}
const profiles = [
  {
    name: 'glob',
    version: '10.5.0',
    count: 65,
    original: 'glob-10.5.0.original.tgz',
    originalHash: '18b75cb9c66c8c08bab5cacccd09013c31d3182f1e001c19d8815c5bb46e0802',
    integrity: 'sha512-DfXN8DfhJ7NH3Oe7cFmu3NCu1wKbkReJ8TorzSAFbSKrlNaQSKfIzqYqVY8zlbs2NLBbWpRiU52GX2PbaBVNkg==',
    repaired: 'glob-10.5.0-lsf-abort-v1.tar',
    repairedHash: 'b2f6d5fb3bd7b63df8454989bfb9d812a29ea67bbbbe81cc5e0e2c4c32e06d68',
    recipe: 'glob-10.5.0-lsf-abort-v1.repair.json',
    recipeHash: 'beb9c5bed151b7a67f3b7b384e04ae0c01ca52e093795c042b9b3a3542a54e0f',
    targets: ['dist/commonjs/walker.js', 'dist/esm/walker.js'],
    installed: ['node_modules/glob']
  },
  {
    name: 'minimatch',
    version: '9.0.9',
    count: 53,
    original: 'minimatch-9.0.9.original.tgz',
    originalHash: '7d28c9a3ef17ce542093c78ec191481503e2711d29db1bd1522062303ab40478',
    integrity: 'sha512-OBwBN9AL4dqmETlpS2zasx+vTeWclWzkblfZk7KTA5j3jeOONz/tRCnZomUyvNg83wL5Zv9Ss6HMJXAgL8R2Yg==',
    repaired: 'minimatch-9.0.9-lsf-bound-v1.tar',
    repairedHash: '66bcb5a384e44e094efb868280fa4607660da97bbd9d0489eb7cc69eb2da93b2',
    recipe: 'minimatch-9.0.9-lsf-bound-v1.repair.json',
    recipeHash: '67f874fd66ff2bbc9930e5a3529cf15fb7eb9fc15bd7e7d82969c0289b12a207',
    targets: ['dist/commonjs/index.js', 'dist/esm/index.js'],
    installed: [
      'node_modules/glob/node_modules/minimatch',
      'node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch'
    ]
  },
  {
    name: 'deepmerge',
    version: '4.3.1',
    count: 11,
    original: 'deepmerge-4.3.1.original.tgz',
    originalHash: '4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c',
    integrity: 'sha512-3sUqbMEc77XqpdNO7FRyRog+eW3ph+GYCbj+rK+uYyRMuwsVy0rMiVtPn+QJlKFvWP/1PYpapqYn0Me2knFn+A==',
    installedIntegrity:
      'sha512-w9M3UphEGYK/Zn9kkYnPVw7NnQyxE3T7gIcqBv3m4/Fe+LAhnAPZBwgYCqj0/orv2GagYhPGa2OMjqdzp7G0Lg==',
    installedResolved: 'file:.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar',
    repaired: 'deepmerge-4.3.1-lsf-prototype-v1.tar',
    repairedHash: 'c4ca0f4eb3a2464c026bc3dec5d9eaf04544aed24c3fd1d77da95f85e36c369f',
    recipe: 'deepmerge-4.3.1-lsf-prototype-v1.repair.json',
    recipeHash: 'e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7',
    targets: ['dist/cjs.js', 'dist/umd.js', 'index.js'],
    installed: ['node_modules/deepmerge'],
    requireRepaired: true
  }
]

function safePath(base, relative, wantDirectory = false) {
  assert.equal(typeof relative, 'string')
  const parts = relative.split('/')
  assert(parts.every(part => part && part !== '.' && part !== '..' && !part.includes('\\')))
  let current = base
  for (const [index, part] of parts.entries()) {
    current = path.join(current, part)
    const stat = fs.lstatSync(current)
    assert(!stat.isSymbolicLink(), `symlink refused: ${relative}`)
    if (index < parts.length - 1 || wantDirectory) assert(stat.isDirectory(), `not a directory: ${relative}`)
    else assert(stat.isFile(), `not a file: ${relative}`)
  }
  return current
}

function readPinned(base, relative, expected) {
  const bytes = fs.readFileSync(safePath(base, relative))
  assert.equal(sha256(bytes), expected, `wrong SHA-256: ${relative}`)
  return bytes
}

// These pinned npm archives contain only regular ustar members with short
// names. Refuse extensions, links, duplicates, overlong inputs and bad sums.
function readTar(bytes, expectedCount) {
  assert(bytes.length <= 2 * 1024 * 1024 && bytes.length % 512 === 0, 'tar size')
  const files = new Map()
  const text = (b, start, end) => b.subarray(start, end).toString('ascii').replace(/\0.*$/, '')
  const octal = s => {
    assert(/^[0-7 ]*$/.test(s))
    return parseInt(s.trim() || '0', 8)
  }
  let offset = 0
  while (offset + 512 <= bytes.length) {
    const header = bytes.subarray(offset, offset + 512)
    if (header.every(byte => byte === 0)) {
      assert(
        bytes.subarray(offset).every(byte => byte === 0),
        'nonzero tar trailer'
      )
      offset = bytes.length
      break
    }
    const stored = octal(text(header, 148, 156))
    let sum = 0
    for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : header[i]
    assert.equal(sum, stored, 'tar checksum')
    const name = text(header, 0, 100)
    assert(name.startsWith('package/') && !name.includes('\\') && !name.split('/').includes('..'))
    assert.equal(text(header, 345, 500), '', 'tar prefix/extension')
    assert(header[156] === 48 || header[156] === 0, 'non-regular tar member')
    const size = octal(text(header, 124, 136))
    const start = offset + 512
    assert(start + size <= bytes.length && size <= 1024 * 1024, 'tar member bounds')
    const member = name.slice('package/'.length)
    assert(member && !files.has(member), `duplicate member: ${member}`)
    files.set(member, bytes.subarray(start, start + size))
    offset = start + Math.ceil(size / 512) * 512
  }
  assert.equal(offset, bytes.length, 'truncated tar')
  assert.equal(files.size, expectedCount, 'tar member count')
  return files
}

function applyEdits(bytes, row) {
  assert.equal(sha256(bytes), row.beforeSha256, `unexpected upstream bytes: ${row.path}`)
  let text = bytes.toString('utf8')
  assert(Buffer.from(text, 'utf8').equals(bytes), 'non-UTF8 repair target')
  for (const edit of row.edits) {
    assert(edit.before && Number.isSafeInteger(edit.count) && edit.count > 0)
    const pieces = text.split(edit.before)
    assert.equal(pieces.length - 1, edit.count, `edit count: ${row.path}`)
    text = pieces.join(edit.after)
  }
  const output = Buffer.from(text, 'utf8')
  assert.equal(sha256(output), row.afterSha256, `unexpected repaired bytes: ${row.path}`)
  return output
}

function installedMembers(base, relative) {
  const result = new Map()
  const walk = member => {
    const dir = member ? `${relative}/${member}` : relative
    for (const entry of fs.readdirSync(safePath(base, dir, true), { withFileTypes: true })) {
      if (!member && entry.name === 'node_modules') continue
      assert(!entry.isSymbolicLink(), `symlink in ${dir}/${entry.name}`)
      const child = member ? `${member}/${entry.name}` : entry.name
      if (entry.isDirectory()) walk(child)
      else {
        assert(entry.isFile(), `non-file in ${dir}/${entry.name}`)
        result.set(child, fs.readFileSync(safePath(base, `${relative}/${child}`)))
      }
    }
  }
  walk('')
  return result
}

function checkAndApply(base = root, apply = true) {
  base = path.resolve(base)
  for (const [name, digest] of Object.entries(pins)) readPinned(base, name, digest)
  readPinned(
    base,
    '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.source.json',
    'b4b0b79fa2bc84c6f1e1c61ddcc1ab228df629f9fce4b1067d3ac8b3d1c42892'
  )
  const lock = JSON.parse(fs.readFileSync(safePath(base, 'package-lock.json')))
  const pending = []
  for (const profile of profiles) {
    const source = readPinned(base, `.lsf-source/${profile.original}`, profile.originalHash)
    assert.equal(sha512(source), profile.integrity, `upstream integrity: ${profile.name}`)
    const packed = readPinned(base, `.lsf-source/${profile.repaired}`, profile.repairedHash)
    const repair = JSON.parse(readPinned(base, `.lsf-source/${profile.recipe}`, profile.recipeHash))
    assert.equal(repair.name, profile.name)
    assert.equal(repair.version, profile.version)
    assert.equal(repair.upstreamIntegrity, profile.integrity)
    assert.deepEqual(repair.files.map(row => row.path).sort(), [...profile.targets].sort())
    const original = readTar(zlib.gunzipSync(source, { maxOutputLength: 2 * 1024 * 1024 }), profile.count)
    const repaired = readTar(packed, profile.count)
    assert.deepEqual([...original.keys()].sort(), [...repaired.keys()].sort(), 'archive members differ')
    const rows = new Map(repair.files.map(row => [row.path, row]))
    for (const [name, bytes] of original) {
      const expected = rows.has(name) ? applyEdits(bytes, rows.get(name)) : bytes
      assert(expected.equals(repaired.get(name)), `reconstruction mismatch: ${profile.name}/${name}`)
    }
    const matching = Object.entries(lock.packages)
      .filter(([name, row]) => name.endsWith(`/${profile.name}`) && row.version === profile.version)
      .map(([name]) => name)
      .sort()
    assert.deepEqual(matching, [...profile.installed].sort(), `lock installations: ${profile.name}`)
    for (const location of profile.installed) {
      assert.equal(
        lock.packages[location].integrity,
        profile.installedIntegrity || profile.integrity,
        `lock integrity: ${location}`
      )
      if (profile.installedResolved)
        assert.equal(lock.packages[location].resolved, profile.installedResolved, `lock resolution: ${location}`)
      const members = installedMembers(base, location)
      assert.deepEqual([...members.keys()].sort(), [...original.keys()].sort(), `installed members: ${location}`)
      for (const [name, actual] of members) {
        const before = original.get(name)
        const after = repaired.get(name)
        assert(
          actual.equals(after) || (!profile.requireRepaired && actual.equals(before)),
          `installed bytes: ${location}/${name}`
        )
        if (!actual.equals(after)) pending.push({ file: safePath(base, `${location}/${name}`), bytes: after })
      }
    }
  }
  const resolution = [
    ['glob', 'node_modules/archiver-utils', 'node_modules/glob/dist/commonjs/index.js'],
    ['minimatch', 'node_modules/glob', 'node_modules/glob/node_modules/minimatch/dist/commonjs/index.js'],
    [
      'minimatch',
      'node_modules/@typescript-eslint/typescript-estree',
      'node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch/dist/commonjs/index.js'
    ]
  ]
  for (const [name, from, expected] of resolution) {
    assert.equal(
      require.resolve(name, { paths: [safePath(base, from, true)] }),
      safePath(base, expected),
      `resolution: ${name} from ${from}`
    )
  }
  if (apply) {
    for (const row of pending) fs.writeFileSync(row.file, row.bytes)
    for (const row of pending) assert(fs.readFileSync(row.file).equals(row.bytes), `write failed: ${row.file}`)
  } else assert.equal(pending.length, 0, 'installed sources are not fully repaired')
  return {
    profiles: profiles.map(row => `${row.name}@${row.version}`),
    changedFiles: pending.length,
    graph: 'unchanged pinned lock'
  }
}

module.exports = { checkAndApply, readTar }
if (require.main === module) console.log(JSON.stringify(checkAndApply()))
