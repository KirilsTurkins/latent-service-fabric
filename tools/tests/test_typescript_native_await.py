"""Actual captured native binding controls; signed execution remains separate."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNativeAwaitTests(unittest.TestCase):
    def native_binding_javascript(self, source):
        node = shutil.which('node')
        parser = os.environ.get('LSF_TYPESCRIPT_ACORN')
        if parser is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
            parser = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND'])/'node_modules/acorn/dist/acorn.mjs')
        if node is None:
            self.skipTest('Node is required for source-only generated binding controls')
        if parser is not None:
            self.assertTrue(Path(parser).is_file())
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\n"
        imports += "import {readFile} from 'node:fs/promises';\nimport {createHash} from 'node:crypto';\n"
        if parser is not None:
            imports += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            # Host source controls only, never a production/compiler fallback.
            imports += "const parserScope={};const parserSource=process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'];assert.equal(typeof parserSource,'string');vm.runInNewContext(parserSource,parserScope);const {parse}=parserScope.acorn;\n"
        imports += f"import {{explicitResourceOwners}} from {json.dumps((ROOT/'tools/typescript_guest/resources.mjs').as_uri())};\n"
        imports += f"import {{fuseNativeImportAwaits, staticOwnBindings}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"const fixture=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_open_binding.json').as_uri())}),'utf8'));\n"
        imports += "assert.equal(createHash('sha256').update(fixture.source).digest('hex'),fixture.sourceSha256);\n"
        imports += "const original='const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\\n'+fixture.source.replace('\\n  try {','\\n  /* lsf-owned-result-transfer:wit-result */\\n  try {');\n"
        result = subprocess.run([node, '--input-type=module', '-e', imports+source],
                                text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_native_open_fuses_existing_await_without_changing_typed_code(self):
        self.native_binding_javascript(r"""
const fused=fuseNativeImportAwaits(original,parse);
assert.notEqual(fused,original);
const before=parse(original,{ecmaVersion:'latest',sourceType:'module'}).body[1];
const after=parse(fused,{ecmaVersion:'latest',sourceType:'module'}).body[1];
assert.equal(before.id.name,after.id.name);
assert(before.async && after.async);
function strip(node) {
 if (Array.isArray(node)) return node.map(strip);
 if (!node || typeof node!=='object') return node;
 if (node.type==='VariableDeclarator' && node.id.name==='__lsfAwaitImport') return {type:'carrier-forwarder'};
 if (node.type==='AwaitExpression' && node.argument.type==='CallExpression' &&
     node.argument.callee.name==='_withGlobalCurrentTaskMetaAsync') return {type:'await-native-carrier'};
 if (node.type==='CallExpression' && node.callee.type==='MemberExpression' &&
     node.callee.object.name==='__lsfImports' && node.callee.property.name==='lift') return {type:'await-native-carrier'};
 if (node.type==='CallExpression' && node.callee.type==='MemberExpression' &&
     node.callee.object.name==='__lsfImports' && node.callee.property.name==='delivered') return strip(node.arguments[1]);
 return Object.fromEntries(Object.entries(node).filter(([key])=>!['start','end','raw'].includes(key)).map(([key,value])=>[key,strip(value)]));
}
assert.deepEqual(strip(before),strip(after));
assert.equal(fuseNativeImportAwaits('export const synchronous=42;',parse),'export const synchronous=42;');
""")

    def test_actual_native_open_preserves_pending_success_and_each_error_retirement(self):
        self.native_binding_javascript(r"""
