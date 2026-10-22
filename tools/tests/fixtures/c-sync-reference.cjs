// Execute only the compiled serialized source controls, with explicit test ports.
// No Wasmtime, canonical threads, broker, signing or runtime qualification.
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const bytes = fs.readFileSync(process.argv[2]);
assert(bytes.length > 8 && bytes.length <= 1024 * 1024);
let instance;
let output = '';
const stopped = Symbol('bounded-source-control-exit');
let status;
const imports = {'lsf-source-test': {
  exit(value) { status = value; throw stopped; },
  write(pointer, length) {
    assert(Number.isInteger(pointer) && pointer >= 0);
    assert(Number.isInteger(length) && length >= 0 && length <= 4096);
    const memory = new Uint8Array(instance.exports.memory.buffer);
    assert(pointer <= memory.length - length);
    output += new TextDecoder('utf-8', {fatal: true}).decode(memory.subarray(pointer, pointer + length));
    assert(Buffer.byteLength(output) <= 4096);
  },
}};
instance = new WebAssembly.Instance(new WebAssembly.Module(bytes), imports);
try {
  instance.exports.lsf_test_entry();
  assert.fail('source control entry returned without its explicit exit port');
} catch (error) {
  if (error !== stopped) throw error;
}
process.stdout.write(output);
assert.equal(status, 0, `serialized C source control exit ${status}`);
assert.equal(output, 'PASS:13 serialized production-source cases; no engine/ledger qualification\n');
