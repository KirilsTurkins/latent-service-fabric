'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const { pathToFileURL } = require('node:url')
const zlib = require('node:zlib')
const { checkAndApply, readTar } = require('./apply-verified-sources.cjs')

const root = path.resolve(__dirname, '..')
const globRoot = path.join(root, 'node_modules/glob')
const minRoot = path.join(globRoot, 'node_modules/minimatch')
const oldGlob = readTar(zlib.gunzipSync(fs.readFileSync(path.join(__dirname, 'glob-10.5.0.original.tgz'))), 65)
const oldMin = readTar(zlib.gunzipSync(fs.readFileSync(path.join(__dirname, 'minimatch-9.0.9.original.tgz'))), 53)
const oldDeep = readTar(zlib.gunzipSync(fs.readFileSync(path.join(__dirname, 'deepmerge-4.3.1.original.tgz'))), 11)

function workspace() {
  const dir = fs.mkdtempSync(path.join(root, '.lsf-test-'))
  assert(path.resolve(dir).startsWith(`${root}${path.sep}`))
  return dir
}
function removeWorkspace(dir) {
  assert(path.resolve(dir).startsWith(`${root}${path.sep}.lsf-test-`))
  fs.rmSync(dir, { recursive: true, force: true })
}
function copy(base, relative, to = relative) {
  const dest = path.join(base, to)
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.cpSync(path.join(root, relative), dest, { recursive: true })
}
function oldModules(base) {
  copy(base, 'node_modules/glob')
  copy(base, 'node_modules/archiver-utils')
  for (const name of ['dist/commonjs/walker.js', 'dist/esm/walker.js'])
    fs.writeFileSync(path.join(base, 'node_modules/glob', name), oldGlob.get(name))
  for (const name of ['dist/commonjs/index.js', 'dist/esm/index.js'])
    fs.writeFileSync(path.join(base, 'node_modules/glob/node_modules/minimatch', name), oldMin.get(name))
  return path.join(base, 'node_modules')
}
function fixture(base) {
  copy(base, '.lsf-source')
  copy(base, 'package.json')
  copy(base, 'package-lock.json')
  copy(base, 'node_modules/glob')
  copy(base, 'node_modules/archiver-utils')
  copy(base, 'node_modules/deepmerge')
  copy(base, 'node_modules/@typescript-eslint/typescript-estree')
}

test('all pinned package members are reconstructed and installed repairs are idempotent', () => {
  assert.equal(checkAndApply(root, false).changedFiles, 0)
  assert.equal(checkAndApply(root).changedFiles, 0)
})

test('source, archive, graph and installed drift refuse before any writes', () => {
  const tmp = workspace()
  try {
    fixture(tmp)
    const globFile = 'node_modules/glob/dist/commonjs/walker.js'
    const minFile = 'node_modules/glob/node_modules/minimatch/dist/esm/index.js'
    const secondMin = 'node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch/dist/commonjs/index.js'
    // Leave a valid preimage pending, so each refusal must happen before mutation.
    fs.writeFileSync(path.join(tmp, globFile), oldGlob.get('dist/commonjs/walker.js'))
    const pendingBefore = fs.readFileSync(path.join(tmp, globFile))
    for (const relative of [
      '.lsf-source/glob-10.5.0.original.tgz',
      '.lsf-source/glob-10.5.0-lsf-abort-v1.tar',
      '.lsf-source/glob-10.5.0-lsf-abort-v1.repair.json',
      '.lsf-source/minimatch-9.0.9.original.tgz',
      '.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar',
      '.lsf-source/minimatch-9.0.9-lsf-bound-v1.repair.json',
      '.lsf-source/deepmerge-4.3.1.original.tgz',
      '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar',
      '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json',
      '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.source.json',
      'package.json',
      'package-lock.json',
      minFile,
      secondMin,
      'node_modules/glob/package.json',
      'node_modules/deepmerge/dist/cjs.js'
    ]) {
      const file = path.join(tmp, relative)
      const original = fs.readFileSync(file)
      fs.writeFileSync(file, Buffer.concat([original, Buffer.from('\nmodified')]))
      assert.throws(() => checkAndApply(tmp), undefined, relative)
      assert(fs.readFileSync(path.join(tmp, globFile)).equals(pendingBefore), `partial write after ${relative}`)
      fs.writeFileSync(file, original)
    }
    const extra = path.join(tmp, 'node_modules/glob/extra.js')
    fs.writeFileSync(extra, 'unexpected')
    assert.throws(() => checkAndApply(tmp))
    assert(fs.readFileSync(path.join(tmp, globFile)).equals(pendingBefore))
    fs.unlinkSync(extra)
    assert.equal(checkAndApply(tmp).changedFiles, 1)
    assert.equal(checkAndApply(tmp, false).changedFiles, 0)
  } finally {
    removeWorkspace(tmp)
  }
})

