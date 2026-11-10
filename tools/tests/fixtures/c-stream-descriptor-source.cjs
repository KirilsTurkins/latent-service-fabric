const fs = require('node:fs');

WebAssembly.instantiate(fs.readFileSync(process.argv[2]), {}).then(({ instance }) => {
  for (const name of ['descriptor_controls', 'readiness_controls']) {
    const result = instance.exports[name]();
    if (result !== 0) throw new Error(`${name} failed at source line ${result}`);
    process.stdout.write(`PASS ${name}\n`);
  }
}).catch(error => {
  process.stderr.write(`${error}\n`);
  process.exitCode = 1;
});
