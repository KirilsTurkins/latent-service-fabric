// Actual compiled adapter with explicit finite host/libc doubles; no provider.
const fs = require('fs');
const module_ = new WebAssembly.Module(fs.readFileSync(process.argv[2]));
if (WebAssembly.Module.imports(module_).length !== 0) throw Error('ambient import');
for (const name of ['stdio_stream_controls', 'stdio_missing_log_authority']) {
  const instance = new WebAssembly.Instance(module_, {});
  const result = instance.exports[name]();
  if (result !== 0) throw Error(`${name}:${result}`);
  console.log(`PASS ${name}`);
}
