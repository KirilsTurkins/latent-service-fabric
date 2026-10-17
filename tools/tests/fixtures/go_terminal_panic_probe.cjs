// Fixed-memory instruction controls; no component or application executes.
const fs = require('fs');
const path = require('path');
const root = process.argv[2];
const rows = JSON.parse(fs.readFileSync(path.join(root, 'rows.json')));
const bits = rows.length.toString(2).length;
let checks = 0;
function probe(file, text, change) {
  const instance = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(path.join(root, file))));
  const data = new DataView(instance.exports.memory.buffer);
  const memory = new Uint8Array(data.buffer);
  data.setBigUint64(1032, 2048n, true);
  data.setBigUint64(2048, 1280848n, true);
  data.setBigUint64(2056, 4096n, true);
  data.setBigUint64(2064, 0n, true);
  const encoded = Buffer.from(text);
  memory.set(encoded, 8192);
  data.setBigUint64(4096, 8192n, true);
  data.setBigUint64(4104, BigInt(encoded.length), true);
  if (change) change(data);
  try {
    instance.exports.probe(0);
    throw new Error('unexpected-resumption');
  } catch (error) {
    if (!(error instanceof WebAssembly.RuntimeError)) throw error;
    checks++;
    if (error.message.includes('divide by zero')) return 'matched';
    if (error.message.includes('unreachable')) return 'unknown';
    throw error;
  }
}
function equal(actual, expected) {
  if (actual !== expected) throw new Error(`${actual} != ${expected}`);
}
for (const row of rows) {
  for (const digits of ['1', '-1', '18446744073709551615']) {
    const text = row.segments.map(segment => segment.literalHex
      ? Buffer.from(segment.literalHex, 'hex').toString()
      : segment.decimal.signed ? digits : '0').join('');
    for (let bit = 0; bit < bits; bit++) equal(probe(`bit-${bit}.wasm`, text), row.id >> bit & 1 ? 'matched' : 'unknown');
    equal(probe(`confirm-${row.id}.wasm`, text), 'matched');
  }
}
const text = rows[0].segments.map(segment => segment.literalHex
  ? Buffer.from(segment.literalHex, 'hex').toString() : '1').join('');
for (const change of [
  data => data.setBigUint64(1032, 0n, true),
  data => data.setBigUint64(1032, (1n << 32n) + 2048n, true),
  data => data.setBigUint64(1032, 131064n, true),
  data => data.setBigUint64(2048, 9n, true),
  data => data.setBigUint64(2064, 1n, true),
  data => data.setBigUint64(2056, (1n << 32n) + 4096n, true),
  data => data.setBigUint64(2056, 131064n, true),
  data => data.setBigUint64(4104, 257n, true),
  data => data.setBigUint64(4096, (1n << 32n) + 8192n, true),
  data => { data.setBigUint64(4096, 131070n, true); data.setBigUint64(4104, 32n, true); },
]) equal(probe('confirm-1.wasm', text, change), 'unknown');
for (const invalid of ['', 'unknown payload',
  'runtime error: index out of range [a] with length 1',
  'runtime error: index out of range [-] with length 1',
  'runtime error: index out of range [1] with length -1',
  'runtime error: index out of range [111111111111111111111] with length 1',
  'runtime error: index out of range [1] with length 11111111111111111111',
  'runtime error: index out of range [1] with length 1 trailing', 'x'.repeat(257),
]) for (let bit = 0; bit < bits; bit++) equal(probe(`bit-${bit}.wasm`, invalid), 'unknown');
console.log(JSON.stringify({ checks, normalComponentExecuted: false }));
