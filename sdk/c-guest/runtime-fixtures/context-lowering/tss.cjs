'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const [corePath, receiptPath] = process.argv.slice(2);
const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
assert.equal(receipt.runtimeProfileQualified, false);
let context = 256, guest, deletedKey;
const instance = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(corePath)), {
  '$root': {'[context-get-1]': () => context},
  control: {pause(key) {
    deletedKey = key;
    context = 320;
    assert.equal(guest.child(key), 0, 'child has independent initial errno and TLS values');
    context = 256;
  }}
});
guest = instance.exports;
assert.equal(guest.memory.buffer instanceof SharedArrayBuffer, false);
if (guest.memory.buffer.byteLength < 262144) guest.memory.grow(4 - guest.memory.buffer.byteLength / 65536);
const bytes = new Uint8Array(guest.memory.buffer);
const template = bytes.slice(receipt.templateStart, receipt.templateStart + receipt.templateExtentUpperBound);
for (const [ptr, low, high, tls] of [[256,4096,65536,131072],[320,69632,131072,196608]]) {
  bytes.set(template, tls);
  new Uint32Array(guest.memory.buffer).set([high,low,high,tls,template.length,2,0,0],ptr/4);
}
assert.equal(guest.isolate(), 0, 'C11 root value survives child reentry; deletion invokes no destructor and stale keys fail');
context = 320;
assert.equal(guest.child_state(deletedKey), 0, 'deleted key does not expose child stale value');
context = 256;
assert.equal(guest.keys_limit(), 0, 'C11 and pthread share the exact128-key bound; exhaustion/error codes preserve errno');
assert.equal(guest.destructors(0), 0, 'destructor clears before call, permits reinstall and refuses reentry');
assert.equal(guest.destructors(1), 0, 'four-pass exhaustion retains pending values until explicit later cleanup');
context = 320;
assert.equal(guest.destructors(0), 0, 'destructor state belongs to selected context');
process.stdout.write(JSON.stringify({schemaVersion:'latent.c.c11-tss-control.v1',status:'passed',
  actualCompiledCoreExecuted:true,contextErrnoIsolation:true,staleKeyRefusal:true,sharedPthreadKeyLimit:128,
  destructorPassLimit:4,cyclicPendingRetained:true,clearBeforeDestructor:true,reentryRefused:true,
  deleteDoesNotRunDestructor:true,c11ErrorReturns:true,canonicalChildCreated:false,nativeRuntimeExecuted:false,pthreadProfileQualified:false})+'\n');
