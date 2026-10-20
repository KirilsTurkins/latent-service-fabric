// Actual core-Wasm/compiler control. No canonical thread or native host executes.
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const [originalPath, derivedPath, receiptPath] = process.argv.slice(2);
const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
assert.equal(receipt.runtimeProfileQualified, false);
const source = fs.readFileSync(originalPath), derived = fs.readFileSync(derivedPath);
function fixture(raw) {
  let context = 256, e;
  const rows = [];
  const instance = new WebAssembly.Instance(new WebAssembly.Module(raw), {
    '$root': {'[context-get-1]': () => context},
    control: {pause(value, stack, tls) {
      const words = new Uint32Array(e.memory.buffer);
      const c = context / 4;
      assert.ok(stack >= words[c + 1] && stack + 64 <= words[c + 2], 'stack outside selected owner');
      assert.ok(tls >= words[c + 3] && tls + 4 <= words[c + 3] + words[c + 4], 'TLS outside selected owner');
      const snapshot = Array.from(words.slice(stack / 4, stack / 4 + 16));
      assert.deepEqual(snapshot, Array.from({length:16}, (_,i) => value + i));
      rows.push({context, value, stack, tls, counter:words[tls / 4]});
      if (context === 256 && value === 1 && rows.length === 1) {
        context = 320;
        assert.equal(e.probe(2), 28, 'independent child TLS');
        context = 256;
        assert.deepEqual(Array.from(words.slice(stack / 4, stack / 4 + 16)), snapshot, 'root frame survives callback');
        assert.equal(words[tls / 4], 8, 'root TLS survives callback');
      }
    }}
  });
  e = instance.exports;
  assert.equal(e.memory.buffer instanceof SharedArrayBuffer, false);
  if (e.memory.buffer.byteLength < 262144) e.memory.grow(4 - e.memory.buffer.byteLength / 65536);
  const start = receipt.templateStart, size = receipt.templateExtentUpperBound;
  assert.ok(size > 0 && size <= 1024 * 1024);
  const bytes = new Uint8Array(e.memory.buffer), template = bytes.slice(start,start+size);
  assert.equal(template.length, size);
  for (const [ptr, low, high, tls] of [[256,4096,65536,131072],[320,69632,131072,196608]]) {
    bytes.set(template,tls);
    new Uint32Array(e.memory.buffer).set([high,low,high,tls,size,2,0,0],ptr/4);
  }
  return {e, rows, setContext(value) { context = value; }};
}
assert.throws(() => { const f = fixture(source); f.e.probe(1); }, /TLS outside selected owner/,
  'original compiler output must fail the context-isolation control');
const f = fixture(derived);
assert.equal(f.e.probe(1),25);
assert.equal(f.e.probe(1),26);
f.setContext(320); assert.equal(f.e.probe(2),30);
assert.equal(f.rows.length,4);
for (const [name, mutate] of [
  ['no-context', f => f.setContext(0)],
  ['unaligned-context', f => f.setContext(257)],
  ['non-running-context', f => new Uint32Array(f.e.memory.buffer)[256/4+5]=1],
  ['invalid-stack-pointer', f => new Uint32Array(f.e.memory.buffer)[256/4]=2048],
  ['short-TLS-record', f => new Uint32Array(f.e.memory.buffer)[256/4+4]=0],
  ['out-of-memory-TLS', f => new Uint32Array(f.e.memory.buffer)[256/4+3]=0xfffffff0]
]) {
  const fresh = fixture(derived); mutate(fresh);
  assert.throws(() => fresh.e.probe(1), WebAssembly.RuntimeError, name);
}
process.stdout.write(JSON.stringify({schemaVersion:'latent.c.context-compiler-control.v1',
  status:'passed', originalControlRejected:true, actualCompiledCoreExecuted:true,
  callbackReentrancyControl:true, records:f.rows, negativeControls:6,
  canonicalChildCreated:false, nativeRuntimeExecuted:false, pthreadProfileQualified:false})+'\n');
