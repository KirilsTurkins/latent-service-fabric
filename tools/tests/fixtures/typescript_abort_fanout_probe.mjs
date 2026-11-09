// Probe-assertion controls only. Node has no original-activation owner ledger;
// these injected refusals do not qualify the source-built SpiderMonkey guest.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';

const [fixture, output] = process.argv.slice(2);
for (const name of ['default-client', 'main']) {
  const source = stripTypeScriptTypes(await readFile(`${fixture}/${name}.ts`, 'utf8'));
  await writeFile(`${output}/${name}.mjs`, source.replace("'./default-client.js'", "'./default-client.mjs'"));
}
const {api} = await import(pathToFileURL(`${output}/main.mjs`));
const original = {
  add: EventTarget.prototype.addEventListener,
  remove: EventTarget.prototype.removeEventListener,
  abort: AbortController.prototype.abort,
  resolve: Promise.resolve,
  fetch: globalThis.fetch,
};
const exhausted = 'activation-runtime-promise-native-register-denied:2';
const success = 'abort-fanout:refusal:unchanged:recovered';
let contacts = 0;
globalThis.fetch = () => { ++contacts; throw new Error('unexpected-network'); };

async function exercise(selected, fault) {
  let held = 0, removed = 0, checkpoint = 0, callbacks = 0, root, reason;
  EventTarget.prototype.addEventListener = function(type, callback, ...rest) {
    if (type === 'fanout-fill') {
      if (held === 3 && fault !== 'no-refusal') {
        throw new Error(fault === 'wrong-diagnostic' ? 'private-unexpected-text' : exhausted);
      }
      ++held;
    } else if (type === 'abort' && ++callbacks === 10 && fault === 'lost-callback') {
      return;
    }
    return original.add.call(this, type, callback, ...rest);
  };
  EventTarget.prototype.removeEventListener = function(type, callback, ...rest) {
    if (type === 'fanout-fill') { --held; ++removed; }
    return original.remove.call(this, type, callback, ...rest);
  };
  AbortController.prototype.abort = function(value) {
    if (!this.signal.aborted && held === 3) {
      root = this;
      reason = value;
      if (fault === 'non-atomic') original.abort.call(this, value);
      if (fault === 'missing-abort-refusal') return;
      throw new Error(exhausted);
    }
    if (this === root && !this.signal.aborted && fault === 'retry-refusal') throw new Error(exhausted);
    return original.abort.call(this, value);
  };
  Promise.resolve = function(value) {
    ++checkpoint;
    assert.equal(held, 0, 'fillers must be removed before the normal checkpoint');
    if (fault === 'checkpoint-refusal') throw new Error(exhausted);
    if (fault === 'checkpoint-mutation') original.abort.call(root, reason);
    return original.resolve.call(this, value);
  };
  try {
    const result = await selected.run(28, '');
    assert.equal(held, 0, 'all admitted filler listeners must be removed on every exit');
    assert.equal(removed, fault === 'no-refusal' ? 128 : 3);
    return {result, checkpoint};
  } finally {
    EventTarget.prototype.addEventListener = original.add;
    EventTarget.prototype.removeEventListener = original.remove;
    AbortController.prototype.abort = original.abort;
    Promise.resolve = original.resolve;
  }
}

try {
  assert.equal(await api.run(27, ''), 'abort-fanout:9:ordered');
  const normal = await exercise(api, 'none');
  assert.deepEqual(normal, {result: success, checkpoint: 1});
  const diagnostics = [];
  for (const [fault, expected] of [
    ['no-refusal', 'diagnostic:abort-fanout:refusal:contract'],
    ['wrong-diagnostic', 'diagnostic:abort-fanout:refusal:contract'],
    ['non-atomic', 'diagnostic:abort-fanout:refusal:contract'],
    ['missing-abort-refusal', 'diagnostic:abort-fanout:refusal:contract'],
    ['checkpoint-refusal', 'diagnostic:abort-fanout:checkpoint:native-admission'],
    ['checkpoint-mutation', 'diagnostic:abort-fanout:after-checkpoint:contract'],
    ['retry-refusal', 'diagnostic:abort-fanout:retry:native-admission'],
    ['lost-callback', 'diagnostic:abort-fanout:verification:contract'],
  ]) {
    const observed = await exercise(api, fault);
    assert.equal(observed.result, expected, fault);
    assert.notEqual(observed.result, success);
    diagnostics.push(observed.result);
  }
  // The historical contract could accept a deferred abort performed during the
  // checkpoint: its retry is then a no-op and final event/reason checks pass.
  const source = await readFile(`${output}/main.mjs`, 'utf8');
  const guard = "if (!graph.unchanged()) throw new Error('abort-fanout-checkpoint-mutated-state');";
  assert.equal(source.split(guard).length, 2);
  await writeFile(`${output}/without-checkpoint-guard.mjs`, source.replace(guard, ''));
  const old = (await import(pathToFileURL(`${output}/without-checkpoint-guard.mjs`))).api;
  assert.equal((await exercise(old, 'checkpoint-mutation')).result, success);
  const fresh = (await import(pathToFileURL(`${output}/main.mjs`).href+'?fresh')).api;
  assert.equal(await fresh.run(27, ''), 'abort-fanout:9:ordered');
  // Node's primordial factory is not the selected native factory. Its lack of
  // constructor reentry must remain a failure, never a passing fallback.
  await assert.rejects(api.run(29, ''), /abort-fanout-default-factory-not-reentered/);
  assert.equal(contacts, 0);
  console.log(JSON.stringify({scope: 'probe-assertions-only', diagnostics}));
} finally {
  globalThis.fetch = original.fetch;
}