async function execute(source,mode) {
 const events=[],pending=Promise.withResolvers(),reason={original:true};
 const memory=new WebAssembly.Memory({initial:1}),view=new DataView(memory.buffer);
 let allocation=1024,error;
 const symbol=Symbol('handle');class Upload{};
 class ComponentError extends Error {constructor(payload){if(mode==='error-constructor-failure')throw reason;super('typed-error');this.payload=payload;}}
 const bridge={beginOwnPlans(version,plans,slots){assert.deepEqual([version,plans,slots],[2,0,0]);},reserve(...args){events.push(['reserve',...args.slice(0,3)]);return 7;},
  lift(id){events.push(['lift',id]);if(mode==='lift-failure')throw reason;assert.equal(id,7);return 512;},
  delivered(id,value){events.push(['delivered',id]);assert.equal(id,7);return value;},
  finish(id){events.push(['finish',id]);assert.equal(id,7);}};
 const task={id:()=>1,componentIdx:()=>1,async enter(){events.push(['enter']);return true;},
  setErrored(v){error=v;},reject(v){error=v;events.push(['reject']);},
  completionPromise(){return Promise.reject(error);},
  resolve(v){events.push(['resolve',v.length]);},exit(){events.push(['exit']);}};
 const scope={contentGlobal:{__lsfAsyncImportBridge:bridge},$memory:memory,
  $realloc(_p,_old,_align,size){const address=allocation;allocation+=size;return address;},
  _utf8AllocateAndEncode(value,realloc){const data=new TextEncoder().encode(value);const ptr=realloc(0,0,1,data.length);new Uint8Array(memory.buffer,ptr,data.length).set(data);return{ptr,len:data.length};},
  toUint64:BigInt,dataView:()=>view,_debugLog(){},createNewCurrentTask:()=>[task,1],
  async _withGlobalCurrentTaskMetaAsync({fn}){events.push(['wrapper-enter']);try{return await fn();}finally{events.push(['wrapper-exit']);}},
  $import_latent_http_streaming_0_3_0$open(...args){events.push(['native',...args]);return pending.promise;},
  import_streaming_0_3_0$Upload:Upload,symbolRscHandle:symbol,
  finalizationRegistry_import$streaming_0_3_0$upload:{register(_v,handle){events.push(['resource',handle]);if(mode==='partial-own-lift-failure')throw reason;}},ComponentError};
 const invoke=vm.runInNewContext(source+';import_latent_http_streaming_0_3_0$open;',scope);
 const input={method:mode==='lowering-failure'?'forged':'get',url:'https://fixture.invalid/json',
  headers:[{name:'x-conformance',value:'owned'}],bodyLength:0n};
 const result=invoke(input);assert.equal(typeof result.then,'function');
 if(mode==='lowering-failure') {
  await assert.rejects(result,e=>e.message.includes('not one of the cases'));
  assert.equal(events.some(e=>e[0]==='native'),false);
 } else {
  for(let turn=0;turn<12;turn++)await Promise.resolve();
  assert.equal(events.some(e=>e[0]==='finish'),false);
  assert.equal(events.filter(e=>e[0]==='native').length,1);
  if(mode==='native-failure')pending.reject(reason);
  else {view.setUint8(512,['typed-failure','error-constructor-failure'].includes(mode)?1:0);view.setInt32(516,mode==='typed-failure'?12:42,true);pending.resolve(7);}
  if(mode==='success'){const value=await result;assert.equal(Object.getPrototypeOf(value),Upload.prototype);assert.equal(value[symbol],42);}
  else if(mode==='typed-failure')await assert.rejects(result,e=>e.payload.tag==='uncertain');
  else await assert.rejects(result,e=>e===reason);
 }
 assert.equal(events.filter(e=>e[0]==='finish').length,1);
 assert.deepEqual(events.at(-1),['finish',7]);
 assert.equal(events.filter(e=>e[0]==='delivered').length,source.includes('__lsfImports.delivered(')&&['success','typed-failure'].includes(mode)?1:0);
 return events.filter(e=>!['lift','wrapper-exit','delivered'].includes(e[0]));
}
for(const mode of ['success','native-failure','lift-failure','typed-failure','lowering-failure','partial-own-lift-failure','error-constructor-failure']){
 assert.deepEqual(await execute(original,mode),await execute(fuseNativeImportAwaits(original,parse),mode));
}
""")

    def test_native_await_fusion_rejects_unknown_or_partial_private_graph(self):
        self.native_binding_javascript(r"""
for(const [before,after] of [
 ['__lsfImports.reserve(8, 80, 5, arg0)','__lsfImports.cancel(8, 80, 5, arg0)'],
 ['__lsfImports.finish(__lsfImportId)','__lsfImports.finish(0)'],
 ['__lsfImportId | 0','__lsfImportId | 1'],
 ['const __lsfAwaitImport = async','const __lsfAwaitImport ='],
 ['fn: () => __lsfAwaitImport','fn: async () => __lsfAwaitImport'],
 ['await  _withGlobalCurrentTaskMetaAsync','await  unreviewedWrapper'],
 ['await  _withGlobalCurrentTaskMetaAsync','await  _withGlobalCurrentTaskMetaOtherAsync'],
 ['const __lsfImports = contentGlobal.__lsfAsyncImportBridge;','const __lsfImports = unreviewedBridge;'],
 ]) {assert(original.includes(before));assert.throws(()=>fuseNativeImportAwaits(original.replace(before,after),parse),/shape-drift/);}
