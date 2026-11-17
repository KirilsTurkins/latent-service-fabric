const fs = require('node:fs');
const module_ = new WebAssembly.Module(fs.readFileSync(process.argv[2]));
if (WebAssembly.Module.imports(module_).length) throw Error('ambient import');
const result = new WebAssembly.Instance(module_, {}).exports.signed_logging_mode_control();
if (result) throw Error(`signed logging fixture failed at C line ${result}`);
console.log('PASS signed logging short-write fixture');
