"""Host-only binding controls. These are not engine or signed borrow evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ImportCancellationTests(unittest.TestCase):
    def javascript(self, body):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for host-only handoff controls')
        parser = os.environ.get('LSF_TYPESCRIPT_ACORN')
        if parser is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
            parser = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND']) / 'node_modules/acorn/dist/acorn.mjs')
        prelude = "import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';\n"
        if parser:
            self.assertTrue(Path(parser).is_file())
            prelude += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            # Test mechanism only: production still requires the source-owned
            # pinned compiler parser, with no fallback to Node internals.
            prelude += "const parserScope={};const parserSource=process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'];assert.equal(typeof parserSource,'string');vm.runInNewContext(parserSource,parserScope);const {parse}=parserScope.acorn;\n"
        prelude += f"import {{borrowReleaseHandoff,selectedBorrowReleaseImports}} from {json.dumps((ROOT/'tools/typescript_guest/import_cancellation.mjs').as_uri())};\n"
        prelude += f"import {{fuseNativeImportAwaits}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        prelude += "const anchor='const __lsfImports = contentGlobal.__lsfAsyncImportBridge;';\n"
        prelude += "const minimal=anchor+`\nasync function import_owned$read(value) {\n const __lsfImportId=__lsfImports.reserve(4,0,1,value);\n const __lsfAwaitImport=(...lowered)=>$import_owned$read(__lsfImportId | 0,...lowered);\n try { return await __lsfAwaitImport(value); } finally { __lsfImports.finish(__lsfImportId); }\n}`;\n"
        prelude += "const selected=[{binding:'import_owned$read',alias:'read'}];\n"
        result = subprocess.run([node, '--input-type=module', '-e', prelude + body],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_bytes_and_actual_captured_binding_shape(self):
        self.javascript(f"""
assert(Object.isFrozen(selectedBorrowReleaseImports));assert.equal(selectedBorrowReleaseImports.length,0);
assert.equal(borrowReleaseHandoff(minimal,()=>{{throw Error('must not parse');}}),minimal);
const fixture=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_open_binding.json').as_uri())}),'utf8'));
const captured=fuseNativeImportAwaits(anchor+'\\n'+fixture.source.replace('\\n  try {{','\\n  /* lsf-owned-result-transfer:wit-result */\\n  try {{'),parse);
const changed=borrowReleaseHandoff(captured,parse,[{{binding:'import_latent_http_streaming_0_3_0$open',alias:'open'}}]);
assert.equal(changed.split('__lsfBorrowArm(import_latent_http_streaming_0_3_0$open, __lsfImportId);').length,2);
const oldFn=parse(captured,{{ecmaVersion:'latest',sourceType:'module'}}).body[1];
const matches=parse(changed,{{ecmaVersion:'latest',sourceType:'module'}}).body.filter(node=>node.type==='FunctionDeclaration'&&node.id?.name===oldFn.id.name);
assert.equal(matches.length,1);const newFn=matches[0];
const erase=node=>Array.isArray(node)?node.map(erase):node&&typeof node==='object'?Object.fromEntries(Object.entries(node).filter(([key])=>!['start','end'].includes(key)).map(([key,value])=>[key,erase(value)])):node;
const arm=newFn.body.body[2].block.body.shift();
assert.equal(arm.expression.callee.name,'__lsfBorrowArm');
assert.deepEqual(erase(newFn),erase(oldFn));
""")

    def test_logical_rejection_precedes_release_and_default_call_stays_lazy(self):
        self.javascript(r"""
const records=new Map(),handles=new Map(),events=[];let next=1,cancels=0,arms=0;
const bridge={reserve(_r,_p,_k,value){const id=next++;records.set(id,{value,result:Promise.withResolvers(),release:Promise.withResolvers()});return id;},
 watchBorrow(id){arms++;const handle=Object.freeze({});handles.set(handle,records.get(id));return handle;},
 finish(id){events.push(['finish',id]);},
 borrowReleased(handle){return handles.get(handle).release.promise;},
 cancelBorrow(handle){const record=handles.get(handle);if(!record.cancelled){record.cancelled=true;cancels++;record.result.reject('logical-cancelled');}return record.release.promise;}};
const scope={contentGlobal:{Promise,__lsfAsyncImportBridge:bridge},$import_owned$read(id,value){assert.equal(records.get(id).value,value);return records.get(id).result.promise;}};
const api=vm.runInNewContext(borrowReleaseHandoff(minimal,parse,selected)+';({selected:__lsfBorrowCalls.read,normal:import_owned$read});',scope);
const operation=api.selected('owned');const rejected=assert.rejects(operation.promise,e=>e==='logical-cancelled');
const released=operation.borrowReleased;let acknowledged=false;released.then(()=>{acknowledged=true;});
assert.equal(operation.cancel(),released);assert.equal(operation.cancel(),released);
await rejected;assert.equal(cancels,1);assert.equal(acknowledged,false);assert.deepEqual(events,[['finish',1]]);
// Only this explicit fake canonical-drop barrier can release the second Promise.
// It deliberately says nothing about a physical provider IoCall/IoTransfer.
records.get(1).release.resolve();await released;assert.equal(acknowledged,true);
assert.equal(operation.cancel(),released);assert.equal(cancels,1);
const normal=api.normal('ordinary');assert.equal(arms,1);records.get(2).result.resolve(42);assert.equal(await normal,42);
assert.deepEqual(events,[['finish',1],['finish',2]]);
""")

    def test_admission_refusal_never_supplies_release_or_starts_native_call(self):
        self.javascript(r"""
