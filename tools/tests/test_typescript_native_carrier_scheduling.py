"""Captured compiler-source controls; models do not prove native retirement."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNativeCarrierSchedulingTests(unittest.TestCase):
    def javascript(self, source):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required for captured compiler-source controls')
        parser = os.environ.get('LSF_TYPESCRIPT_ACORN')
        if parser is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
            parser = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND']) / 'node_modules/acorn/dist/acorn.mjs')
        prelude = "import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';import {createHash} from 'node:crypto';\n"
        if parser:
            self.assertTrue(Path(parser).is_file())
            prelude += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            # Host-only mechanism evidence, never a production parser fallback.
            prelude += "const scope={};vm.runInNewContext(process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'],scope);const {parse}=scope.acorn;\n"
        prelude += f"import {{directIdleTaskSlots,fuseNativeImportAwaits,nativeCarrierImports}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        for variable, name, digest in [('prefix', 'typescript_native_task_state.json', 'prefixSha256'),
                                       ('binding', 'typescript_native_open_binding.json', 'sourceSha256')]:
            prelude += f"const {variable}Material=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures'/name).as_uri())}),'utf8'));assert.equal(createHash('sha256').update({variable}Material.source).digest('hex'),{variable}Material.{digest});\n"
        prelude += "const prefix=prefixMaterial.source;const binding=bindingMaterial.source.replace('\\n  try {','\\n  /* lsf-owned-result-transfer:wit-result */\\n  try {');const original=fuseNativeImportAwaits(directIdleTaskSlots(prefix+binding),parse);const selected=nativeCarrierImports(original,parse);\n"
        result = subprocess.run([node, '--input-type=module', '-e', prelude + source],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_namespace_sibling_starts_while_first_native_carrier_is_pending(self):
        self.javascript(r"""
async function execute(source,projected) {
 const pending=[Promise.withResolvers(),Promise.withResolvers()],events=[];let allocation=1024,runtime,next=0;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={beginOwnPlans(...v){assert.deepEqual(v,[2,0,0]);},reserve(){return ++next;},delivered(_id,value){return value;},
  lift(id){events.push(['lift',id]);return 512+id*16;},finish(id){events.push(['finish',id]);}};
 const native=id=>{events.push(['native',id]);return pending[id-1].promise;};
 const context=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},native,...Array(10).fill(null)],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:bridge},defineBuiltinModule(){}});
 runtime=vm.runInContext(source+';({invoke:import_latent_http_streaming_0_3_0$open,meta:()=>CURRENT_TASK_META[1],tasks:()=>ASYNC_TASKS_BY_COMPONENT_IDX.get(1)});',context);
 const input={method:'get',url:'https://fixture.invalid/',headers:[],bodyLength:0n};
 const first=runtime.invoke(input);const sibling=runtime.invoke(input);
 for(let i=0;i<32;i++)await Promise.resolve();
 assert.deepEqual(events.filter(e=>e[0]==='native').map(e=>e[1]),projected?[1,2]:[1]);
 assert.equal(events.some(e=>e[0]==='finish'),false);
 if(projected){assert.equal(runtime.meta(),undefined);assert.equal(runtime.tasks(),undefined);}
 for(let id=1;id<=2;id++){
  view.setUint8(512+id*16,0);view.setInt32(516+id*16,40+id,true);pending[id-1].resolve(id);
  await (id===1?first:sibling);
 }
 assert.deepEqual(events.filter(e=>e[0]==='finish').map(e=>e[1]),[1,2]);
}
await execute(original,false);await execute(selected,true);
""")

    def test_typed_values_errors_cancellation_lift_and_start_failure_keep_finally(self):
        self.javascript(r"""
async function execute(mode) {
 const events=[],pending=Promise.withResolvers(),reason={original:mode};let allocation=1024;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={beginOwnPlans(...v){assert.deepEqual(v,[2,0,0]);},reserve(){events.push('reserve');return 7;},delivered(id,value){assert.equal(id,7);events.push('delivered');return value;},
  lift(id){assert.equal(id,7);events.push('lift');if(mode==='lift-failure')throw reason;return 512;},finish(id){assert.equal(id,7);events.push('finish');}};
 const native=id=>{assert.equal(id,7);events.push('native');if(mode==='start-failure')throw reason;return pending.promise;};
 const context=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},native,...Array(10).fill(null)],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:bridge},defineBuiltinModule(){}});
 const runtime=vm.runInContext(selected+';({invoke:import_latent_http_streaming_0_3_0$open,Upload:import_streaming_0_3_0$Upload,handle:symbolRscHandle});',context);
 const result=runtime.invoke({method:'get',url:'https://fixture.invalid/',headers:[],bodyLength:0n});
 assert.equal(typeof result.then,'function');assert.deepEqual(events,['reserve','native',...(mode==='start-failure'?['finish']:[])]);
 if(mode==='native-rejection'||mode==='cancellation')pending.reject(reason);
 else if(mode!=='start-failure'){view.setUint8(512,mode==='wit-error'?1:0);view.setInt32(516,mode==='wit-error'?12:42,true);pending.resolve(7);}
 if(mode==='success'){const value=await result;assert.equal(Object.getPrototypeOf(value),runtime.Upload.prototype);assert.equal(value[runtime.handle],42);}
 else if(mode==='wit-error')await assert.rejects(result,error=>error.payload.tag==='uncertain');
 else await assert.rejects(result,error=>error===reason);
 assert.equal(events.filter(e=>e==='finish').length,1);
 assert.equal(events.filter(e=>e==='delivered').length,['success','wit-error'].includes(mode)?1:0);
}
for(const mode of ['success','wit-error','native-rejection','cancellation','lift-failure','start-failure'])await execute(mode);
""")

    def test_default_other_wrappers_and_ambient_metadata_are_unchanged(self):
        self.javascript(r"""
