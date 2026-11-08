// Serialized source controls only; no actual guest, engine, or host ledger.
'use strict';
const fs = require('node:fs');
const bytes = fs.readFileSync(process.argv[2]);
const module_ = new WebAssembly.Module(bytes);
const imports = WebAssembly.Module.imports(module_);
if (imports.length) throw new Error(`Unexpected imports: ${JSON.stringify(imports)}`);
const exports_ = new WebAssembly.Instance(module_, {}).exports;
const cases = ['mutex_fast', 'mutex_expired', 'mutex_invalid', 'condition_expired',
  'condition_invalid', 'future_relative', 'future_overflow', 'clock_failure',
  'c11_expired', 'duration_boundaries'];
let failed = 0;
for (const name of cases) {
  const result = exports_[name]();
  if (result) { console.log(`FAIL ${name} C line ${result}`); ++failed; }
  else console.log(`PASS ${name}`);
}
process.exitCode = failed ? 1 : 0;
