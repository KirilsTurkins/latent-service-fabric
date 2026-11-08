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
  'c11_expired', 'duration_boundaries', 'mutex_next_refused', 'condition_next_refused',
  'sleep_next_refused', 'c11_next_refused', 'c11_condition_next_refused',
  'mutex_notification_during_refusal', 'condition_notification_during_refusal'];
let failed = 0;
for (const name of cases) {
  try {
    const result = exports_[name]();
    if (result) { console.log(`FAIL ${name} C line ${result}`); ++failed; }
    else console.log(`PASS ${name}`);
  } catch (error) {
    console.log(`FAIL ${name} ${error.constructor.name}`); ++failed;
  }
}
for (const name of ['terminal_cancel', 'terminal_deadline', 'terminal_cancel_after_notification',
  'refusal_cancel_before_wake', 'refusal_notification_cancel_before_wake']) {
  try {
    const result = exports_[name]();
    console.log(`FAIL ${name} returned ${result}`); ++failed;
  } catch (error) {
    if (!(error instanceof WebAssembly.RuntimeError)) throw error;
    const state = exports_.terminal_state();
    if (state) { console.log(`FAIL ${name} terminal state C line ${state}`); ++failed; }
    else console.log(`PASS ${name}`);
  }
}
process.exitCode = failed ? 1 : 0;
