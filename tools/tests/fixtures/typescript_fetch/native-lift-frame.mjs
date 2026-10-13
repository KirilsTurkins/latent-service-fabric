import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {liftNativeImportInMetadataFrame} from './async_waiters.mjs';

const source = `
import assert from 'node:assert/strict';
let metadata = null;
const order = [];
let native;
let liftError;
const __lsfImports = {lift(id) {order.push('lift');assert.equal(metadata, 17);if(liftError)throw liftError;return id+1;},
 finish() {order.push('finish');assert.equal(metadata,null);}};
function $native(id) {assert.equal(id,17);order.push('native');return native.promise;}
async function _withGlobalCurrentTaskMetaAsync(args) {
  const {fn} = args;
  try {metadata = 17;
    return await fn();
  } finally {order.push('metadata-cleared');metadata = null;}
}
async function _clearCurrentTask() {}
async function imported() {
 const __lsfImportId = 17;
 try {
  const __lsfAwaitImport = async (...lowered) => __lsfImports.lift(await $native(__lsfImportId | 0, ...lowered));
  return await _withGlobalCurrentTaskMetaAsync({
    fn: () => __lsfAwaitImport(42),
  });
 } finally {__lsfImports.finish();}
}
export function begin(error) {native=Promise.withResolvers();liftError=error;order.length=0;return imported();}
export function resolve(value) {native.resolve(value);}
export function reject(value) {native.reject(value);}
export function observed() {return {order:[...order],metadata};}
export async function ordinary(fn) {return _withGlobalCurrentTaskMetaAsync({fn});}
`;
const projected = liftNativeImportInMetadataFrame(source);
await writeFile(new URL('./projected.mjs', import.meta.url), projected);
const module = await import('./projected.mjs');
let settled = false;
const pending = module.begin().then(value => {settled=true;return value;});
assert.deepEqual(module.observed(), {order:['native'],metadata:17});
await Promise.resolve();
assert.equal(settled,false);
module.resolve(41);
assert.equal(await pending,42);
assert.deepEqual(module.observed(), {order:['native','lift','metadata-cleared','finish'],metadata:null});
const reason = {original:'reject'};
const rejected = module.begin();module.reject(reason);
await assert.rejects(rejected, error=>error===reason);
assert.deepEqual(module.observed(), {order:['native','metadata-cleared','finish'],metadata:null});
const liftReason = {original:'lift'};
const failedLift=module.begin(liftReason);module.resolve(41);
await assert.rejects(failedLift,error=>error===liftReason);
assert.deepEqual(module.observed(), {order:['native','lift','metadata-cleared','finish'],metadata:null});
assert.equal(await module.ordinary(()=>Promise.resolve(19)),19);
let gets = 0;
const ordinaryProxy = new Proxy(()=>23, {get(){gets++;throw new Error('ordinary-property-read');}});
assert.equal(await module.ordinary(ordinaryProxy),23);
assert.equal(gets,0);
await assert.rejects(module.ordinary(()=>Promise.reject(reason)),error=>error===reason);
assert.throws(()=>liftNativeImportInMetadataFrame(source+source),/metadata-source-shape/);
assert.throws(()=>liftNativeImportInMetadataFrame(source.replace('fn: () => __lsfAwaitImport(42),','fn: () => 42,')),/lift-binding-shape/);
assert.throws(()=>liftNativeImportInMetadataFrame(projected),/await-shape|trampoline-shape/);