assert.equal(nativeCarrierImports('export const scalar=42;',parse),'export const scalar=42;');
assert.equal(nativeCarrierImports(prefix,parse),prefix);
const other=';async function ordinaryExport(){return await _withGlobalCurrentTaskMetaAsync({taskID:2,componentIdx:1,fn:()=>42});}';
assert(nativeCarrierImports(original+other,parse).endsWith(other));
const fn=parse(selected,{ecmaVersion:'latest',sourceType:'module'}).body.find(n=>n.type==='FunctionDeclaration'&&n.id.name==='import_latent_http_streaming_0_3_0$open');
const body=selected.slice(fn.start,fn.end);
for(const name of ['createNewCurrentTask','task.enter','task.exit','CURRENT_TASK_META','_withGlobalCurrentTaskMetaAsync'])assert(!body.includes(name));
assert(body.includes('finally { __lsfImports.finish(__lsfImportId); }'));
assert.equal((body.match(/__lsfImports.delivered\(/g)||[]).length,2);
const pending=Promise.withResolvers(),ambient={taskID:999,componentIdx:1};let runtime,allocation=1024;
const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
function unchanged(){assert.equal(runtime.meta(),ambient);assert.equal(runtime.state().isExclusivelyLocked(),true);}
const bridge={beginOwnPlans(...v){assert.deepEqual(v,[2,0,0]);},reserve(){return 7;},delivered(_id,value){return value;},lift(){unchanged();return 512;},finish(){unchanged();}};
const context=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},()=>{unchanged();return pending.promise;},...Array(10).fill(null)],
 contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:bridge},defineBuiltinModule(){},ambient});
runtime=vm.runInContext(selected+';CURRENT_TASK_META[1]=ambient;getOrCreateAsyncState(1).exclusiveLock();({invoke:import_latent_http_streaming_0_3_0$open,meta:()=>CURRENT_TASK_META[1],state:()=>getOrCreateAsyncState(1)});',context);
const result=runtime.invoke({method:'get',url:'https://fixture.invalid/',headers:[],bodyLength:0n});unchanged();
view.setUint8(512,0);view.setInt32(516,42,true);pending.resolve(7);await result;unchanged();
""")

    def test_new_task_borrow_callback_postreturn_and_reachable_helper_duties_refuse(self):
        self.javascript(r"""
for(const [before,after] of [
 ['isManualAsync: true','isManualAsync: false'],
 ['getCallbackFn: () => null','getCallbackFn: () => (()=>42)'],
 ['if (null!== null)','if (1!== null)'],
 ['task.resolve([retCopy.val]);','task.resolve([retCopy.val]);task.borrowedHandles++;'],
 ['var val1 = v0_0;','getCurrentTask(1);var val1 = v0_0;'],
 ['var val1 = v0_0;','postReturnFn();var val1 = v0_0;'],
 ['var val1 = v0_0;','__carrierTypedHelper();var val1 = v0_0;'],
 ['var val1 = v0_0;','__carrierAliasedHelper();var val1 = v0_0;'],
 ['var val1 = v0_0;','__carrierTable.get();var val1 = v0_0;']]){
 const changed=original.replace(before,after);assert.notEqual(changed,original);
 const helper=after.includes('__carrierTypedHelper')?'\nfunction __carrierTypedHelper(){return getCurrentTask(1);}':
  after.includes('__carrierAliasedHelper')?'\nconst __carrierAlias=getCurrentTask;function __carrierAliasedHelper(){return __carrierAlias(1);}':
  after.includes('__carrierTable')?'\nclass __CarrierTable {get(){return getCurrentTask(1);}}const __carrierTable=new __CarrierTable();':'';
 assert.throws(()=>nativeCarrierImports(changed+helper,parse),/shape-drift/);
}
assert.throws(()=>nativeCarrierImports(selected,parse),/shape-drift/);
const fakeAnchor=original.replace('const __lsfImports = contentGlobal.__lsfAsyncImportBridge;',
 '// const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\nconst __lsfImports=otherBridge;');
assert.throws(()=>nativeCarrierImports(fakeAnchor,parse),/shape-drift/);
""")


if __name__ == '__main__':
    unittest.main()
