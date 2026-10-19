"""Exact generated metadata-wrapper controls; signed qualification is separate."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNativeTaskMetaTests(unittest.TestCase):
    def javascript(self, source):
        node = shutil.which('node')
        parser = os.environ.get('LSF_TYPESCRIPT_ACORN')
        if parser is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
            parser = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND'])/'node_modules/acorn/dist/acorn.mjs')
        if node is None or parser is None:
            self.skipTest('Node and captured Acorn are required for actual generated metadata controls')
        self.assertTrue(Path(parser).is_file())
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\nimport {readFile} from 'node:fs/promises';\nimport {createHash} from 'node:crypto';\n"
        imports += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        imports += f"import {{directIdleTaskSlots,fuseNativeImportAwaits,inlineNativeTaskMeta}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"const prefixMaterial=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_task_state.json').as_uri())}),'utf8'));\n"
        imports += f"const bindingMaterial=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_open_binding.json').as_uri())}),'utf8'));\n"
        imports += "const prefix=prefixMaterial.source,binding=bindingMaterial.source;assert.equal(createHash('sha256').update(prefix).digest('hex'),prefixMaterial.prefixSha256);assert.equal(createHash('sha256').update(binding).digest('hex'),bindingMaterial.sourceSha256);\n"
        imports += "const original=fuseNativeImportAwaits(directIdleTaskSlots(prefix+binding),parse);\n"
        result = subprocess.run([node, '--input-type=module', '-e', imports+source],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_actual_open_success_rejection_and_typed_failure_keep_task_meta_and_cleanup(self):
        self.javascript(r"""
async function execute(source,mode) {
 const events=[],pending=Promise.withResolvers(),reason={owned:true};let allocation=1024,ctx,runtime;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={reserve(...args){events.push(['reserve',...args.slice(0,3)]);return 7;},
  lift(id){events.push(['lift',id]);assert.equal(runtime.meta(),null);if(mode==='lift-failure')throw reason;return 512;},
  finish(id){events.push(['finish',id]);assert.equal(runtime.meta(),null);}};
 const native=(...args)=>{events.push(['native',...args]);assert(runtime.meta()?.taskID);return pending.promise;};
 ctx=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},native,
  null,null,null,null,null,null,null,h=>events.push(['drop',h]),null,null],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:bridge},defineBuiltinModule(){}});
 runtime=vm.runInContext(source+';({invoke:import_latent_http_streaming_0_3_0$open,Upload:import_streaming_0_3_0$Upload,handle:symbolRscHandle,dispose:symbolDispose,meta:()=>CURRENT_TASK_META[1],state:()=>getOrCreateAsyncState(1)});',ctx);
 const input={method:'get',url:'https://fixture.invalid/json',headers:[{name:'x-conformance',value:'owned'}],bodyLength:0n};
 const result=runtime.invoke(input);assert.equal(typeof result.then,'function');
 for(let i=0;i<32&&!events.some(e=>e[0]==='native');i++)await Promise.resolve();
 assert.equal(events.filter(e=>e[0]==='native').length,1);assert(runtime.meta()?.taskID);
 assert.equal(events.some(e=>e[0]==='finish'),false);
 if(mode==='native-failure')pending.reject(reason);
 else {view.setUint8(512,mode==='typed-failure'?1:0);view.setInt32(516,mode==='typed-failure'?12:42,true);pending.resolve(7);}
 if(mode==='success') {const value=await result;assert.equal(Object.getPrototypeOf(value),runtime.Upload.prototype);assert.equal(value[runtime.handle],42);value[runtime.dispose]();}
 else if(mode==='typed-failure')await assert.rejects(result,e=>e.payload.tag==='uncertain');
 else await assert.rejects(result,e=>e===reason);
 assert.equal(runtime.meta(),null);assert.equal(runtime.state().isExclusivelyLocked(),false);
 assert.equal(events.filter(e=>e[0]==='finish').length,1);
 return events;
}
for(const mode of ['success','native-failure','typed-failure','lift-failure']) {
 assert.deepEqual(await execute(original,mode),await execute(inlineNativeTaskMeta(original,parse),mode));
}
""")

    def test_real_contended_metadata_wait_releases_then_relocks_before_native_carrier(self):
        self.javascript(r"""
