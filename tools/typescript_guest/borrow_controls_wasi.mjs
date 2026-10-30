// Standalone real-SpiderMonkey diagnostic only. Canonical/broker intrinsics
// are compiled fixture doubles; this is not signed Component Model execution.
import {createReadStream} from 'node:fs';
import {WASI} from 'node:wasi';

const [path, control, ...extra] = process.argv.slice(2);
if (!path || !control || extra.length || !/^[a-zA-Z0-9-]{1,96}$/.test(control)) {
  throw new Error('borrow-control-invocation-invalid');
}
const chunks = [];
let size = 0;
for await (const chunk of createReadStream(path, {highWaterMark: 65536})) {
  size += chunk.length;
  if (size > 64 * 1024 * 1024) throw new Error('borrow-control-core-bound');
  chunks.push(chunk);
}
const bytes = Buffer.concat(chunks, size);
const module = await WebAssembly.compile(bytes);
if (WebAssembly.Module.imports(module).some(row => row.module !== 'wasi_snapshot_preview1')) {
  throw new Error('borrow-control-unexpected-native-import');
}
const wasi = new WASI({version: 'preview1', args: [path, control], env: {}, preopens: {}, returnOnExit: true});
const instance = await WebAssembly.instantiate(module, wasi.getImportObject());
const status = wasi.start(instance);
if (status !== 0) process.exitCode = status;
