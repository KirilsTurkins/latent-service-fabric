// Owned compiler reference, not a sandbox for untrusted code or an LSF host.
import { readFile } from 'node:fs/promises';
import { WASI } from 'node:wasi';

if (process.version !== 'v24.19.0' || process.argv.length !== 3) {
  throw new Error('closed-network-reference-tool-identity');
}
const bytes = await readFile(process.argv[2]);
if (bytes.byteLength > 16 * 1024 * 1024) {
  throw new Error('closed-network-reference-module-bound');
}
const wasi = new WASI({ version: 'preview1', args: ['owned-network-reference'],
  env: {}, preopens: {}, returnOnExit: true });
const module = await WebAssembly.compile(bytes);
const instance = await WebAssembly.instantiate(module, wasi.getImportObject());
const code = wasi.start(instance);
if (code !== 0) throw new Error('closed-network-reference-nonzero-exit');
