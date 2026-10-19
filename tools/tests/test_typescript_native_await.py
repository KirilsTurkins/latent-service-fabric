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
        if node is None or parser is None:
            self.skipTest('Node and captured compiler Acorn are required for native binding controls')
        self.assertTrue(Path(parser).is_file())
        imports = "import assert from 'node:assert/strict';\nimport vm from 'node:vm';\n"
        imports += "import {readFile} from 'node:fs/promises';\nimport {createHash} from 'node:crypto';\n"
        imports += f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        imports += f"import {{fuseNativeImportAwaits}} from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};\n"
        imports += f"const fixture=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures/typescript_native_open_binding.json').as_uri())}),'utf8'));\n"
        imports += "assert.equal(createHash('sha256').update(fixture.source).digest('hex'),fixture.sourceSha256);\n"
        imports += "const original='const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\\n'+fixture.source;\n"
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
 class ComponentError extends Error {constructor(payload){super('typed-error');this.payload=payload;}}
 const bridge={reserve(...args){events.push(['reserve',...args.slice(0,3)]);return 7;},
  lift(id){events.push(['lift',id]);if(mode==='lift-failure')throw reason;assert.equal(id,7);return 512;},
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
  finalizationRegistry_import$streaming_0_3_0$upload:{register(_v,handle){events.push(['resource',handle]);}},ComponentError};
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
  else {view.setUint8(512,mode==='typed-failure'?1:0);view.setInt32(516,mode==='typed-failure'?12:42,true);pending.resolve(7);}
  if(mode==='success'){const value=await result;assert.equal(Object.getPrototypeOf(value),Upload.prototype);assert.equal(value[symbol],42);}
  else if(mode==='typed-failure')await assert.rejects(result,e=>e.payload.tag==='uncertain');
  else await assert.rejects(result,e=>e===reason);
 }
 assert.equal(events.filter(e=>e[0]==='finish').length,1);
 assert.deepEqual(events.at(-1),['finish',7]);
 return events.filter(e=>!['lift','wrapper-exit'].includes(e[0]));
}
for(const mode of ['success','native-failure','lift-failure','typed-failure','lowering-failure']){
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
 ['const __lsfImports = contentGlobal.__lsfAsyncImportBridge;','const __lsfImports = unreviewedBridge;'],
 ]) {assert(original.includes(before));assert.throws(()=>fuseNativeImportAwaits(original.replace(before,after),parse),/shape-drift/);}
assert.throws(()=>fuseNativeImportAwaits(original+';__lsfAwaitImport(1);',parse),/shape-drift/);
""")


if __name__ == '__main__':
    unittest.main()
