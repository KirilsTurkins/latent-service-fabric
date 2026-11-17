const fs = require('node:fs');
const bytes = fs.readFileSync(process.argv[2]);
const module_ = new WebAssembly.Module(bytes);
if (WebAssembly.Module.imports(module_).length) throw Error('unexpected wasm imports');
const instance = new WebAssembly.Instance(module_, {});
if (instance.exports._initialize) instance.exports._initialize();
const result = instance.exports.numeric_resolver_controls();
if (result) throw Error(`numeric resolver control failed at C line ${result}`);
process.stdout.write('PASS numeric_resolver_controls\n');
if (instance.exports.numeric_resolver_allocation_refusal) {
  const refused = instance.exports.numeric_resolver_allocation_refusal();
  if (refused) throw Error(`allocation refusal control failed at C line ${refused}`);
  process.stdout.write('PASS numeric_resolver_allocation_refusal\n');
}
