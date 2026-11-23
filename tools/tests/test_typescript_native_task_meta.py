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
        if node is None:
            self.skipTest('Node is required for source-only generated binding controls')
        if parser is not None:
            self.assertTrue(Path(parser).is_file())
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\nimport {readFile} from 'node:fs/promises';\nimport {createHash} from 'node:crypto';\n"
        if parser is not None:
            imports += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            # Host source controls only, never a production/compiler fallback.
            imports += "const parserScope={};const parserSource=process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'];assert.equal(typeof parserSource,'string');vm.runInNewContext(parserSource,parserScope);const {parse}=parserScope.acorn;\n"
        imports += f"import {{directIdleTaskSlots,fuseNativeImportAwaits,inlineNativeTaskMeta}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"const prefixMaterial=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_task_state.json').as_uri())}),'utf8'));\n"
        imports += f"const bindingMaterial=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_open_binding.json').as_uri())}),'utf8'));\n"
        imports += "const prefix=prefixMaterial.source;let binding=bindingMaterial.source;assert.equal(createHash('sha256').update(prefix).digest('hex'),prefixMaterial.prefixSha256);assert.equal(createHash('sha256').update(binding).digest('hex'),bindingMaterial.sourceSha256);binding=binding.replace('\\n  try {','\\n  /* lsf-owned-result-transfer:wit-result */\\n  try {');\n"
        imports += "const original=fuseNativeImportAwaits(directIdleTaskSlots(prefix+binding),parse);\n"
        imports += f"import {{lazyTaskCompletion}} from {json.dumps((ROOT/'tools/typescript_guest/source_splicer.mjs').as_uri())};\n"
        imports += r"""
function completionRuntime(source) {
 const control={allocations:0,fail:false,reason:new Error('original-native-admission-refusal')};
 const ctx=vm.createContext({$bindings:Array(14).fill(null),
  contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:{}},defineBuiltinModule(){},
  allocation(){if(control.fail)throw control.reason;++control.allocations;}});
 vm.runInContext(`const originalWithResolvers=Promise.withResolvers;
  Promise.withResolvers=function(){allocation();return Reflect.apply(originalWithResolvers,this,[]);};`,ctx);
 const runtime=vm.runInContext(source+';({AsyncTask,createNewCurrentTask,getOrCreateAsyncState});',ctx);
 return {control,runtime,fresh:()=>runtime.createNewCurrentTask({componentIdx:-1,isAsync:false,
  entryFnName:'completion-control',callingWasmExport:false})[0]};
}
"""
        result = subprocess.run([node, '--input-type=module', '-e', imports+source],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_actual_open_success_rejection_and_typed_failure_keep_task_meta_and_cleanup(self):
        self.javascript(r"""
async function execute(source,mode) {
 const events=[],pending=Promise.withResolvers(),reason={owned:true};let allocation=1024,ctx,runtime;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={beginOwnPlans(...v){assert.deepEqual(v,[2,0,0]);},delivered(_id,value){return value;},reserve(...args){events.push(['reserve',...args.slice(0,3)]);return 7;},
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
 const before=await execute(original,mode);
 assert.deepEqual(before,await execute(inlineNativeTaskMeta(original,parse),mode));
 assert.deepEqual(before,await execute(lazyTaskCompletion(inlineNativeTaskMeta(original,parse),parse),mode));
}
""")

    def test_real_contended_metadata_wait_releases_then_relocks_before_native_carrier(self):
        self.javascript(r"""
async function execute(source) {
 const pending=Promise.withResolvers();let calls=0,ctx,runtime,allocation=1024;
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 const bridge={beginOwnPlans(...v){assert.deepEqual(v,[2,0,0]);},delivered(_id,value){return value;},reserve(){return 7;},lift(){assert.equal(runtime.meta(),null);return 512;},finish(){assert.equal(runtime.meta(),null);}};
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
await execute(lazyTaskCompletion(inlineNativeTaskMeta(original,parse),parse));
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


    def test_completion_capability_is_lazy_but_identity_and_multiple_observers_are_preserved(self):
        self.javascript(r"""
for(const [source,initial] of [[prefix,2],[lazyTaskCompletion(prefix,parse),1]]) {
 const {fresh,control}=completionRuntime(source),task=fresh();
 assert.equal(control.allocations,initial); // Actual capability factories, not an LSF owner count.
 const first=task.completionPromise();
 assert.equal(control.allocations,2);assert.equal(first,task.completionPromise());
 let settled=false;const seen=[];
 first.then(value=>{settled=true;seen.push(['first',value]);});
 task.completionPromise().then(value=>seen.push(['second',value]));
 await Promise.resolve();assert.equal(settled,false);
 task.resolve([42]);assert.equal(settled,false);
 assert.equal(task.completionPromise(),first);assert.equal(await first,42);
 assert.deepEqual(seen,[['first',42],['second',42]]);assert.equal(control.allocations,2);
 task.exit();
}
""")

    def test_unobserved_completion_settles_real_promise_and_assimilates_thenables_in_original_order(self):
        self.javascript(r"""
for(const source of [prefix,lazyTaskCompletion(prefix,parse)]) {
 for(const mode of ['value','thenable','throwing-getter']) {
  const {fresh,control}=completionRuntime(source),task=fresh(),events=[];
  const reason=new Error('original-then-getter');
  const value=mode==='value'?42:Object.defineProperty({},'then',{get(){
   events.push('get');if(mode==='throwing-getter')throw reason;
   return resolve=>{events.push('then');resolve(42);};}});
  task.registerOnResolveHandler(()=>events.push('handler'));
  task.resolve([value]);
  assert.equal(control.allocations,2); // Allocate on settlement even with no prior observer.
  assert.deepEqual(events,mode==='value'?['handler']:['get','handler']);
  const completion=task.completionPromise();assert.equal(control.allocations,2);
  if(mode==='throwing-getter')await assert.rejects(completion,e=>e===reason);
  else assert.equal(await completion,42);
  assert.deepEqual(events,mode==='thenable'?['get','handler','then']:
   mode==='value'?['handler']:['get','handler']);
  assert.equal(completion,task.completionPromise());task.exit();
 }
}
""")

    def test_early_rejection_and_unobserved_rejection_keep_original_failure_reporting(self):
        self.javascript(r"""
const unhandled=[],handled=[];
const onUnhandled=(reason,promise)=>unhandled.push({reason,promise});
const onHandled=promise=>handled.push(promise);
process.on('unhandledRejection',onUnhandled);process.on('rejectionHandled',onHandled);
try {
 for(const source of [prefix,lazyTaskCompletion(prefix,parse)]) {
  for(const observe of [true,false]) {
   const {fresh,control}=completionRuntime(source),task=fresh();
   const reason=new Error('original-task-rejection');
   const early=observe?task.completionPromise():null;
   const checked=early?assert.rejects(early,e=>e===reason):null;
   const before=unhandled.length;
   task.setErrored(reason);task.reject(reason);
   assert.equal(control.allocations,2);
   await new Promise(resolve=>setImmediate(resolve));
   const completion=task.completionPromise();
   if(observe){assert.equal(completion,early);await checked;assert.equal(unhandled.length,before);}
   else {
    assert.equal(unhandled.length,before+1);assert.equal(unhandled.at(-1).reason,reason);
    assert.equal(unhandled.at(-1).promise,completion);await assert.rejects(completion,e=>e===reason);
   }
   task.exit();await new Promise(resolve=>setImmediate(resolve));
  }
 }
 assert.equal(handled.length,2);
} finally {process.off('unhandledRejection',onUnhandled);process.off('rejectionHandled',onHandled);}
""")

    def test_refused_factory_publishes_nothing_and_keeps_original_settlement_handlers(self):
        self.javascript(r"""
const {fresh,control}=completionRuntime(lazyTaskCompletion(prefix,parse)),task=fresh();
assert.equal(control.allocations,1);
let called=0;task.registerOnResolveHandler(()=>++called);
control.fail=true;
assert.throws(()=>task.completionPromise(),e=>e===control.reason);
assert.throws(()=>task.onResolve(42),e=>e===control.reason);
assert.equal(control.allocations,1);assert.equal(called,0);
control.fail=false;
const completion=task.completionPromise();assert.equal(control.allocations,2);
task.resolve([42]);assert.equal(called,1);assert.equal(await completion,42);
assert.equal(task.completionPromise(),completion);task.exit();
""")

    def test_refused_completion_keeps_task_state_and_allows_same_task_settlement_retry(self):
        self.javascript(r"""
for(const operation of ['resolve','reject','cancel']) {
 const {fresh,control,runtime}=completionRuntime(lazyTaskCompletion(prefix,parse)),task=fresh();
 if(operation==='cancel') {
  // Reach the real delivered-cancel state without first calling reject (which
  // now admits completion before child/parent changes). Restore the public
  // enum immediately; no task body or private field is replaced by the control.
  const states=runtime.AsyncTask.State, prior=Object.getOwnPropertyDescriptor(states,'PENDING_CANCEL');
  states.PENDING_CANCEL=states.INITIAL;
  assert.equal(task.deliverPendingCancel({cancellable:true}),true);
  if(prior)Object.defineProperty(states,'PENDING_CANCEL',prior);else delete states.PENDING_CANCEL;
 }
 const before={state:task.taskState(),cancelled:task.cancelled,cancelRequested:task.cancelRequested};
 const reason=new Error('original-settlement-reason');let handlers=0;
 task.registerOnResolveHandler(()=>++handlers);
 const settle=()=>operation==='resolve'?task.resolve([42]):
  operation==='reject'?task.reject(reason):task.cancel({error:reason});
 control.fail=true;
 for(let attempt=0;attempt<2;++attempt) {
  assert.throws(settle,e=>e===control.reason);
  assert.deepEqual({state:task.taskState(),cancelled:task.cancelled,cancelRequested:task.cancelRequested},before);
  assert.equal(handlers,0);assert.equal(control.allocations,1);
 }
 control.fail=false;settle();
 assert.equal(handlers,1);assert.equal(control.allocations,2);assert.equal(task.isResolved(),true);
 const completion=task.completionPromise();assert.equal(completion,task.completionPromise());
 if(operation==='reject')await assert.rejects(completion,e=>e===reason);
 else assert.equal(await completion,operation==='resolve'?42:reason);
 task.exit();
}
""")

    def test_parent_completion_refusal_does_not_visit_child_rejection(self):
        self.javascript(r"""
const {fresh,control}=completionRuntime(lazyTaskCompletion(prefix,parse)),task=fresh();
const child=task.createSubtask({componentIdx:-1,fnName:'child-control',callMetadata:{},isAsync:false});
let visited=0;const reason=new Error('reject-after-admission');
// Observe call ordering only; this does not claim child-lifecycle qualification.
child.reject=error=>{assert.equal(error,reason);++visited;};
control.fail=true;
assert.throws(()=>task.reject(reason),e=>e===control.reason);
assert.equal(visited,0);assert.equal(task.isResolved(),false);
control.fail=false;task.reject(reason);assert.equal(visited,1);
await assert.rejects(task.completionPromise(),e=>e===reason);
task.removeSubtask(child);task.exit();
""")

    def test_completion_admission_preserves_existing_validation_and_terminal_noops(self):
        self.javascript(r"""
const {fresh,control}=completionRuntime(lazyTaskCompletion(prefix,parse));
const borrowed=fresh();borrowed.borrowedHandles=[42];const before=control.allocations;
control.fail=true;
assert.throws(()=>borrowed.resolve([42]),/task still has borrow handles/);
assert.throws(()=>borrowed.cancel(),/invalid task state/);
assert.equal(control.allocations,before);assert.equal(borrowed.isResolved(),false);
control.fail=false;borrowed.borrowedHandles=[];borrowed.resolve([42]);
await borrowed.completionPromise();
control.fail=true;
assert.throws(()=>borrowed.resolve([42]),/already resolved/);
assert.equal(borrowed.reject(new Error('ignored-after-settlement')),undefined);
assert.equal(control.allocations,before+1);borrowed.exit();
""")

    def test_lazy_completion_preserves_pending_entry_queue_and_reentrant_observation(self):
        self.javascript(r"""
for(const source of [directIdleTaskSlots(prefix),lazyTaskCompletion(directIdleTaskSlots(prefix),parse)]) {
 const {fresh}=completionRuntime(source),first=fresh(),second=fresh(),events=[];
 await first.enter();let entered=false;
 const pending=second.enter().then(()=>{entered=true;events.push('entered');});
 for(let i=0;i<4;++i)await Promise.resolve();assert.equal(entered,false);
 first.registerOnResolveHandler(()=>{
  const completion=first.completionPromise();
  assert.equal(completion,first.completionPromise());completion.then(value=>events.push(value));
 });
 first.resolve([42]);assert.equal(entered,false);first.exit();await pending;
 assert.equal(entered,true);assert.deepEqual(events,[42,'entered']);second.resolve([]);second.exit();
}
""")

    def test_unreviewed_completion_shape_and_extra_private_uses_are_rejected(self):
        self.javascript(r"""
const adapted=lazyTaskCompletion(prefix,parse);
for(const [before,after] of [
 ['class AsyncTask {','class AsyncTask extends OtherTask {'],
 ['#onResolveHandlers = [];','#onResolveHandlers = customHandlers;'],
 ['#completionPromise = null;','#completionPromise = undefined;'],
 ['completionPromise() { return this.#completionPromise; }','completionPromise() { return Promise.resolve(); }'],
 ['this.#completionPromise = completionPromise;','this.#completionPromise = exitPromise;'],
 ['rejectCompletionPromise(this.#errored);','rejectCompletionPromise(results);'],
 ['const handlers = this.#onResolveHandlers;','const handlers = [...this.#onResolveHandlers];'],
 ['this.#onResolveHandlers = [];','this.#onResolveHandlers.length = 0;'],
 ['taskState() { return this.#state; }','taskState() { return this.#completionPromise; }'],
 ['this.#completionPromise = completionPromise;','this.#completionPromise = completionPromise; resolveCompletionPromise(42);'],
 ['this.#state = AsyncTask.State.RESOLVED;','this.#state = AsyncTask.State.CANCEL_DELIVERED;'],
 ['if (this.isResolvedState() || this.#rejected) { return; }','if (this.#rejected) { return; }'],
 ['for (const subtask of this.#subtasks) {','for (const subtask of otherTasks) {'],
 ['this.cancelled = true;','this.cancelled = false;'],
 ['if (this.borrowedHandles.length > 0)','if (this.borrowedHandles.length >= 0)'],
 ]) {
  assert.notEqual(prefix.replace(before,after),prefix);
  assert.throws(()=>lazyTaskCompletion(prefix.replaceAll(before,after),parse),/task-completion-shape-drift/);
}
assert.throws(()=>lazyTaskCompletion(adapted,parse),/task-completion-shape-drift/);
assert.throws(()=>lazyTaskCompletion(prefix+'\n// #completionCapability',parse),/task-completion-shape-drift/);
assert.equal(lazyTaskCompletion('export const scalar=42;',parse),'export const scalar=42;');
const shape=value=>JSON.stringify(value,(key,value)=>['start','end','raw'].includes(key)?undefined:typeof value==='bigint'?{bigint:String(value)}:value);
function taskClass(source) {
 let result;function walk(node){if(!node||typeof node!=='object')return;
  if(node.type==='ClassDeclaration'&&node.id.name==='AsyncTask')result=node;
  for(const value of Object.values(node)){if(Array.isArray(value))value.forEach(walk);else walk(value);}}
 walk(parse(source,{ecmaVersion:'latest',sourceType:'module'}));return result;
}
const before=taskClass(prefix),after=taskClass(adapted);
for(const member of before.body.body) {
 if(['constructor','completionPromise','onResolve','resolve','reject','cancel'].includes(member.key.name))continue;
 const matching=after.body.body.filter(value=>shape(value)===shape(member));assert.equal(matching.length,1);
}
for(const name of ['resolve','reject','cancel']) {
 const original=before.body.body.find(member=>member.key.name===name);
 const changed=structuredClone(after.body.body.find(member=>member.key.name===name));
 const body=changed.value.body.body;
 const preparations=body.filter(node=>node.type==='ExpressionStatement' &&
  node.expression.type==='CallExpression' && node.expression.callee.property?.name==='ensureCompletionPromise');
 assert.equal(preparations.length,1);
 changed.value.body.body=body.filter(node=>node!==preparations[0]);
 assert.equal(shape(changed),shape(original));
}
assert(adapted.includes('this.#completionCapability = null; // Drop captures'));
""")


if __name__ == '__main__':
    unittest.main()
