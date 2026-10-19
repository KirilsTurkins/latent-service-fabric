"""Authentic generated Task ordering; Node counts are not LSF qualification."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptIdleTaskTests(unittest.TestCase):
    def javascript(self, source):
        node = shutil.which('node')
        if node is None:
            self.skipTest('requires Node for actual generated Task controls')
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\n"
        imports += "import {readFile} from 'node:fs/promises';\nimport {createHash} from 'node:crypto';\nimport {createHook} from 'node:async_hooks';\n"
        imports += f"import {{directIdleTaskSlots}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"const fixture=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_task_state.json').as_uri())}),'utf8'));\n"
        imports += "const original=fixture.source;assert.equal(createHash('sha256').update(original).digest('hex'),fixture.prefixSha256);\n"
        imports += """
function load(source) {
 const scope={$bindings:Array(14).fill(null),contentGlobal:{TextEncoder,TextDecoder,Promise,__lsfAsyncImportBridge:{}},defineBuiltinModule(){}};
 return vm.runInNewContext(source+';({AsyncTask,getOrCreateAsyncState,createNewCurrentTask});',scope);
}
function fresh(runtime,options={}) {
 return runtime.createNewCurrentTask({componentIdx:1,isAsync:false,isManualAsync:true,entryFnName:'owned',callingWasmExport:true,...options})[0];
}
function exit(task,skip=false) {task.resolve([]);task.exit({skipExclusiveLockCheck:skip});}
"""
        result = subprocess.run([node, '--input-type=module', '-e', imports+source],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_real_closed_first_middle_and_post_slot_entry_race_remain_refused(self):
        self.javascript(r"""
const previous=fresh(load(original));const oldEntry=previous.enter();exit(previous,true);
assert.equal(await oldEntry,true); // Actual old code grants entry after this real Task exited.
const runtime=load(directIdleTaskSlots(original));
const closed=fresh(runtime);exit(closed,true);
await assert.rejects(runtime.getOrCreateAsyncState(1).nextTaskExecutionSlot({task:closed}),
 e=>e.message==='selected-runtime-task-exited-before-slot');
const [first,middle,last]=Array.from({length:3},()=>fresh(runtime,{isAsync:true,isManualAsync:false}));
await first.enter();let middleEntered=false,lastEntered=false;
const mid=middle.enter().then(()=>{middleEntered=true;},e=>{
 assert.equal(e.message,'selected-runtime-task-exited-before-slot');});
const end=last.enter().then(()=>{lastEntered=true;});
exit(middle,true);for(let i=0;i<4;i++)await Promise.resolve();
assert.equal(middleEntered,false);assert.equal(lastEntered,false);
exit(first);await mid;await end;assert.equal(lastEntered,true);exit(last);
const raced=fresh(load(directIdleTaskSlots(original)));const entering=raced.enter();exit(raced,true);
await assert.rejects(entering,e=>e.message==='selected-runtime-task-exited-before-entry');
""")

    def test_live_contended_order_retirement_gap_and_unknown_fallback_keep_async_entry(self):
        self.javascript(r"""
for(const source of [original,directIdleTaskSlots(original)]) {
 const runtime=load(source),first=fresh(runtime),second=fresh(runtime),third=fresh(runtime);
 const order=[];let firstDone=false;
 const initial=first.enter().then(()=>{firstDone=true;order.push(1);});
 assert.equal(firstDone,false);await initial;
 const pending=second.enter().then(()=>order.push(2));
 for(let i=0;i<4;i++)await Promise.resolve();assert.deepEqual(order,[1]);
 exit(first);await Promise.resolve(); // Current cleanup ran; earlier waiter may not have resumed.
 const following=third.enter().then(()=>order.push(3));
 await pending;assert.deepEqual(order,[1,2]);exit(second);await following;
 assert.deepEqual(order,[1,2,3]);exit(third);
 // Unknown/fake callers retain the original asynchronous completion guard.
 const state=runtime.getOrCreateAsyncState(2);
 await assert.rejects(state.nextTaskExecutionSlot({task:{exitPromise:()=>Promise.resolve()}}),
  e=>e.message==='selected-runtime-task-exited-before-slot');
}
""")

    def test_idle_real_task_avoids_two_reference_promises_without_synchronous_public_entry(self):
        self.javascript(r"""
async function allocations(source) {
 const runtime=load(source),task=fresh(runtime);let promises=0;
 const hook=createHook({init(_id,kind){if(kind==='PROMISE')promises++;}});
 hook.enable();await task.enter();hook.disable();exit(task);return promises;
}
const before=await allocations(original),after=await allocations(directIdleTaskSlots(original));
assert.equal(before,10);assert.equal(after,8); // Node reference only; actual signed limits stay unchanged.
""")

    def test_unreviewed_private_task_or_duplicate_idle_anchors_fail_closed(self):
        self.javascript(r"""
for(const anchor of ['class AsyncTask {','  #exited = false;','    this.#exited = true;',
 'isSync() { return !this.isAsync(); }',
 "      await this.#nextTaskPromise;\n      if (placeholder.completed) throw new Error('selected-runtime-task-exited-before-slot');",
 '    await cstate.nextTaskExecutionSlot({ task: this });']) {
 assert.equal(original.split(anchor).length,2);
 assert.throws(()=>directIdleTaskSlots(original.replace(anchor,'')),/idle-task-shape-drift/);
 assert.throws(()=>directIdleTaskSlots(original+'\n'+anchor),/idle-task-shape-drift/);
}
assert.throws(()=>directIdleTaskSlots(original+'\nhasExitedBeforeEntry'),/idle-task-shape-drift/);
assert.throws(()=>directIdleTaskSlots(directIdleTaskSlots(original)),/idle-task-shape-drift/);
""")


if __name__ == '__main__':
    unittest.main()
