// Execute real generated C allocation/root/post-return core bodies only.
// No canonical child, production host, or ordinary-thread pass is modeled.
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const [corePath, receiptPath] = process.argv.slice(2);
const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
assert.equal(receipt.schemaVersion, 'latent.c.canonical-abi-source.v1');
assert.equal(receipt.canonicalComponentAuthenticated, false);
assert.equal(receipt.runtimeProfileQualified, false);
const wasmModule = new WebAssembly.Module(fs.readFileSync(corePath));
const ROOT = 'examples:threading/api@1.0.0#greet';
function fresh() {
  let context = 0, lookups = 0, hostCalls = 0;
  const blocked = () => { hostCalls++; throw new Error('unexpected-host-or-thread-call'); };
  const imports = {};
  for (const item of WebAssembly.Module.imports(wasmModule)) {
    assert.equal(item.kind, 'function');
    imports[item.module] ??= {};
    imports[item.module][item.name] = blocked;
  }
  Object.assign(imports.$root, {
    '[context-get-1]': () => { lookups++; return context; },
    '[context-set-1]': value => { context = value; },
    '[thread-index]': () => 0,
  });
  const e = new WebAssembly.Instance(wasmModule, imports).exports;
  assert.equal(e.memory.buffer instanceof SharedArrayBuffer, false);
  return {e, context: () => context, lookups: () => lookups, hostCalls: () => hostCalls};
}
const f = fresh(), e = f.e;
assert.throws(() => e.cabi_realloc(0, 0, 1, 7), WebAssembly.RuntimeError,
              'lowering before the original initializer is closed');
const earlyRoot = fresh();
assert.throws(() => earlyRoot.e[ROOT](0, 0), WebAssembly.RuntimeError,
              'ordinary C cannot run before original initialization');
// A core trap does not implement component Store lockdown. Each negative
// below therefore uses its own instance, never borrowing a trapped success.
const selected = fresh(), out = selected.e;
out._initialize();
assert.equal(selected.context(), 0);
assert.equal(selected.lookups(), 0, 'initializer cannot consult canonical context');
const input = new TextEncoder().encode('unknown');
const pointer = out.cabi_realloc(0, 0, 1, input.length);
new Uint8Array(out.memory.buffer).set(input, pointer);
assert.equal(selected.lookups(), 0, 'pre-entry allocation remains System-only');
const ret = out[ROOT](pointer, input.length);
assert.equal(selected.context(), 0, 'root detached after normal generated result');
const words = new DataView(out.memory.buffer);
assert.equal(words.getUint8(ret), 1, 'ordinary C false is the WIT Err variant');
const resultPointer = words.getUint32(ret + 4, true);
const resultLength = words.getUint32(ret + 8, true);
assert.equal(new TextDecoder('utf-8', {fatal: true}).decode(
  new Uint8Array(out.memory.buffer, resultPointer, resultLength)), 'unknown-thread-kind');
const afterRoot = selected.lookups();
assert.ok(afterRoot > 0, 'the C root actually used the checked private context');
out['cabi_post_' + ROOT](ret);
assert.equal(selected.lookups(), afterRoot, 'post-return cannot borrow detached context');
assert.equal(selected.context(), 0);
assert.equal(selected.hostCalls(), 0, 'no inline worker or provider callback substitute');
assert.throws(() => out['cabi_post_' + ROOT](ret), WebAssembly.RuntimeError);

const twice = fresh(); twice.e._initialize();
assert.throws(() => twice.e._initialize(), WebAssembly.RuntimeError);
const earlyPost = fresh(); earlyPost.e._initialize();
assert.throws(() => earlyPost.e['cabi_post_' + ROOT](0), WebAssembly.RuntimeError);
const oom = fresh(); oom.e._initialize();
assert.throws(() => oom.e.cabi_realloc(0, 0, 1, 4 * 1024 * 1024), WebAssembly.RuntimeError);
assert.equal(oom.context(), 0);
assert.equal(oom.lookups(), 0, 'real allocation-failure closure remains System-only');
assert.equal(oom.hostCalls(), 0, 'OOM/abort does not call a host or thread fallback');
console.log(JSON.stringify({schemaVersion: 'latent.c.canonical-abi-core-control.v1',
  status: 'passed', actualGeneratedCAbiExecuted: true, originalInitializerPreserved: true,
  loweringBeforeRoot: true, ordinaryResultErr: true, postReturnAfterDetach: true,
  oomRefusedInsideOriginalMemory: true, negativeControls: 6,
  canonicalChildCreated: false, nativeRuntimeExecuted: false, pthreadProfileQualified: false}));