const reason={denied:true};let started=0,finished=0;
const scope={contentGlobal:{Promise,__lsfAsyncImportBridge:{reserve(){return 1;},watchBorrow(){throw reason;},finish(){finished++;}}},
 $import_owned$read(){started++;}};
const start=vm.runInNewContext(borrowReleaseHandoff(minimal,parse,selected)+';__lsfBorrowCalls.read;',scope);
const operation=start('refused');await assert.rejects(operation.promise,error=>error===reason);
assert.throws(()=>operation.borrowReleased,/not-admitted/);assert.throws(()=>operation.cancel(),/not-admitted/);
assert.equal(started,0);assert.equal(finished,1);
""")

    def test_nested_selected_frames_keep_the_original_handles(self):
        self.javascript(r"""
const records=new Map(),handles=new Map();let next=1,nested,start;
const bridge={reserve(_r,_p,_k,value){if(value==='outer')nested=start('inner');const id=next++;records.set(id,{value,result:Promise.withResolvers(),release:Promise.withResolvers()});return id;},
 watchBorrow(id){const handle=Object.freeze({});handles.set(handle,records.get(id));return handle;},finish(){},
 borrowReleased(handle){return handles.get(handle).release.promise;},
 cancelBorrow(handle){const record=handles.get(handle);record.result.reject(record.value);return record.release.promise;}};
const scope={contentGlobal:{Promise,__lsfAsyncImportBridge:bridge},$import_owned$read(id){return records.get(id).result.promise;}};
start=vm.runInNewContext(borrowReleaseHandoff(minimal,parse,selected)+';__lsfBorrowCalls.read;',scope);
const outer=start('outer');const innerFailure=assert.rejects(nested.promise,error=>error==='inner');nested.cancel();await innerFailure;
let outerSettled=false;outer.promise.then(()=>{outerSettled=true;});await Promise.resolve();assert.equal(outerSettled,false);
records.get(2).result.resolve('outer-value');assert.equal(await outer.promise,'outer-value');
records.get(1).release.resolve();records.get(2).release.resolve();await nested.borrowReleased;await outer.borrowReleased;
""")

    def test_changed_or_ambiguous_generated_graph_refuses(self):
        self.javascript(r"""
for(const [before,after] of [
 [anchor,'// '+anchor],
 [anchor,'const __lsfImports = unreviewedBridge;'],
 ['async function','function'],['const __lsfImportId=','let __lsfImportId='],
 ['const __lsfImportId=','await 0;const __lsfImportId='],
 ['__lsfImports.reserve(4,0,1,value)','__lsfImports.reserve(4,0,1,unknown)'],
 ['$import_owned$read(__lsfImportId | 0,...lowered)','$other(__lsfImportId | 0,...lowered)'],
 ['__lsfImportId | 0','__lsfImportId | 1'],
 ['__lsfImports.finish(__lsfImportId)','__lsfImports.finish(0)'],
 ['__lsfImports.finish(__lsfImportId);','__lsfImports.finish(__lsfImportId);sideEffect();'],
 ]){assert(minimal.includes(before));assert.throws(()=>borrowReleaseHandoff(minimal.replace(before,after),parse,selected),/shape-drift/);}
for(const selection of [[{binding:'missing',alias:'read'}],[...selected,...selected],
 [{...selected[0],authority:'ambient'}],[{binding:true,alias:'read'}],Array(17).fill(selected[0]),{}]){
 assert.throws(()=>borrowReleaseHandoff(minimal,parse,selection),/shape-drift/);
}
assert.throws(()=>borrowReleaseHandoff(minimal+';let __lsfBorrowUnknown;',parse,selected),/shape-drift/);
""")

    def test_observer_and_handoff_are_bound_by_owned_source_recipes(self):
        from tools.typescript_guest.activation_engine import engine_input_paths
        from tools.typescript_guest.import_engine import IMPORT_PROFILE
        from tools.typescript_guest.build import RECIPE
        observer = 'sdk/typescript-guest/activation/native_import_observer.h'
        for profile in ('spidermonkey-activation-promises-v1',
                        'spidermonkey-activation-promises-clocks-v1', IMPORT_PROFILE):
            self.assertIn(observer, engine_input_paths(profile))
        self.assertIn(observer, RECIPE)
        self.assertIn('tools/typescript_guest/import_cancellation.mjs', RECIPE)


if __name__ == '__main__':
    unittest.main()
