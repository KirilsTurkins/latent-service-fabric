// Finite fixture controls only. V8 and injected errors do not qualify the
// patched SpiderMonkey engine, collector, host admission or signed component.
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';

const [fixture] = process.argv.slice(2);
assert.ok(fixture);
const work = await mkdtemp(join(tmpdir(), 'lsf-combinator-control-'));
try {
  const source = stripTypeScriptTypes(await readFile(fixture, 'utf8'))
    .replace("'./default-client.js'", "'./default-client.mjs'");
  await writeFile(join(work, 'main.mjs'), source);
  await writeFile(join(work, 'default-client.mjs'),
    'export const initialized=true; export const request=()=>{}, requestReady=()=>{}, promiseReady=()=>{}, requestCopyReady=()=>{};\n');
  globalThis.fetch = () => { throw new Error('unexpected-network'); };
  const {api} = await import(pathToFileURL(join(work, 'main.mjs')));
  assert.equal(await api.run(27, ''), 'combinator:retained:3:ordered');

  // An uninstrumented engine accepts all 96 callbacks, so it cannot satisfy
  // the denial/iterator-close vector just by returning the success marker.
  await assert.rejects(api.run(28, ''), /combinator-native-refusal-or-close-missing/);

  const original = Promise.all;
  let mutation = 'valid';
  Promise.all = function(input) {
    const constructor = this, resolve = constructor.resolve;
    let visits = 0;
    constructor.resolve = function(value) {
      const thenable = resolve.call(this, value);
      return {then(accept, reject) {
        if (++visits === 5) throw new Error(mutation === 'wrong-error' ? 'wrong-error' :
          'activation-runtime-promise-native-register-denied:2');
        return thenable.then(accept, reject);
      }};
    };
    if (mutation === 'no-close') {
      const originalInput = input;
      input = {[Symbol.iterator]() {
        const iterator = originalInput[Symbol.iterator]();
        return {next: () => iterator.next(), return: () => ({done: true, value: undefined})};
      }};
    }
    try { return original.call(constructor, input); }
    finally { constructor.resolve = resolve; }
  };
  try {
    assert.equal(await api.run(28, ''), 'combinator:native-refusal:closed:recovered');
    for (mutation of ['wrong-error', 'no-close'])
      await assert.rejects(api.run(28, ''), /combinator-native-refusal-or-close-missing/);
  } finally {
    Promise.all = original;
  }
  console.log('fixture-controls-passed; engine-qualified=false');
} finally {
  await rm(work, {recursive: true, force: true});
}
