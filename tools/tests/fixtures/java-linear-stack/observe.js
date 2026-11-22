'use strict';
// Run only explicitly on the two local witness modules, never on a signed guest.
const assert = require('node:assert/strict');
const fs = require('node:fs');

assert.equal(process.argv.length, 4, 'expected baseline.wasm and protected.wasm');
for (const [index, name] of ['baseline', 'protected'].entries()) {
    const bytes = fs.readFileSync(process.argv[index + 2]);
    assert.ok(bytes.length > 0 && bytes.length < 65536, 'bounded witness module');
    const module = new WebAssembly.Module(bytes);
    assert.deepEqual(WebAssembly.Module.imports(module), [], 'no host imports');
    const instance = new WebAssembly.Instance(module);
    const memory = instance.exports.memory;
    const address = instance.exports.marker_address() >>> 0;
    assert.ok(address + 65536 <= memory.buffer.byteLength, 'complete marker region');
    const marker = new Uint8Array(memory.buffer, address, 65536);
    assert.ok(marker.every(value => value === 0), 'initial marker');
    assert.equal(instance.exports.within(), 42, 'in-budget stack execution');
    assert.ok(marker.every(value => value === 0), 'in-budget marker preservation');
    if (name === 'protected') {
        assert.throws(() => instance.exports.exhaust(), WebAssembly.RuntimeError);
        assert.ok(marker.every(value => value === 0), 'overflow must not reach static data');
    } else {
        assert.equal(instance.exports.exhaust(), 124, 'baseline silently overruns its stack');
        assert.ok(marker.some(value => value !== 0), 'baseline must demonstrate corruption');
    }
    console.log(JSON.stringify({name, within: 42, overflow: name === 'protected' ? 'trapped' : 'returned',
        staticBytesChanged: marker.filter(value => value !== 0).length, stackBytes: 65536}));
}