async function execute(source) {
 const pending=Promise.withResolvers();let calls=0,ctx,runtime,allocation=1024;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={reserve(){return 7;},lift(){assert.equal(runtime.meta(),null);return 512;},finish(){assert.equal(runtime.meta(),null);}};
 ctx=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},()=>{calls++;assert(runtime.state().isExclusivelyLocked());return pending.promise;},...Array(10).fill(null)],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:bridge},defineBuiltinModule(){}});
 runtime=vm.runInContext(source+';({invoke:import_latent_http_streaming_0_3_0$open,meta:()=>CURRENT_TASK_META[1],state:()=>getOrCreateAsyncState(1)});',ctx);
 vm.runInContext('CURRENT_TASK_META[1]={taskID:999,componentIdx:1};',ctx);
 const result=runtime.invoke({method:'get',url:'https://fixture.invalid/json',headers:[],bodyLength:0n});
 for(let i=0;i<32;i++)await Promise.resolve();assert.equal(calls,0);
 vm.runInContext('CURRENT_TASK_META[1]=null;getOrCreateAsyncState(1).exclusiveRelease();',ctx);
 for(let i=0;i<32&&!calls;i++)await Promise.resolve();assert.equal(calls,1);
 view.setUint8(512,0);view.setInt32(516,42,true);pending.resolve(7);await result;
 assert.equal(runtime.meta(),null);assert.equal(runtime.state().isExclusivelyLocked(),false);
}
await execute(original);await execute(inlineNativeTaskMeta(original,parse));
""")

    def test_unknown_wrapper_unfused_calls_and_local_capture_are_refused(self):
        self.javascript(r"""
assert.notEqual(original.replace('return await fn();','return fn();'),original);
assert.notEqual(original.replace('ret =  __lsfImports.lift','ret += __lsfImports.lift'),original);
assert.notEqual(original.replace('fn: () => __lsfAwaitImport(enum1,','fn: () => __lsfAwaitImport(args,'),original);
assert.throws(()=>inlineNativeTaskMeta(original.replace('return await fn();','return fn();'),parse),/task-meta-shape-drift/);
assert.throws(()=>inlineNativeTaskMeta(original.replace('ret =  __lsfImports.lift','ret += __lsfImports.lift'),parse),/task-meta-shape-drift/);
assert.throws(()=>inlineNativeTaskMeta(original.replace('fn: () => __lsfAwaitImport(enum1,','fn: () => __lsfAwaitImport(args,'),parse),/task-meta-shape-drift/);
const extraNativeCall=original.replace('const __lsfImportId =','_withGlobalCurrentTaskMetaAsync({}); const __lsfImportId =');
assert.notEqual(extraNativeCall,original);
assert.throws(()=>inlineNativeTaskMeta(extraNativeCall,parse),/task-meta-shape-drift/);
assert.equal(inlineNativeTaskMeta('export const scalar=42;',parse),'export const scalar=42;');
assert.equal(inlineNativeTaskMeta(prefix,parse),prefix);
assert.throws(()=>inlineNativeTaskMeta('export const __lsfAwaitImport=42;',parse),/task-meta-shape-drift/);
const exportCall=';async function applicationExport(){ return await _withGlobalCurrentTaskMetaAsync({componentIdx:1,taskID:2,fn:()=>42}); }';
assert(inlineNativeTaskMeta(original+exportCall,parse).endsWith(exportCall));
assert.throws(()=>inlineNativeTaskMeta(prefix+binding,parse),/task-meta-shape-drift/);
const next=inlineNativeTaskMeta(original,parse);parse(next,{ecmaVersion:'latest',sourceType:'module'});
assert.equal(next.includes('fn: () => __lsfAwaitImport'),true);
assert.throws(()=>inlineNativeTaskMeta(next,parse),/task-meta-shape-drift/);
""")


if __name__ == '__main__':
    unittest.main()
