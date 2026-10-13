// Controlled generator calls exercise compiler-source capture, not native ABI.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {nativeOperationCapture} from './operation_capture.mjs';
import {fetchOperationBindings} from './fetch_bindings.mjs';
import {applicationRealmImportPromises} from './async_waiters.mjs';
const AppPromise = vm.runInNewContext('Promise');
const retirement = AppPromise.withResolvers();
const result = Promise.withResolvers();
const order = [];
const capture = nativeOperationCapture({
  retired(id) { assert.equal(id, 17); order.push('retirement'); return retirement.promise; },
  cancel(id, retired) { assert.equal(id, 17); assert.equal(retired, retirement.promise); order.push('cancel'); },
}, AppPromise);
const receiver = {};
async function generated(value) {
  assert.equal(this, receiver);
  assert.equal(value, 42);
  order.push('reserve');
  capture.observe(17);
  try {
    order.push('lower');
    return await result.promise;
  } finally { order.push('typed-finish'); }
}
const operation = capture.invoke(generated, receiver, [42]);
assert.deepEqual(order, ['reserve', 'retirement', 'lower']);
assert.equal(operation.result instanceof AppPromise, true);
assert.equal(operation.retired, retirement.promise);
assert.equal(operation.id, 17);
operation.cancel();
assert.equal(order.at(-1), 'cancel');
const reason = {original: 'cancel'};
result.reject(reason);
await assert.rejects(operation.result, value => value === reason);
let retired = false;
operation.retired.then(() => { retired = true; });
await Promise.resolve();
assert.equal(retired, false);
assert.equal(order.at(-1), 'typed-finish');
retirement.resolve(17);
await operation.retired;
assert.equal(retired, true);

let ordinaryRetirements = 0;
const ordinary = nativeOperationCapture({retired() { ordinaryRetirements++; }}, AppPromise);
ordinary.observe(18);
assert.equal(ordinaryRetirements, 0);
const failure = {original: 'pre-admission'};
const missing = ordinary.invoke(async () => { throw failure; }, undefined, []);
await assert.rejects(missing.result, value => value === failure);
await assert.rejects(missing.retired, /capture-missing/);
assert.throws(() => missing.cancel(), /capture-missing/);

const multiple = nativeOperationCapture({retired() { return AppPromise.resolve(); }}, AppPromise);
const conflicting = multiple.invoke(async () => { multiple.observe(1); multiple.observe(2); }, undefined, []);
await assert.rejects(conflicting.result, /not-a-single-operation/);
assert.equal(conflicting.id, 1); // Original accepted operation stays available for cleanup.
assert.throws(() => capture.invoke(null, null, []), TypeError);

// The existing realm adapter invokes the original generated function before
// returning its application Promise; the exact ID observer must run then.
const captureSource = await readFile(new URL('./operation_capture.mjs', import.meta.url), 'utf8');
const original = `
const __lsfImports = contentGlobal.__lsfAsyncImportBridge;
defineBuiltinModule('latent:http/streaming@0.3.0', {
  async read(body, maximum) {
    const id = __lsfImports.reserve(body, maximum);
    try {
      if (typeof __lsfObserveNativeImport === 'function') __lsfObserveNativeImport(id);
      return await __lsfImports.call(id);
    } finally { __lsfImports.finish(id); }
  }
});
`;
const transformed = fetchOperationBindings(applicationRealmImportPromises(original), captureSource);
const registered = [];
const nativeRetirement = AppPromise.withResolvers();
const nativeResult = Promise.withResolvers();
let typedFinished = false;
const contentGlobal = {Promise: AppPromise, __lsfAsyncImportBridge: {
  reserve(body, maximum) { assert.equal(body, 'owned-body'); assert.equal(maximum, 16384); return 23; },
  retired(id) { assert.equal(id, 23); return nativeRetirement.promise; },
  call(id) { assert.equal(id, 23); return nativeResult.promise; },
  finish(id) { assert.equal(id, 23); typedFinished = true; },
  cancel(id, retired) { assert.equal(id, 23); assert.equal(retired, nativeRetirement.promise); },
}};
new Function('contentGlobal', 'defineBuiltinModule', transformed)(contentGlobal,
  (name, module) => registered.push({name, module}));
const bridge = contentGlobal.__lsfSdkFetchBridge;
assert.notEqual(bridge.http, registered[0].module);
const actual = bridge.invoke(bridge.http.read, bridge.http, ['owned-body', 16384]);
assert.equal(actual.id, 23);
assert.equal(actual.retired, nativeRetirement.promise);
assert.equal(actual.result instanceof AppPromise, true);
delete contentGlobal.__lsfSdkFetchBridge; // Startup must consume its private seam.
assert.equal(Object.hasOwn(contentGlobal, '__lsfSdkFetchBridge'), false);
actual.cancel();
nativeResult.resolve('typed-chunk');
assert.equal(await actual.result, 'typed-chunk');
assert.equal(typedFinished, true);
nativeRetirement.resolve(23);
await actual.retired;
assert.throws(() => fetchOperationBindings(original, captureSource), /hook-shape/);
assert.throws(() => fetchOperationBindings(transformed, captureSource + captureSource), /source-shape/);