assert.throws(()=>fuseNativeImportAwaits(original+';__lsfAwaitImport(1);',parse),/shape-drift/);
""")

    def test_owned_transfer_rejects_unknown_terminal_and_error_branches(self):
        self.native_binding_javascript(r"""
for(const [before,after] of [
 ['lsf-owned-result-transfer:wit-result','lsf-owned-result-transfer:unknown'],
 ['/* lsf-owned-result-transfer:wit-result */',''],
 ['task.resolve([retCopy.val]);','task.resolve([unknown]);'],
 ['throw new ComponentError(retCopy.val);','throw new Error(retCopy.val);'],
 ["retCopy.tag === 'err'","retCopy.tag === 'ok'"],
 ['return retCopy.val;','return unknown;'],
 ['throw new ComponentError(retCopy.val);','throw new ComponentError(retCopy);'],
 ]) {assert(original.includes(before));assert.throws(()=>fuseNativeImportAwaits(original.replace(before,after),parse),/shape-drift/);}
""")

    def test_value_and_void_transfer_follow_original_terminal_task_exit(self):
        self.native_binding_javascript(r"""
const start=original.indexOf('    const retCopy = variant16;');
const end=original.indexOf('  } finally { __lsfImports.finish',start);
assert(start>0&&end>start);
for(const [tail,expected] of [
 ['    task.resolve([rsc13]); task.exit(); return rsc13;\n','return __lsfImports.delivered(__lsfImportId, rsc13);'],
 ['    task.resolve([ret]); task.exit();\n','__lsfImports.delivered(__lsfImportId, undefined);'],
]) {
 const candidate=(original.slice(0,start)+tail+original.slice(end)).replace('lsf-owned-result-transfer:wit-result','lsf-owned-result-transfer:value');
 const actual=fuseNativeImportAwaits(candidate,parse);
 assert(actual.includes(expected));parse(actual,{ecmaVersion:'latest',sourceType:'module'});
 const last=candidate.lastIndexOf('task.exit();');assert(last>0);
 assert.throws(()=>fuseNativeImportAwaits(candidate.slice(0,last)+'task.exit(1);'+candidate.slice(last+'task.exit();'.length),parse),/shape-drift/);
}
""")



    def test_static_own_handoff_is_native_and_constructor_this_is_uncertain(self):
        self.native_binding_javascript(r"""
if(process.env.LSF_TYPESCRIPT_PARTIAL_BINDING_CAPTURE) {
 const actual=await readFile(process.env.LSF_TYPESCRIPT_PARTIAL_BINDING_CAPTURE,'utf8');
 assert(Buffer.byteLength(actual)<=256*1024);
 const active=fuseNativeImportAwaits(explicitResourceOwners(actual),parse);
 assert(active.includes('__lsfImports.beginOwnPlans(2, 1, 2)'));
 assert(active.includes('__lsfImports.attachOwn(__lsfImportId, 0)'));
 assert(active.includes('__lsfImports.attachOwn(__lsfImportId, 1)'));
}
const header=`const __lsfImports = contentGlobal.__lsfAsyncImportBridge;
const symbolRscHandle = Symbol('handle');
const symbolDispose = Symbol.dispose;
const finalizationRegistry_import$test$thing = { register() {}, unregister() {} };
class import_test$Thing {
  constructor() { throw new TypeError('host-resource-cannot-be-constructed'); }
  [symbolDispose]() {
    const handle = this[symbolRscHandle];
    if (handle === undefined) return;
    this[symbolRscHandle] = undefined;
    $resource_import$test$drop$thing(handle);
  }
}
`;
const slot={offset:0,resource:3,registry:'finalizationRegistry_import$test$thing',class:'import_test$Thing'};
const plan={key:12,bytes:8,raw:5,slots:[slot,{...slot,offset:4}]};
const body=`async function invoke() {
const __lsfImportId=7;
/* lsf-own-plan-v2:${JSON.stringify(plan)} */
const ret=__lsfImports.lift(await Promise.resolve(7));
var handle0=dataView($memory).getInt32(ret+0,true);
var resource0=new.target === import_test$Thing ? this : Object.create(import_test$Thing.prototype);
Object.defineProperty(resource0,symbolRscHandle,{writable:true,value:handle0});
finalizationRegistry_import$test$thing.register(resource0,handle0,resource0);
var handle1=dataView($memory).getInt32(ret+4,true);
var resource1=new.target === import_test$Thing ? this : Object.create(import_test$Thing.prototype);
Object.defineProperty(resource1,symbolRscHandle,{writable:true,value:handle1});
finalizationRegistry_import$test$thing.register(resource1,handle1,resource1);
return [resource0,resource1];
}`;
const generated=header+body,rewritten=staticOwnBindings(generated,parse);
assert(rewritten.includes('__lsfImports.attachOwn(__lsfImportId, 0)'));
assert(rewritten.includes('__lsfImports.attachOwn(__lsfImportId, 1)'));
assert(rewritten.includes('__lsfImports.uncertainOwn(__lsfImportId)'));
const events=[],bound=[];
const bridge={beginOwnPlans(...v){events.push(v);},bindOwnSlot(...v){bound.push(v);},
 lift(){return 512;},uncertainOwn(){assert.fail('fresh branch');},attachOwn(id,index){
  assert.equal(arguments.length,2);assert.equal(id,7);return {native:index};}};
