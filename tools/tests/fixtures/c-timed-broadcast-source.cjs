// Serialized source interleaving, with explicit canonical/broker doubles.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const bytes = fs.readFileSync(process.argv[2]);
assert(bytes.length <= 1024 * 1024);
const module_ = new WebAssembly.Module(bytes);
const descriptors = WebAssembly.Module.imports(module_);
const allowed = new Set([
  'latent:runtime/activation@0.1.0.timer-stop',
  '$root.[thread-resume-later]',
]);
for (const item of descriptors) {
  assert.equal(item.kind, 'function');
  assert(allowed.has(item.module + '.' + item.name));
}
let instance;
let stops = 0;
const imports = {
  'latent:runtime/activation@0.1.0': {
    'timer-stop': (generation, id, result) => {
      assert.equal(generation, 1n);
      assert.equal(id, 11n);
      assert.equal(++stops, 1);
      // Reenter exactly where the real C contract permits timer-stop to await.
      instance.exports.test_interleave();
      new DataView(instance.exports.memory.buffer).setUint8(result, 0);
    },
  },
  '$root': {'[thread-resume-later]': () => { throw new Error('unexpected canonical wake'); }},
};
instance = new WebAssembly.Instance(module_, imports);
assert.equal(instance.exports.test_start(), 1);
assert.equal(stops, 1);
process.stdout.write('PASS timed-broadcast-expiry-reclaim-new-wave\n');
