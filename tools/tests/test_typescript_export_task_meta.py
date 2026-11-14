"""Actual generated export-frame controls; signed execution is a separate gate."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptExportTaskMetaTests(unittest.TestCase):
    def javascript(self, source):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for generated-binding controls')
        parser = os.environ.get('LSF_TYPESCRIPT_ACORN')
        if parser is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
            parser = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND'])/'node_modules/acorn/dist/acorn.mjs')
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\nimport {readFile} from 'node:fs/promises';\n"
        if parser:
            self.assertTrue(Path(parser).is_file())
            imports += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            imports += "const scope={};vm.runInNewContext(process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'],scope);const {parse}=scope.acorn;\n"
        imports += f"import {{directIdleTaskSlots}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"import {{inlineExportTaskMeta}} from {json.dumps((ROOT/'tools/typescript_guest/source_splicer.mjs').as_uri())};\n"
        imports += f"const prefix=JSON.parse(await readFile({json.dumps(str(ROOT/'tools/tests/fixtures/typescript_native_task_state.json'))},'utf8')).source;\n"
        imports += f"const binding=await readFile({json.dumps(str(ROOT/'tools/tests/fixtures/typescript_fetch_export_binding.js'))},'utf8');\n"
        imports += "const original=directIdleTaskSlots(prefix+binding);\n"
        result = subprocess.run([node, '--input-type=module', '-e', imports+source],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_export_await_preserves_pending_thenables_typed_result_and_error_cleanup(self):
        self.javascript(r'''
async function execute(source, mode, contended=false) {
 const events=[],pending=Promise.withResolvers(),reason=new Error('application-failure');
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 let allocation=1024, runtime, calls=0;
 const ctx=vm.createContext({
  $bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},...Array(11).fill(null)],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:{}},
  api100Run(modeValue,url){
   calls++; events.push('call'); assert.equal(modeValue,42);assert.equal(url,'input');
   assert(runtime.meta()?.taskID);assert.equal(runtime.meta().componentIdx,-1);
   if(mode==='throw')throw reason;
   if(mode==='then-getter-throw')return Object.defineProperty({},'then',{get(){throw reason;}});
   if(mode==='thenable')return {then(resolve){events.push('then');assert(runtime.meta());resolve('result');}};
   if(mode==='value')return 'result';
   return pending.promise;
  },defineBuiltinModule(){}
 });
 runtime=vm.runInContext(source+';({invoke:export_api_1_0_0$run,meta:()=>CURRENT_TASK_META[-1],state:()=>getOrCreateAsyncState(-1),tasks:()=>ASYNC_TASKS_BY_COMPONENT_IDX.get(-1)});',ctx);
 new Uint8Array(memory.buffer,64,5).set(new TextEncoder().encode('input'));
 if(contended)vm.runInContext('CURRENT_TASK_META[-1]={taskID:999,componentIdx:-1};',ctx);
 const result=runtime.invoke(42,64,5,128);
 assert.equal(typeof result.then,'function');assert.equal(calls,0,'entry remains asynchronous');
 const failure=['throw','reject','then-getter-throw'].includes(mode);
 const observed=failure?assert.rejects(result,e=>e===reason):result;
 for(let i=0;i<32&&!calls;i++)await Promise.resolve();
 if(contended){
  assert.equal(calls,0);
  vm.runInContext('CURRENT_TASK_META[-1]=null;getOrCreateAsyncState(-1).exclusiveRelease();',ctx);
  for(let i=0;i<32&&!calls;i++)await Promise.resolve();
 }
 assert.equal(calls,1);
 if(mode==='pending'||mode==='reject') {
  assert(runtime.meta(),'metadata remains owned through the application await');
  assert.equal(view.getUint32(132,true),0,'result is not lowered prematurely');
  if(mode==='reject')pending.reject(reason);else pending.resolve('result');
 }
 await observed;
 assert.equal(runtime.meta(),null);assert.equal(runtime.state().isExclusivelyLocked(),false);
 if(!failure)assert.equal(new TextDecoder().decode(new Uint8Array(memory.buffer,view.getUint32(128,true),view.getUint32(132,true))),'result');
 return events;
}
for(const mode of ['value','pending','thenable','throw','reject','then-getter-throw']) {
 assert.deepEqual(await execute(original,mode),await execute(inlineExportTaskMeta(original,parse),mode));
}
for(const mode of ['pending','reject']) {
 assert.deepEqual(await execute(original,mode,true),await execute(inlineExportTaskMeta(original,parse),mode,true));
}
''')

    def test_callback_lexical_names_are_not_captured_by_inlined_helper_locals(self):
        self.javascript(r'''
for(const name of ['args','taskID','componentIdx','fn','current','cstate','promise','resolve']) {
 const source=directIdleTaskSlots(prefix+binding.replaceAll('result0',name));
 const next=inlineExportTaskMeta(source,parse);
 const memory=new WebAssembly.Memory({initial:1});let allocation=1024,calls=0;
 const ctx=vm.createContext({$bindings:[memory,(_p,_o,_a,n)=>{const p=allocation;allocation+=n;return p;},...Array(11).fill(null)],
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:{}},
  api100Run(_mode,url){assert.equal(url,'abc',name);calls++;return 'ok';},defineBuiltinModule(){}});
 new Uint8Array(memory.buffer,64,3).set(new TextEncoder().encode('abc'));
 await vm.runInContext(next+';export_api_1_0_0$run(1,64,3,128);',ctx);
 assert.equal(calls,1);
}
''')

    def test_unknown_private_shapes_are_refused_and_framework_callbacks_are_unchanged(self):
        self.javascript(r'''
for(const [before,after] of [
 ['return await fn();','return fn();'],
 ['CURRENT_TASK_META[componentIdx] = null;','CURRENT_TASK_META[componentIdx] = undefined;'],
 ['ret = await  _withGlobalCurrentTaskMetaAsync','ret += await  _withGlobalCurrentTaskMetaAsync'],
 ['const started = await task.enter','const started = task.enter'],
 ['componentIdx: task.componentIdx(),','componentIdx: task.id(),'],
 ['fn: () => api100Run','fn: async () => api100Run'],
 ['task.setErrored(err);','task.setErrored(new Error());'],
 ['task.reject(err);','task.reject(other);'],
 ['return task.completionPromise();','return Promise.resolve();'],
 ['var result0 =','var __lsfExportTaskMetaArgs; var result0 ='],
 ['let ret;','let ret = 0;'],
 ]) {
  const mutated=original.replaceAll(before,after);assert.notEqual(mutated,original,before);
  assert.throws(()=>inlineExportTaskMeta(mutated,parse),/export-task-meta-shape-drift/,before);
 }
 const callback='\nasync function frameworkCallback(){return await _withGlobalCurrentTaskMetaAsync({taskID:1,componentIdx:1,fn:()=>42});}\n';
 const next=inlineExportTaskMeta(original+callback,parse);
 assert(next.endsWith(callback));assert(next.includes('async function _withGlobalCurrentTaskMetaAsync(args)'));
 assert(next.includes('const started = await task.enter({ isHost: hostProvided });'));
 assert(next.includes('task.reject(err);'));assert(next.includes('task.resolve([ret]);'));
 assert.equal(inlineExportTaskMeta('export const value=42;',parse),'export const value=42;');
 parse(next,{ecmaVersion:'latest',sourceType:'module'});
''')


if __name__ == '__main__':
    unittest.main()