const memory=new WebAssembly.Memory({initial:1});
const view=new DataView(memory.buffer);view.setInt32(512,42,true);view.setInt32(516,84,true);
const invoke=vm.runInNewContext(rewritten+';invoke;',{
 contentGlobal:{__lsfAsyncImportBridge:bridge},$memory:memory,dataView:()=>view,
 $resource_import$test$drop$thing(){assert.fail('no implicit canonical drop');}});
assert.deepEqual(events,[[2,1,2]]);assert.equal(bound.length,2);
assert.equal(bound[0][4],0);assert.equal(bound[1][4],4);assert.equal(bound[0][5],3);
const result=await invoke();assert.equal(result[0].native,0);assert.equal(result[1].native,1);
// A canonical offset/type mismatch cannot be repaired by guessed variable
// names or an application-supplied handle/progress declaration.
for(const [before,after] of [['ret+4','ret+0'],['getInt32','getUint32'],
 ['value:handle1','value:handle0'],['writable:true','writable:false'],
 ['register() {}','register() { throw new Error("user"); }']]) {
 const refused=staticOwnBindings(generated.replace(before,after),parse);
 assert(!refused.includes('__lsfImports.attachOwn('));
 assert(refused.includes('__lsfImports.beginOwnPlans(2, 0, 0)'));
}
assert.throws(()=>staticOwnBindings(generated.replace('"resource":3','"resource":-1'),parse),/shape-drift/);
""")

    def test_static_own_plan_overbound_collision_and_missing_seal_shape_refuse(self):
        self.native_binding_javascript(r"""
const prefix='const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\n';
assert.equal(staticOwnBindings('export const original=1;',parse),'export const original=1;');
assert(staticOwnBindings(prefix+'function untouched(){}',parse).endsWith(
 '__lsfImports.beginOwnPlans(2, 0, 0);\n'));
if(process.env.LSF_TYPESCRIPT_PARTIAL_BINDING_CAPTURE) {
 const path=process.env.LSF_TYPESCRIPT_PARTIAL_BINDING_CAPTURE.replace(/\.[^./\\]+$/,'.zero.js');
 const actual=await readFile(path,'utf8');assert(Buffer.byteLength(actual)<=256*1024);
 const generated=fuseNativeImportAwaits(explicitResourceOwners(actual),parse);
 assert(generated.endsWith('__lsfImports.beginOwnPlans(2, 0, 0);\n'));
 assert(!generated.includes('__lsfImports.attachOwn('));
}

assert.throws(()=>staticOwnBindings(prefix+prefix,parse),/shape-drift/);
assert.throws(()=>staticOwnBindings(prefix+'__lsfImports.beginOwnPlans(2,0,0);',parse),/shape-drift/);
const slot={offset:0,resource:3,registry:'x',class:'Y'};
for(const plan of [{key:0,bytes:4,raw:5,slots:Array(65).fill(slot)},
 {key:0,bytes:3,raw:5,slots:[slot]}, {key:0,bytes:4,raw:5,slots:[slot,slot]}]) {
 const source=prefix+`async function candidate(){/* lsf-own-plan-v2:${JSON.stringify(plan)} */}`;
 assert.throws(()=>staticOwnBindings(source,parse),/shape-drift/);
}
""")


if __name__ == '__main__':
    unittest.main()