test('deepmerge preserves normal merges while refusing poisoned source and target prototypes', () => {
  const tmp = workspace()
  try {
    copy(tmp, 'node_modules/deepmerge')
    for (const name of ['index.js', 'dist/cjs.js', 'dist/umd.js'])
      fs.writeFileSync(path.join(tmp, 'node_modules/deepmerge', name), oldDeep.get(name))
    const poison = JSON.parse('{"__proto__":{"poisoned":"yes"},"safe":1}')
    for (const name of ['index.js', 'dist/cjs.js', 'dist/umd.js']) {
      const load = base => {
        const file = path.join(base, 'node_modules/deepmerge', name)
        if (name !== 'index.js') return require(file)
        // The raw source expects an upstream development dependency that is not
        // installed by this action. Use a plain-object fixture for this case;
        // the shipped CJS and UMD entrypoints run their real bundled helper.
        const result = { exports: {} }
        const plainObject = value =>
          value !== null && typeof value === 'object' && !(value instanceof Date) && !(value instanceof RegExp)
        const onlyHelper = request => {
          assert.equal(request, 'is-mergeable-object')
          return plainObject
        }
        new Function('require', 'module', 'exports', fs.readFileSync(file, 'utf8'))(onlyHelper, result, result.exports)
        return result.exports
      }
      const original = load(tmp)
      const fixed = load(root)
      assert.deepEqual(
        fixed({ list: [1], nested: { a: 1 } }, { list: [2], nested: { b: 2 } }),
        original({ list: [1], nested: { a: 1 } }, { list: [2], nested: { b: 2 } })
      )
      assert.equal(original(poison, {}).poisoned, 'yes')
      for (const result of [fixed(poison, {}), fixed({}, poison)]) {
        assert.equal(result.safe, 1)
        assert.equal(result.poisoned, undefined)
        assert.equal(Object.getPrototypeOf(result), Object.prototype)
      }
    }
  } finally {
    removeWorkspace(tmp)
  }
})

function verifyAbortBoundaries(Old, Fixed) {
  for (const [name, next] of [
    ['walkCB', 'walkCB2'],
    ['walkCBSync', 'walkCB2Sync']
  ]) {
    for (const [Ctor, expected] of [
      [Old, 1],
      [Fixed, 0]
    ]) {
      const controller = new AbortController()
      controller.abort(new Error('stop'))
      const walker = new Ctor([], {}, { signal: controller.signal })
      let callbacks = 0
      let followOns = 0
      walker[next] = () => {
        followOns++
      }
      walker[name]({}, [], () => {
        callbacks++
      })
      assert.equal(callbacks, 1, `${name}: callback`)
      assert.equal(followOns, expected, `${name}: after-abort follow-on`)
    }
  }
  for (const name of ['walkCB2', 'walkCB2Sync']) {
    for (const [Ctor, expected] of [
      [Old, 1],
      [Fixed, 0]
    ]) {
      const controller = new AbortController()
      controller.abort(new Error('stop'))
      const walker = new Ctor([], {}, { signal: controller.signal })
      let callbacks = 0
      let processed = 0
      const stop = new Error('processed after abort')
      try {
        walker[name](
          {},
          [],
          {
            processPatterns() {
              processed++
              throw stop
            }
          },
          () => {
            callbacks++
          }
        )
      } catch (e) {
        assert.equal(e, stop)
      }
      assert.equal(callbacks, 1, `${name}: callback`)
      assert.equal(processed, expected, `${name}: after-abort processor`)
    }
  }
  for (const [Ctor, expected] of [
    [Old, 0],
    [Fixed, 1]
  ]) {
    const controller = new AbortController()
    controller.abort()
    const walker = new Ctor([], {}, { signal: controller.signal })
    let called = 0
    walker.onResume(() => {
      called++
    })
    assert.equal(called, expected, 'unpaused callback after abort')
  }
  const controller = new AbortController()
  const paused = new Fixed([], {}, { signal: controller.signal })
  let called = 0
  paused.pause()
  paused.onResume(() => {
    called++
  })
  controller.abort()
  paused.resume()
  assert.equal(called, 0, 'paused work remains canceled after abort')
}

