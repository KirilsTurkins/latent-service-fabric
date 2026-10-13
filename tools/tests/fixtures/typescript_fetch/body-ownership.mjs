// Controlled callback lifetimes exercise SDK source only, never a native receipt.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {BodyState, NativeBodyReader} from './http-body.mjs';
const settled = value => ({result: Promise.resolve(value), retired: Promise.resolve(), cancel() {}});
const deferred = () => Promise.withResolvers();

const events = [];
const chunk = {};
let reads = 0;
const reader = new NativeBodyReader({
  read(maximum) { assert.equal(maximum, 16384); events.push('read'); return settled(reads++ ? undefined : chunk); },
  materialize(value) { assert.equal(value, chunk); events.push('materialize'); return settled(new Uint8Array([1, 2])); },
  dropChunk(value) { assert.equal(value, chunk); events.push('drop-chunk'); },
  dropBody() { events.push('drop-body'); },
});
const body = new BodyState(reader);
assert.equal(body.used, false);
assert.equal(body.stream.locked, false);
await Promise.resolve();
assert.deepEqual(events, []); // No prefetch while no reader requests bytes.
assert.deepEqual(await body.consume(), new Uint8Array([1, 2]));
assert.deepEqual(events, ['read', 'materialize', 'drop-chunk', 'read', 'drop-body']);
await reader.cancel();
assert.equal(events.filter(value => value === 'drop-body').length, 1);
assert.throws(() => new BodyState(reader).clone(), /not-supported/);

const result = deferred();
const retirement = deferred();
const cancelledEvents = [];
const reason = {original: 'abort'};
const pending = new NativeBodyReader({
  read() { return {result: result.promise, retired: retirement.promise,
    cancel(value) { assert.equal(value, reason); cancelledEvents.push('native-cancel'); result.reject(value); }}; },
  materialize() { throw new Error('cancelled-read-cannot-materialize'); },
  dropChunk() { throw new Error('cancelled-read-produced-no-chunk'); },
  dropBody() { cancelledEvents.push('drop-body'); },
});
const pulling = pending.pull();
const originalRejection = assert.rejects(pulling, value => value === reason);
const cancellation = pending.cancel(reason);
assert.equal(pending.cancel(reason), cancellation);
await Promise.resolve();
await Promise.resolve();
assert.deepEqual(cancelledEvents, ['native-cancel']);
retirement.resolve();
await originalRejection;
await cancellation;
assert.deepEqual(cancelledEvents, ['native-cancel', 'drop-body']);

const result2 = deferred();
const retirement2 = deferred();
const materializeEvents = [];
const duringMaterialization = new NativeBodyReader({
  read() { return settled(chunk); },
  materialize() { materializeEvents.push('materialize'); return {result: result2.promise,
    retired: retirement2.promise, cancel() { materializeEvents.push('native-cancel'); result2.reject(reason); }}; },
  dropChunk() { materializeEvents.push('drop-chunk'); },
  dropBody() { materializeEvents.push('drop-body'); },
});
const materializing = duringMaterialization.pull();
const materializingRejection = assert.rejects(materializing, value => value === reason);
while (!materializeEvents.length) await Promise.resolve();
const close = duringMaterialization.cancel(reason);
await Promise.resolve();
assert.deepEqual(materializeEvents, ['materialize', 'native-cancel']);
retirement2.resolve();
await materializingRejection;
await close;
assert.deepEqual(materializeEvents, ['materialize', 'native-cancel', 'drop-chunk', 'drop-body']);

const primary = {original: 'read-failure'};
const cleanup = {original: 'retirement-failure'};
let unsafeDrops = 0;
const unretired = new NativeBodyReader({
  read() { return {result: Promise.reject(primary), retired: Promise.reject(cleanup), cancel() {}}; },
  materialize() { throw new Error('failed-read-cannot-materialize'); },
  dropChunk() { unsafeDrops++; }, dropBody() { unsafeDrops++; },
});
await assert.rejects(unretired.pull(), value => value === primary);
assert.equal(unretired.cleanupFailure, cleanup);
assert.equal(unsafeDrops, 0); // Failed acknowledgement permits no canonical drop.
await assert.rejects(unretired.cancel(primary));
assert.equal(unretired.cleanupFailure, cleanup); // A later close refusal retains the original cleanup cause.
assert.equal(unsafeDrops, 0);
const dropFailure = {original: 'drop-failure'};
const failedDrop = new NativeBodyReader({
  read() { return settled(chunk); }, materialize() { return settled(new Uint8Array([1])); },
  dropChunk() { throw dropFailure; }, dropBody() {},
});
await assert.rejects(failedDrop.pull(), value => value === dropFailure);
assert.equal(failedDrop.cleanupFailure, dropFailure);

let falseFailureDrops = 0;
const falseFailure = new NativeBodyReader({
  read() { return {result: Promise.reject(0), retired: Promise.resolve(), cancel() {}}; },
  materialize() { throw new Error('failed-read-cannot-materialize'); }, dropChunk() {},
  dropBody() { falseFailureDrops++; throw undefined; },
});
await assert.rejects(falseFailure.pull(), value => value === 0);
await assert.rejects(falseFailure.cancel());
assert.equal(falseFailureDrops, 1); // A failed destruction is retained, never silently retried.

const foreignBytes = vm.runInNewContext('new Uint8Array([7,8])');
assert.equal(foreignBytes instanceof Uint8Array, false);
const foreign = new NativeBodyReader({
  read() { return settled(chunk); }, materialize() { return settled(foreignBytes); },
  dropChunk() {}, dropBody() {},
});
const copied = await foreign.pull();
assert.deepEqual(copied, new Uint8Array([7,8]));
assert.equal(copied instanceof Uint8Array, true);
await foreign.cancel();
