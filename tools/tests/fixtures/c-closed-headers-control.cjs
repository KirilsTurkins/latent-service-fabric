'use strict';
const fs = require('node:fs');
const moduleBytes = fs.readFileSync(process.argv[2]);
const expected = process.argv[3];
const module_ = new WebAssembly.Module(moduleBytes);
if (WebAssembly.Module.imports(module_).length) throw new Error('unexpected imports');
const instance = new WebAssembly.Instance(module_, {});
try {
  const value = instance.exports.probe();
  if (expected !== 'return' || value !== 7) throw new Error('unexpected probe return');
} catch (error) {
  if (expected !== 'trap' || !(error instanceof WebAssembly.RuntimeError)) throw error;
}
process.stdout.write('PASS closed-headers-' + expected + '\n');