test('four abort returns and resume change have old-versus-fixed causal controls in CJS and ESM', async () => {
  const tmp = workspace()
  try {
    const modules = oldModules(tmp)
    const oldCjs = require(path.join(modules, 'glob/dist/commonjs/walker.js'))
    const newCjs = require(path.join(globRoot, 'dist/commonjs/walker.js'))
    verifyAbortBoundaries(oldCjs.GlobUtil, newCjs.GlobUtil)
    const oldEsm = await import(pathToFileURL(path.join(modules, 'glob/dist/esm/walker.js')).href)
    const newEsm = await import(pathToFileURL(path.join(globRoot, 'dist/esm/walker.js')).href)
    verifyAbortBoundaries(oldEsm.GlobUtil, newEsm.GlobUtil)
  } finally {
    removeWorkspace(tmp)
  }
})

test('minimatch bounds repeated globstar expansion in CJS and ESM', async () => {
  const tmp = workspace()
  try {
    const modules = oldModules(tmp)
    const oldPath = path.join(modules, 'glob/node_modules/minimatch')
    const pairs = [
      [
        require(path.join(oldPath, 'dist/commonjs/index.js')).Minimatch,
        require(path.join(minRoot, 'dist/commonjs/index.js')).Minimatch
      ],
      [
        (await import(pathToFileURL(path.join(oldPath, 'dist/esm/index.js')).href)).Minimatch,
        (await import(pathToFileURL(path.join(minRoot, 'dist/esm/index.js')).href)).Minimatch
      ]
    ]
    const pattern = Array(7).fill('**/../a/b').join('/')
    for (const [Old, Fixed] of pairs) {
      assert.equal(new Old(pattern, { optimizationLevel: 2, braceExpandMax: 64 }).set.length, 128)
      assert.equal(new Fixed(pattern, { optimizationLevel: 2, braceExpandMax: 64 }).set.length, 64)
      const broad = `{${Array.from({ length: 1001 }, (_, i) => `case${i}`).join(',')}}`
      for (const [Ctor, isFixed] of [
        [Old, false],
        [Fixed, true]
      ]) {
        const original = Ctor.prototype.partsMatch
        let comparisons = 0
        Ctor.prototype.partsMatch = function (...args) {
          comparisons++
          return original.apply(this, args)
        }
        try {
          const matcher = new Ctor(broad, { optimizationLevel: 2 })
          assert.equal(matcher.set.length, 1001)
          assert.equal(matcher.match('case500'), true)
          assert.equal(matcher.match('case1001'), false)
          if (isFixed) assert.equal(comparisons, 0)
          else assert(comparisons > 1000, 'baseline must exercise quadratic comparison')
        } finally {
          Ctor.prototype.partsMatch = original
        }
      }
      for (const [pattern, candidate] of [
        ['src/**/*.js', 'src/a/b.js'],
        ['*.{md,txt}', 'README.md'],
        ['a/?/[bc].txt', 'a/z/b.txt'],
        ['**/*.js', 'dir/a.md']
      ]) {
        assert.equal(
          new Fixed(pattern, { optimizationLevel: 2 }).match(candidate),
          new Old(pattern, { optimizationLevel: 2 }).match(candidate)
        )
      }
    }
  } finally {
    removeWorkspace(tmp)
  }
})

async function publicAbort(glob, cwd) {
  const controller = new AbortController()
  const reason = new Error('controlled abort')
  let started = 0
  let afterAbort = 0
  const io = {
    ...fs,
    readdir(...args) {
      if (controller.signal.aborted) afterAbort++
      started++
      const callback = args.pop()
      fs.readdir(...args, (err, entries) => {
        controller.abort(reason)
        setImmediate(() => callback(err, entries))
      })
    }
  }
  const stream = glob.globStream('**/*', { cwd, fs: io, signal: controller.signal })
  const result = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('abort stream timed out')), 2000)
    stream.on('error', error => {
      clearTimeout(timer)
      resolve(error)
    })
    stream.on('end', () => {
      clearTimeout(timer)
      reject(new Error('aborted stream ended successfully'))
    })
    stream.resume()
  })
  assert.equal(await result, reason)
  await new Promise(resolve => setTimeout(resolve, 30))
  assert(started > 0)
  assert.equal(afterAbort, 0)
}

async function publicPausedAbort(glob, cwd) {
  const controller = new AbortController()
  const reason = new Error('controlled paused abort')
  let matches = 0
  const stream = glob.globStream('**/*', { cwd, signal: controller.signal })
  const outcome = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('paused abort timed out')), 2000)
    stream.on('error', error => {
      clearTimeout(timer)
      resolve(error)
    })
    stream.on('end', () => {
      clearTimeout(timer)
      reject(new Error('aborted paused stream ended successfully'))
    })
    stream.on('data', () => {
      matches++
      if (matches === 1) {
        stream.pause()
        controller.abort(reason)
        setImmediate(() => stream.resume())
      }
    })
  })
  assert.equal(await outcome, reason)
  await new Promise(resolve => setTimeout(resolve, 30))
  assert.equal(matches, 1)
}

