// Pinned libc linkage and actual selected C bodies only; no runtime qualification.
'use strict';
const fs = require('node:fs');
const module_ = new WebAssembly.Module(fs.readFileSync(process.argv[2]));
if (WebAssembly.Module.imports(module_).length) throw new Error('unexpected imports');
const core = new WebAssembly.Instance(module_, {}).exports;
const expected = core.expected();
if (expected <= 0 || core.try_join() !== expected || core.timed_join() !== expected)
  throw new Error('unsupported GNU joins did not preserve output and refuse');
console.log('PASS pinned libc GNU joins: explicit refusal, unchanged outputs');
