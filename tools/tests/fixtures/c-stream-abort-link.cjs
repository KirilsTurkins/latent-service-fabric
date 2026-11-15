const fs = require('node:fs');
WebAssembly.instantiate(fs.readFileSync(process.argv[2]), {}).then(({ instance }) => {
  if (instance.exports.entropy_success() !== 0) throw new Error('libc entropy call count');
  process.stdout.write('PASS libc-entropy\n');
  for (const name of ['application_abort', 'original_libc_abort']) {
    let trapped = false;
    try { instance.exports[name](); }
    catch (error) {
      if (!(error instanceof WebAssembly.RuntimeError)) throw error;
      trapped = true;
    }
    if (!trapped) throw new Error(`${name} returned`);
    process.stdout.write(`PASS ${name}\n`);
  }
}).catch(error => { process.stderr.write(`${error}\n`); process.exitCode = 1; });