test('public CJS and ESM streams abort during an outstanding directory read', async () => {
  const tmp = workspace()
  try {
    fs.mkdirSync(path.join(tmp, 'dir'))
    fs.writeFileSync(path.join(tmp, 'dir/a.txt'), 'a')
    const variants = [
      require(path.join(globRoot, 'dist/commonjs/index.js')),
      await import(pathToFileURL(path.join(globRoot, 'dist/esm/index.js')).href)
    ]
    for (const variant of variants) {
      await publicAbort(variant, tmp)
      await publicPausedAbort(variant, tmp)
    }
  } finally {
    removeWorkspace(tmp)
  }
})

function collectZip(files, cwd, useGlob = false) {
  return new Promise((resolve, reject) => {
    const archiver = require('archiver')
    const zip = archiver('zip', { zlib: { level: 0 } })
    const chunks = []
    zip.on('data', chunk => chunks.push(chunk))
    zip.on('error', reject)
    zip.on('warning', reject)
    zip.on('end', () => resolve(Buffer.concat(chunks)))
    const date = new Date('2020-01-02T03:04:06.000Z')
    if (useGlob) zip.glob('**/*', { cwd, nodir: true, dot: true }, { date, mode: 0o644 })
    else for (const name of files) zip.append(fs.readFileSync(path.join(cwd, name)), { name, date, mode: 0o644 })
    zip.finalize().catch(reject)
  })
}
function unzip(bytes) {
  return new Promise((resolve, reject) => {
    const result = {}
    const stream = require('unzip-stream').Parse()
    stream.on('entry', entry => {
      const chunks = []
      entry.on('data', chunk => chunks.push(chunk))
      entry.on('error', reject)
      entry.on('end', () => {
        result[entry.path] = Buffer.concat(chunks).toString('utf8')
      })
    })
    stream.on('error', reject)
    stream.on('close', () => resolve(result))
    stream.end(bytes)
  })
}

test('real archiver-utils expansion and archive content match the original graph', async () => {
  const tmp = workspace()
  try {
    const modules = oldModules(tmp)
    const old = require(path.join(modules, 'archiver-utils')).file
    const fixed = require(path.join(root, 'node_modules/archiver-utils')).file
    const cwd = path.join(tmp, 'files')
    fs.mkdirSync(path.join(cwd, 'nested/space name'), { recursive: true })
    for (const [name, body] of Object.entries({
      'README.md': 'readme',
      'a.txt': 'alpha',
      '.hidden': 'secret',
      'nested/b.txt': 'beta',
      'nested/space name/c.js': 'code'
    }))
      fs.writeFileSync(path.join(cwd, name), body)
    for (const patterns of [
      ['**/*'],
      ['**/*.txt', '!nested/**'],
      ['*.{md,txt}'],
      ['nested/**/*', '!**/*.js'],
      ['missing/**'],
      ['**/*', '!**/*.txt']
    ]) {
      const options = { cwd, dot: true, nodir: true }
      assert.deepEqual(fixed.expand(options, patterns), old.expand(options, patterns), `expand ${patterns}`)
      assert.deepEqual(
        fixed.expandMapping(patterns, 'dest', { ...options, ext: '.out' }),
        old.expandMapping(patterns, 'dest', { ...options, ext: '.out' }),
        `mapping ${patterns}`
      )
    }
    const patterns = ['**/*', '!**/*.js']
    const before = old.expand({ cwd, dot: true, nodir: true }, patterns)
    const after = fixed.expand({ cwd, dot: true, nodir: true }, patterns)
    const oldZip = await collectZip(before, cwd)
    const newZip = await collectZip(after, cwd)
    assert(oldZip.equals(newZip), 'archive bytes differ')
    const expected = { '.hidden': 'secret', 'README.md': 'readme', 'a.txt': 'alpha', 'nested/b.txt': 'beta' }
    assert.deepEqual(await unzip(newZip), expected)
    // archiver.glob uses readdir-glob, a distinct dependency path.
    assert.deepEqual(await unzip(await collectZip([], cwd, true)), { ...expected, 'nested/space name/c.js': 'code' })
  } finally {
    removeWorkspace(tmp)
  }
})
