// This checks the compiled core in V8; it does NOT establish LSF conformance.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

assert.equal(process.argv.length, 4, 'Expected core.wasm and output receipt paths');
const bytes = readFileSync(process.argv[2]);
const started = performance.now();
const module = await WebAssembly.compile(bytes);
const compilationMs = performance.now() - started;
assert.deepEqual(WebAssembly.Module.imports(module), [], 'No fabricated WASI/JS host imports');
const observations = [];
for (let generation = 0; generation < 2; generation++) {
  const instantiation = performance.now();
  const instance = await WebAssembly.instantiate(module, {});
  instance.exports._initialize();
  const initialized = performance.now();
  const run = instance.exports['latent:java-probe/probe@1.0.0#run'];
  const cases = [[0n, -1n], [(1n << 63n) - 1n, -(1n << 63n)],
    [-(1n << 63n), -(1n << 63n)], [-42n, -42n], [42n, -43n]];
  for (const [input, expected] of cases) assert.equal(run(input), expected);
  // Actual arrays, strings and caught exceptions in the compiled Java, not JS substitutes.
  const firstCallMemory = instance.exports.memory.buffer.byteLength;
  for (let i = 0; i < 20000; i++) assert.equal(run(-42n), -42n);
  const repeatedCallMemory = instance.exports.memory.buffer.byteLength;
  assert.ok(repeatedCallMemory <= 64 * 1024 * 1024, 'Declared Wasm maximum');
  observations.push({ generation, instantiationMs: initialized - instantiation,
    javaCallsMs: performance.now() - initialized, cases: cases.length + 20000,
    firstCallLinearBytes: firstCallMemory, repeatedCallLinearBytes: repeatedCallMemory });
}
writeFileSync(process.argv[3], JSON.stringify({ formatVersion: 1,
  qualification: 'not-qualified', executionEngine: `Node ${process.version} / V8 ${process.versions.v8}`,
  lsfExecution: 'not-attempted', coreSha256: createHash('sha256').update(bytes).digest('hex'),
  artifactKind: 'core-module', coreBytes: bytes.length, compilationMs, observations,
  unmeasured: ['LSF startup', 'host exception heap', 'cancellation', 'store-drop reclamation',
    'signed admission', 'typed capability ownership', 'declared WIT errors'] }, null, 2) + '\n');
console.log('Compiled Java core semantics passed; LSF qualification remains required.');
