"""Host source/protocol controls, never native owner or signed Socket evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.typescript_guest import net_profile

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNodeNet(unittest.TestCase):
    def javascript(self, body, *, parser=False):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for host-only Socket controls')
        code = "import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';import {createHash} from 'node:crypto';\n"
        for names, path in (
            ('createNodeNetModule', net_profile.BACKEND),
            ('createNodeNetTransport', net_profile.TRANSPORT),
            ('nodeNetBindings,NET_PROFILE,NET_PRIVATE', net_profile.BINDINGS),
            ('Buffer', 'tools/typescript_guest/node_buffer.mjs')):
            code += f'import {{{names}}} from {json.dumps((ROOT/path).as_uri())};\n'
        if parser:
            frontend = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
            selected = os.environ.get('LSF_TYPESCRIPT_ACORN') or (
                str(Path(frontend)/'node_modules/acorn/dist/acorn.mjs') if frontend else None)
            if selected:
                code += f'import {{parse}} from {json.dumps(Path(selected).as_uri())};\n'
            else:
                # Mechanism fallback only. Production and owning qualification
                # require the normal pinned compiler parser, without fallback.
                code += "const {parse}=(()=>{const scope={};vm.runInNewContext(process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'],scope);return scope.acorn;})();\n"
            code += self.captured_source()
        code += """
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const turn=()=>new Promise(resolve=>setTimeout(resolve,0));
const target=()=>({Promise,Error,Uint8Array,queueMicrotask,setTimeout,clearTimeout});
const settled=value=>({promise:Promise.resolve(value),borrowReleased:Promise.resolve(),cancel(){return Promise.resolve()}});
// Host-control convenience only; production Socket uses fixed callbacks, not
// these Promise adapters around the private stop/close protocol.
const stopped=(transport,token)=>new Promise((yes,no)=>transport.stop(token,result=>result.failed?no(result.fault):yes()));
const consumed=(transport,token)=>new Promise((yes,no)=>transport.close(token,result=>result.borrowFailed?no(result.borrowFault):result.logicalFailed?no(result.logicalFault):yes()));
function fixture(overrides={}) {
 const calls=[],connection={},t=target();let drops=0;
 const native={connect:()=>{calls.push('connect');return settled(connection)},
 read:()=>settled(undefined),write:(_,bytes)=>settled(bytes.length),ready:()=>settled({writable:true}),
 chunkBytes:()=>settled(new Uint8Array([65,66])),shutdown:()=>{calls.push('shutdown');return settled({})},
 close:()=>{calls.push('close');return settled({})},...overrides};
 const transport=createNodeNetTransport(native,t,()=>({}));
 const net=createNodeNetModule(transport,Buffer,()=>false,t);
 const chunk={[Symbol.dispose](){++drops}};
 return {calls,connection,t,transport,net,chunk,get drops(){return drops}};
}
"""
        result = subprocess.run([node, '--input-type=module', '-e', code + body],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def captured_source(self):
        return f"""
import {{coreIntegerLowering}} from {json.dumps((ROOT/'tools/typescript_guest/signed64.mjs').as_uri())};
import {{explicitResourceOwners}} from {json.dumps((ROOT/'tools/typescript_guest/resources.mjs').as_uri())};
import * as a from {json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())};
async function capturedInitializer() {{
 const proof=JSON.parse(await readFile({json.dumps(str(ROOT/'tools/tests/fixtures/typescript_node_net_generated.json'))},'utf8'));
 const raw=proof.source;
 assert.equal(Buffer.byteLength(raw),proof.bytes);
 assert.equal(createHash('sha256').update(raw).digest('hex'),proof.sha256);
 let original=explicitResourceOwners(coreIntegerLowering(raw));
 original=a.retireGeneratedTaskSlots(a.lazySyncImportWaiters(original));
 original=a.nativeCarrierImports(a.fuseNativeImportAwaits(a.directIdleTaskSlots(original),parse),parse);
 const changed=nodeNetBindings(original,parse,NET_PROFILE,proof.exports);
 return {{proof,original,changed,script:a.applicationRealmImportPromises(changed)}};
}}
"""

    def captured_ack_fixture(self):
        # Actual authenticated initializer and typed wrappers, with explicitly
        # doubled core operations/bridge ACKs; never native Task qualification.
        return r"""
async function ackFixture(failureKind, faultMode) {
const {script}=await capturedInitializer(),modules=new Map(),memory={buffer:new ArrayBuffer(65536)},view=new DataView(memory.buffer);
let sequence=0,allocated=16000,reads=0,drops=0;const records=new Map(),events=[],ackGets={read:[],chunkBytes:[]};
const originalFault=Object.freeze({originalFault:true});
const content={Promise,Error,TextEncoder,TextDecoder,Uint8Array,queueMicrotask,setTimeout,clearTimeout};
content.__lsfAsyncImportBridge={reserve(){const id=++sequence;records.set(id,{id,ack:deferred(),handle:Object.freeze({id})});return id},
 watchBorrow(id){return records.get(id).handle},lift(value){return value},delivered(id,value){return value},
 finish(id){const r=records.get(id);r.finished=true;events.push('finish:'+r.kind);if(!['read','chunkBytes'].includes(r.kind)&&(!faultMode||faultMode==='hold-close'&&r.kind!=='close'))r.ack.resolve()},
 borrowReleased(handle){if(faultMode==='setup')throw originalFault;return records.get(handle.id).ack.promise},cancelBorrow(handle){const r=records.get(handle.id);events.push('cancel:'+r.kind);if(faultMode==='distinct-cancel'){r.cancelAck??=deferred();return r.cancelAck.promise}return r.ack.promise}};
function result(kind,id){const r=records.get(id);r.kind=kind;events.push('start:'+kind);r.ptr=128+id*64;new Uint8Array(memory.buffer,r.ptr,64).fill(0);return r.ptr}
const bindings=[memory,(_p,_old,_align,n)=>{const p=allocated;allocated+=n;return p},
 id=>{const p=result('connect',id);view.setInt32(p+4,7,true);return Promise.resolve(p)},
 id=>{const p=result('read',id);assert.equal(reads++,0);if(failureKind!=='eof'){view.setUint8(p+4,1);view.setInt32(p+8,11,true)}return failureKind==='read'?Promise.reject(Error('original-read-failure')):Promise.resolve(p)},
 (id,_handle,_bytes,n)=>{const p=result('write',id);view.setUint32(p+4,n,true);return Promise.resolve(p)},
 ()=>{throw Error('no readiness call in this profile')},
 id=>{const p=result('chunkBytes',id);view.setUint32(p+4,14000,true);view.setUint32(p+8,2,true);new Uint8Array(memory.buffer,14000,2).set([65,66]);return failureKind==='chunkBytes'?Promise.reject(Error('original-copy-failure')):Promise.resolve(p)},
 ()=>{throw Error('no inspect call')},
 id=>{const p=result('shutdown',id);view.setUint8(p+8,2);return Promise.resolve(p)},
 id=>{const p=result('close',id);view.setUint8(p+8,5);return Promise.resolve(p)},
 ...Array(10).fill(()=>0),()=>{throw Error('no connection destructor')},()=>{++drops;events.push('drop:chunk')}];
assert.equal(bindings.length,22);
const context=vm.createContext({contentGlobal:content,$bindings:bindings,defineBuiltinModule(name,value){modules.set(name,value)},TextEncoder,TextDecoder,console,__faultArm:false,__faultMode:faultMode,__originalFault:originalFault});
// Test-only intrinsic fault injection BEFORE the authentic factory captures it;
// arm only after logical connect. No application mutation/physical-cost claim.
vm.runInContext(`const originalIndexOf=Array.prototype.indexOf;Array.prototype.indexOf=function(...args){
 if(globalThis.__faultArm){if(globalThis.__faultMode==='identity')return -1;if(globalThis.__faultMode==='intrinsic')throw globalThis.__originalFault;}
 return Reflect.apply(originalIndexOf,this,args);
};`,context);
vm.runInContext(script,context,{timeout:3000});
const original=modules.get(NET_PRIVATE),facade={};
for(const name of Object.keys(original))facade[name]=(...args)=>{
 if(Object.hasOwn(ackGets,name)) {
  const index=name==='read'?3:2,callback=args[index];
  if(typeof callback==='function')args[index]=function(record){
   ackGets[name].push(record);events.push('joined:'+name);
   assert(record.logicalDone&&(record.borrowDone||record.borrowFailed));
   return Reflect.apply(callback,this,[record]);
  };
 }
 return Reflect.apply(original[name],original,args);
};
const net=createNodeNetModule(Object.freeze(facade),Buffer,()=>false,content);
return {net,original,records,events,ackGets,originalFault,armFault(){context.__faultArm=true},get drops(){return drops},
 runApplication(fn){context.__application=fn;vm.runInContext('api100Run=__application;',context);
  const name=parse(script,{ecmaVersion:'latest',sourceType:'module'}).body.find(node=>node.id?.name.startsWith('export_')).id.name;
  return context[name](0,123,0)}};
}
"""

    def test_captured_read_and_copy_ack_are_awaited_once_after_success(self):
        self.javascript(self.captured_ack_fixture() + r"""
const f=await ackFixture(),closed=deferred();let data;
const socket=f.net.connect(12345,'127.0.0.1');
socket.on('error',closed.reject).once('close',closed.resolve).on('data',bytes=>{data=bytes.toString();socket.pause();socket.destroy()});
for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
assert.equal(data,undefined);assert.equal(f.drops,0);assert.equal(f.ackGets.chunkBytes.length,0);
read.ack.resolve();
for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='chunkBytes');++i)await turn();
const copy=[...f.records.values()].find(r=>r.kind==='chunkBytes');assert(copy?.finished);
assert.equal(data,undefined);assert.equal(f.drops,0);
copy.ack.resolve();await closed.promise;
assert.equal(data,'AB');assert.equal(f.drops,1);f.original.assertEmpty();
assert.equal(f.ackGets.read.length,1);assert.equal(f.ackGets.chunkBytes.length,1);
assert([...f.records.values()].every(r=>r.finished));
""", parser=True)

    def test_captured_failed_read_or_copy_still_waits_original_ack_before_cleanup(self):
        self.javascript(self.captured_ack_fixture() + r"""
for(const failureKind of ['read','chunkBytes']) {
 const f=await ackFixture(failureKind),closed=deferred();let reported;
 const socket=f.net.connect(12345,'127.0.0.1');
 socket.on('error',cause=>{reported=cause}).once('close',closed.resolve).on('data',()=>assert.fail('failed operation cannot deliver'));
 for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
 const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
 if(failureKind==='chunkBytes') {
  read.ack.resolve();
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='chunkBytes');++i)await turn();
 }
 const pending=[...f.records.values()].find(r=>r.kind===failureKind);assert(pending?.finished);
 assert.equal(reported,undefined);assert.equal(f.drops,0);
 assert.equal([...f.records.values()].filter(r=>r.kind==='close').length,0);
 assert.equal(f.ackGets[failureKind].length,0);
 pending.ack.resolve();await closed.promise;
 assert.equal(f.ackGets[failureKind].length,1);
 assert.equal(reported.code,'EIO');assert.equal(reported.syscall,'read');
 assert.equal(f.drops,failureKind==='chunkBytes'?1:0);f.original.assertEmpty();
 assert([...f.records.values()].every(r=>r.finished));
}
""", parser=True)

    def test_actual_ack_observation_faults_never_certify_release_or_empty_registry(self):
        self.javascript(self.captured_ack_fixture() + r"""
for(const mode of ['ack-error','ack-undefined','setup','identity','intrinsic','unconfirmed']) {
 const f=await ackFixture(undefined,mode),token=f.original.reserve();
 const op=f.original.connect(token,{host:'127.0.0.1',port:12345,transport:'tcp',timeoutMillis:undefined});
 await op.promise;const record=[...f.records.values()].find(r=>r.kind==='connect');assert(record?.finished);
 let fault;
 if(mode==='unconfirmed') {
  try{op.assertBorrowReleased();assert.fail('early assertion must refuse')}catch(error){fault=error}
  assert.match(fault.message,/borrow-release-unconfirmed/);
 }
 if(mode==='identity'||mode==='intrinsic')f.armFault();
 if(mode==='ack-error')record.ack.reject(f.originalFault);
 else if(mode==='ack-undefined')record.ack.reject(undefined);
 else record.ack.resolve();
 await op.borrowSettlement; // Observation completion is deliberately NOT proof.
 let threw=false;
 try{op.assertBorrowReleased()}catch(error){threw=true;if(mode==='identity')assert.match(error.message,/operation-registry-identity/);
  else if(mode==='unconfirmed')assert.equal(error,fault);
  else assert.equal(error,mode==='ack-undefined'?undefined:f.originalFault);fault=error;}
 assert.equal(threw,true);let repeated=false;
 try{op.assertBorrowReleased()}catch(error){repeated=true;assert.equal(error,fault)}assert.equal(repeated,true);
 assert.throws(f.original.assertEmpty,/unclosed/);
 await assert.rejects(stopped(f.original,token),error=>error===fault);
 assert.equal([...f.records.values()].filter(r=>r.kind==='close').length,0);assert.equal(f.drops,0);
}
for(const failedKind of ['read','chunkBytes']) {
 const f=await ackFixture(undefined,'ack-held'),closed=deferred();let error,delivered=false;
 const socket=f.net.connect(12345,'127.0.0.1');
 socket.on('error',value=>{error=value}).once('close',closed.resolve).on('data',()=>{delivered=true});
 for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='connect');++i)await turn();
 [...f.records.values()].find(r=>r.kind==='connect').ack.resolve();
 for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
 const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
 if(failedKind==='chunkBytes') {
  read.ack.resolve();
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='chunkBytes');++i)await turn();
 }
 const failed=[...f.records.values()].find(r=>r.kind===failedKind);assert(failed?.finished);
 assert.equal(delivered,false);assert.equal(f.drops,0);
 failed.ack.reject(f.originalFault);await closed.promise;
 assert.equal(error.code,'EIO');assert.equal(error.cause,f.originalFault);
 assert.equal(delivered,false);assert.equal(f.drops,0);
 assert.equal([...f.records.values()].filter(r=>r.kind==='close').length,0);
 assert.throws(f.original.assertEmpty,/unclosed/);
}
""", parser=True)

    def test_one_ack_observer_removes_unused_reaction_and_captures_setup_resolver(self):
        self.javascript(r"""
const P=vm.runInNewContext('Promise'),oldThen=P.prototype.then,oldResolve=P.resolve;
let reactions=0,mutators=0;P.prototype.then=function(...args){++reactions;return Reflect.apply(oldThen,this,args)};
const t={Promise:P},ack=deferred(),originalFault=Object.freeze({originalFault:true});
let setup=false;
const native={connect(){return {promise:Promise.resolve({}),get borrowReleased(){if(setup)throw originalFault;return ack.promise},cancel(){return ack.promise}}},
 close:()=>settled({})};
const transport=createNodeNetTransport(native,t,()=>({})),token=transport.reserve(),op=transport.connect(token,{});
assert.equal(reactions,2); // Logical observer + original ACK observer; no sink.
await op.promise;let observed=false;op.borrowSettlement.then(()=>observed=true);await turn();assert.equal(observed,false);
ack.resolve();await op.borrowSettlement;op.assertBorrowReleased();await stopped(transport,token);await consumed(transport,token);transport.assertEmpty();
setup=true;P.resolve=function(){++mutators;throw Error('application resolver mutation')};
const failed=transport.connect(transport.reserve(),{});await failed.promise;await failed.borrowSettlement;
assert.throws(failed.assertBorrowReleased,error=>error===originalFault);assert.equal(mutators,0);
assert.throws(transport.assertEmpty,/unclosed/);
P.resolve=oldResolve;
""")

    def test_falsey_write_ack_fault_is_failure_and_nonfalsey_identity_is_original(self):
        self.javascript(r"""
for(const stage of ['write','ready'])for(const reason of [undefined,false,0,'',null,Error('original-ACK-fault')]) {
 const failed=()=>({promise:Promise.resolve(stage==='write'?1:{writable:true}),borrowReleased:Promise.reject(reason),cancel(){return Promise.resolve()}});
 const f=fixture(stage==='write'?{write:failed}:{write:()=>settled(0),ready:failed});
 const done=deferred(),socket=f.net.connect(12345,'127.0.0.1');let callbackError,eventError;
 socket.on('error',value=>{eventError=value}).once('close',done.resolve);
 socket.once('connect',()=>socket.write('x',value=>{callbackError=value}));await done.promise;
 if(reason){assert.equal(callbackError,reason);assert.equal(eventError,reason)}
 else {assert.equal(callbackError.code,'EIO');assert(Object.hasOwn(callbackError,'cause'));assert.equal(callbackError.cause,reason);assert.equal(eventError,callbackError)}
 assert.equal(f.calls.includes('close'),false);assert.throws(f.transport.assertEmpty,/unclosed/);
}
""")

    def test_callback_join_user_throws_escape_original_and_caught_emit_is_not_poison(self):
        self.javascript(r"""
for(const event of ['connect','data','write','finish','drain','end','timeout']) {
 const fault=event==='end'?undefined:Object.freeze({originalUserFault:event});let observed=false,original;
 const capture=value=>{observed=true;original=value};process.once('unhandledRejection',capture);process.once('uncaughtException',capture);
 const held=deferred(),ack=deferred();let read=0,f;
 f=fixture({read:()=>event==='data'?settled(read++?undefined:f.chunk):event==='end'?settled(undefined):
   {promise:held.promise,borrowReleased:ack.promise,cancel(){return ack.promise}}});
 const socket=new f.net.Socket({highWaterMark:1});let translated=false;
 socket.on('error',()=>{translated=true});
 if(event==='timeout'){socket.once('connect',()=>socket.setTimeout(1));socket.on('timeout',()=>{socket.destroy();throw fault})}
 else if(event==='write')socket.once('connect',()=>socket.write('x',()=>{throw fault}));
 else if(event==='finish'||event==='drain') {
  socket.on(event,()=>{throw fault});socket.once('connect',()=>event==='finish'?socket.end('x'):socket.write('xx'));
 } else socket.on(event,()=>{throw fault});
 if(event==='data'||event==='end')socket.resume();
 socket.connect(12345,'127.0.0.1');
 for(let i=0;i<32&&!observed;++i)await turn();
 assert.equal(observed,true,event);assert.equal(original,fault);assert.equal(translated,false);
 assert.equal(f.calls.includes('close'),false);assert.throws(f.transport.assertEmpty,/unclosed/);
 process.removeListener('unhandledRejection',capture);process.removeListener('uncaughtException',capture);
}
// A buffered resume job has its OWN tail, beyond the nested data listener.
{
 const held=deferred(),started=deferred(),fault={bufferedResumeFault:true};let f,read=0,seen=false,original;
 const capture=value=>{seen=true;original=value};process.once('uncaughtException',capture);
 f=fixture({read(){if(read++)return settled(undefined);started.resolve();return {promise:held.promise,borrowReleased:Promise.resolve(),cancel(){return Promise.resolve()}}}});
 const socket=f.net.connect(12345,'127.0.0.1');socket.on('error',()=>assert.fail('user throw cannot become EIO'));
 socket.on('data',()=>{socket.destroy();throw fault});await started.promise;socket.pause();held.resolve(f.chunk);
 for(let i=0;i<16&&f.drops===0;++i)await turn();assert.equal(f.drops,1);assert.equal(seen,false);
 socket.resume();for(let i=0;i<32&&!seen;++i)await turn();assert.equal(seen,true);assert.equal(original,fault);
 assert.equal(f.calls.includes('close'),false);assert.throws(f.transport.assertEmpty,/unclosed/);process.removeListener('uncaughtException',capture);
}
const f=fixture(),done=deferred(),socket=f.net.connect(12345,'127.0.0.1'),fault={caught:true};
socket.on('error',done.reject).once('close',done.resolve);
socket.on('ready',()=>{throw fault});socket.once('timeout',()=>{
 let caught=false;try{socket.emit('ready')}catch(value){caught=true;assert.equal(value,fault)}assert(caught);
 socket.removeAllListeners('ready');socket.end();
});
socket.once('connect',()=>socket.emit('timeout'));socket.resume();await done.promise;f.transport.assertEmpty();
// A top-level synchronous emit caught by its caller is not permanent poison.
const g=fixture(),other=new g.net.Socket();other.on('timeout',()=>{throw fault});
assert.throws(()=>other.emit('timeout'),value=>value===fault);g.transport.assertEmpty();
""")

    def test_actual_initializer_join_retains_reentrant_and_distinct_cancel_notification_tails(self):
        self.javascript(self.captured_ack_fixture() + r"""
const syntax=parse(createNodeNetModule.toString(),{ecmaVersion:'latest',sourceType:'module'});
let workers=0,awaits=0;
function walk(node){if(!node||typeof node!=='object')return;if(node.async)++workers;if(node.type==='AwaitExpression')++awaits;
 for(const value of Object.values(node)){if(Array.isArray(value))value.forEach(walk);else if(value&&typeof value==='object')walk(value)}}
walk(syntax);assert.equal(workers,0);assert.equal(awaits,0); // No private worker fanout; no physical Task claim.
for(const event of ['connect','data','finish']) {
 const f=await ackFixture(undefined,event==='finish'?'distinct-cancel':undefined),done=deferred();
 const socket=f.net.connect(12345,'127.0.0.1');let tail=false;
 socket.on('error',done.reject).once('close',()=>{
  assert.equal(tail,true);assert.throws(f.original.assertEmpty,/unclosed/);done.resolve();
 });
 socket.once(event,()=>{
  assert.equal(socket.destroy(),socket);
  assert.equal([...f.records.values()].filter(r=>r.kind==='close').length,0);
  assert.throws(f.original.assertEmpty,/unclosed/);f.events.push('listener-tail:'+event);tail=true;
 });
 if(event==='finish')socket.once('connect',()=>socket.end('q'));
 socket.on('data',()=>{});
 if(event==='finish') {
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='connect');++i)await turn();
  [...f.records.values()].find(r=>r.kind==='connect').ack.resolve();
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='write');++i)await turn();
  [...f.records.values()].find(r=>r.kind==='write').ack.resolve();
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='shutdown');++i)await turn();
  [...f.records.values()].find(r=>r.kind==='shutdown').ack.resolve();
 }
 if(event==='data'||event==='finish') {
  for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
  const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
  read.ack.resolve();
  if(event==='data') {
   for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='chunkBytes');++i)await turn();
   [...f.records.values()].find(r=>r.kind==='chunkBytes').ack.resolve();
  } else {
   for(let i=0;i<16&&!read.cancelAck;++i)await turn();assert(read.cancelAck);
   await turn();assert.equal([...f.records.values()].filter(r=>r.kind==='close').length,0);
   read.cancelAck.resolve();
   for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='close');++i)await turn();
   const close=[...f.records.values()].find(r=>r.kind==='close');assert(close?.finished);close.ack.resolve();
  }
 }
 await done.promise;await turn();f.original.assertEmpty();
 assert(f.events.indexOf('start:close')>f.events.indexOf('listener-tail:'+event));
 assert.equal(f.drops,event==='connect'?0:1);
}
""", parser=True)

    def test_real_node_reference_empty_write_and_reentrant_close_observables(self):
        self.javascript(r"""
const real=await import('node:net');
async function reference(mode) {
 const events=[],server=real.createServer(peer=>{
  peer.on('error',()=>{});peer.on('data',()=>{});peer.on('end',()=>peer.end());
  if(mode==='data')peer.write('A');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const socket=new real.Socket(),done=deferred();
 socket.on('error',done.reject).once('close',()=>{events.push('close');done.resolve()});
 const destroy=()=>{assert.equal(socket.destroy(),socket);events.push('destroy-return');events.push('listener-tail')};
 try {
  if(mode==='data')socket.once('data',destroy);
  if(mode==='finish')socket.once('finish',destroy);
  socket.once('connect',()=>{
   events.push('connect');
   if(mode==='connect')destroy();
   else if(mode==='finish')socket.end('x');
   else if(mode==='empty') {
    socket.once('finish',()=>events.push('finish'));
    socket.write('',()=>{events.push('empty-callback');socket.end('x',()=>events.push('end-callback'))});
    events.push('write-return');
   }
  });
  socket.resume();socket.connect(server.address().port,'127.0.0.1');events.push('connect-return');
  await done.promise;
  assert(events.indexOf('connect-return')<events.indexOf('connect'));
  if(mode==='empty') {
   assert(events.indexOf('write-return')<events.indexOf('empty-callback'));
   assert(events.indexOf('finish')<events.indexOf('close'));assert(events.indexOf('end-callback')<events.indexOf('close'));
  } else assert(events.indexOf('listener-tail')<events.indexOf('close'));
 } finally {socket.destroy();await new Promise(resolve=>server.close(resolve))}
}
for(const mode of ['empty','connect','data','finish'])await reference(mode);
// The finite guest module promises these SAME observable partial orders.
const f=fixture(),events=[],done=deferred(),socket=f.net.connect(12345,'127.0.0.1');events.push('connect-return');
socket.on('error',done.reject).once('close',()=>{events.push('close');done.resolve()});
socket.once('connect',()=>{events.push('connect');socket.write('',()=>{events.push('empty-callback');socket.end('x',()=>events.push('end-callback'))});events.push('write-return')});
socket.once('finish',()=>events.push('finish'));socket.resume();await done.promise;
for(const [before,after] of [['connect-return','connect'],['write-return','empty-callback'],['finish','close'],['end-callback','close']])
 assert(events.indexOf(before)>=0&&events.indexOf(before)<events.indexOf(after));
f.transport.assertEmpty();
// The selected port's finite16 bound also retains queued empty callback records.
const g=fixture(),connected=deferred(),closed=deferred(),limited=g.net.connect(12345,'127.0.0.1');
limited.on('error',closed.reject).once('connect',connected.resolve).once('close',closed.resolve);await connected.promise;
let callbacks=0;for(let i=0;i<16;++i)limited.write('',()=>{++callbacks});
assert.throws(()=>limited.write('',()=>{}),/RESOURCE_EXHAUSTED/);assert.equal(callbacks,0);
await turn();assert.equal(callbacks,16);limited.resume();limited.end();await closed.promise;g.transport.assertEmpty();
""")

    def test_held_read_allows_sibling_partial_write_copy_then_normal_close(self):
        self.javascript(r"""
const held=deferred(),ack=deferred(),started=deferred(),bytes=new Uint8Array([65,66]);
const written=[];let read=0,drops=0;
const chunk={[Symbol.dispose](){++drops;bytes.fill(0)}};
const f=fixture({read(){if(read++===0){started.resolve();return {promise:held.promise,borrowReleased:ack.promise,cancel(){held.reject(Error('cancel'));return ack.promise}}}return settled(undefined)},
 write(_,part){written.push([...part]);return settled(Math.min(part.length,2))},chunkBytes:()=>settled(bytes)});
const socket=f.net.connect(32123,'127.0.0.1'),closed=deferred(),events=[];let copied;
socket.on('error',closed.reject).once('close',had=>{assert.equal(had,false);events.push('close');closed.resolve()});
socket.on('data',value=>{copied=value;events.push('data');socket.end()});
socket.on('finish',()=>events.push('finish')).on('end',()=>events.push('end'));
await started.promise;
await new Promise((resolve,reject)=>socket.write('abc',error=>error?reject(error):resolve()));
assert.deepEqual(written,[[97,98,99],[99]]);assert.throws(f.t.__lsfNodeNetRootCheck,/unclosed/);
held.resolve(chunk);ack.resolve();await closed.promise;
assert.equal(copied.toString(),'AB');assert.equal(drops,1);assert.equal(socket.bytesWritten,3);
assert.equal(events[0],'data');assert.equal(events.at(-1),'close');f.t.__lsfNodeNetRootCheck();
""")

    def test_destroy_keeps_registry_until_original_borrow_ack_and_consuming_close(self):
        self.javascript(r"""
const held=deferred(),ack=deferred(),started=deferred(),closeAck=deferred();let cancelled=0,closeStarted=0;
const f=fixture({read(){started.resolve();return {promise:held.promise,borrowReleased:ack.promise,cancel(){++cancelled;held.reject(Error('logical cancel'));return ack.promise}}},
 close(){++closeStarted;return {promise:Promise.resolve({}),borrowReleased:closeAck.promise,cancel(){return closeAck.promise}}}});
const socket=f.net.connect(32123,'localhost'),closed=deferred();socket.on('error',closed.reject).on('close',closed.resolve).on('data',()=>{});
await started.promise;assert.equal(socket.destroy(),socket);await turn();
assert.equal(cancelled,1);assert.equal(closeStarted,0);assert.equal(socket.closed,true);
assert.throws(f.t.__lsfNodeNetRootCheck,/unclosed/);ack.resolve();await turn();
assert.equal(closeStarted,1);assert.throws(f.t.__lsfNodeNetRootCheck,/unclosed/);
closeAck.resolve();await closed.promise;assert.equal(socket.closed,true);f.t.__lsfNodeNetRootCheck();
""")

    def test_ack_or_consuming_close_refusal_never_certifies_empty_registry(self):
        self.javascript(r"""
for(const failed of ['ack','close']) {
 const f=fixture(failed==='ack'?{connect:()=>({promise:Promise.resolve({}),borrowReleased:Promise.reject(Error('ack refusal')),cancel(){}})}:
   {close:()=>({promise:Promise.reject(Error('close refusal')),borrowReleased:Promise.resolve(),cancel(){}})});
 const socket=f.net.connect(32123,'localhost'),closed=deferred();let errors=0;
 socket.on('error',()=>++errors).on('close',closed.resolve);
 if(failed==='close'){await turn();socket.destroy()}
 await closed.promise;assert.equal(socket.closed,true);assert.equal(errors,1);
 assert.throws(f.t.__lsfNodeNetRootCheck,/unclosed/);
}
""")

    def test_port_limit_foreign_tokens_and_immutable_same_registry_check(self):
        self.javascript(r"""
const f=fixture(),one=f.transport.reserve(),two=f.transport.reserve();
assert.throws(()=>f.transport.reserve(),/port-limit/);assert.throws(()=>f.transport.connect({},{}),/foreign/);
assert.throws(()=>{f.t.__lsfNodeNetRootCheck=()=>{}},TypeError);
assert.throws(()=>Object.defineProperty(f.t,'__lsfNodeNetRootCheck',{value:()=>{}}),TypeError);
assert.throws(()=>{f.transport.assertEmpty=()=>{}},TypeError);
const old=Array.prototype.splice;Array.prototype.splice=()=>[];
try {assert.throws(f.transport.assertEmpty,/unclosed/)} finally {Array.prototype.splice=old}
for(const token of [one,two]){const op=f.transport.connect(token,{});await op.promise;await op.borrowSettlement;op.assertBorrowReleased();await stopped(f.transport,token);await consumed(f.transport,token)}
f.transport.assertEmpty();assert.throws(()=>f.transport.connect(one,{}),/retired/);
""")

    def test_uncertain_write_never_replays_and_preserves_known_prefix(self):
        self.javascript(r"""
for(const nativeFlag of [true,false]) {
let writes=0;const failure=Object.assign(Error('unknown result'),{payload:{code:'uncertain',acceptedPrefixBytes:1,mayHaveApplied:nativeFlag}});
const f=fixture({write(){if(++writes===1)return settled(2);return {promise:Promise.reject(failure),borrowReleased:Promise.resolve(),cancel(){}}}});
const socket=f.net.connect(32123,'localhost'),closed=deferred();let callback,error;
socket.on('error',value=>error=value).on('close',closed.resolve);
socket.write('abcd',value=>callback=value);await closed.promise;
assert.equal(writes,2);assert.equal(error,callback);assert.equal(error.code,'ERR_LSF_UNCERTAIN');
assert.equal(error.acceptedPrefixBytes,3);assert.equal(error.nativeAcceptedPrefixBytes,1);
assert.equal(error.mayHaveApplied,true);assert.equal(error.nativeMayHaveApplied,nativeFlag);
assert.equal(socket.bytesWritten,3);f.transport.assertEmpty();
}
""")

    def test_zero_progress_waits_real_writable_hint_and_backpressure_drains(self):
        self.javascript(r"""
const sequence=[];let writes=0;
const f=fixture({write(_,bytes){sequence.push('write');return settled(++writes===1?0:bytes.length)},ready(){sequence.push('ready');return settled({writable:true})}});
const socket=new f.net.Socket({highWaterMark:2}),events=[];socket.connect(32123,'localhost');
const done=deferred();socket.on('error',done.reject).on('drain',()=>{events.push('drain');socket.destroy()}).on('close',done.resolve);
assert.equal(socket.write('ab',error=>{assert.equal(error,undefined);events.push('written')}),false);
await done.promise;assert.deepEqual(sequence,['write','ready','write']);assert.deepEqual(events,['written','drain']);f.transport.assertEmpty();
""")

    def test_actual_captured_initializer_and_export_guard_fail_closed(self):
        self.javascript(f"""
const {{proof,original,changed}}=await capturedInitializer();
assert.equal(nodeNetBindings(original,()=>{{throw Error('must not parse')}},undefined),original);
const tree=parse(changed,{{ecmaVersion:'latest',sourceType:'module'}});
const run=tree.body.find(node=>node.id?.name===proof.exports[0][0]);
const guarded=run.body.body.find(node=>node.type==='TryStatement');
assert.equal(guarded.block.body.length,4);
assert.equal(guarded.block.body[1].expression.right.callee.property.name,'beginAcceptedClose');
assert.equal(guarded.block.body[2].consequent.expression.type,'AwaitExpression');
assert.equal(guarded.block.body[3].expression.callee.name,'__lsfNodeNetRootCheck');
assert.equal(guarded.handler.body.body[3].expression.callee.property.name,'exit');
for(const altered of [original.replace(/ret = await +_withGlobalCurrentTaskMetaAsync/,'ret = await changedWrapper'),
 original.slice(0,original.indexOf('async function '+proof.exports[0][0]))+
 original.slice(original.indexOf('async function '+proof.exports[0][0])).replace('task.setErrored(err);','task.otherError(err);'),
 'import x from "x";\\n'+original,
 original.replace('errMsg: taskErr.message','errMsg: other.message')])
 {{assert.notEqual(altered,original);assert.throws(()=>nodeNetBindings(altered,parse,NET_PROFILE,proof.exports),/shape/);}}
const modules=new Map(),content={{Promise,TextEncoder,TextDecoder,__lsfAsyncImportBridge:{{}}}};
const scope={{contentGlobal:content,$bindings:[{{buffer:new ArrayBuffer(65536)}},()=>0,...Array(22).fill(()=>0)],
 defineBuiltinModule(name,exports){{modules.set(name,exports)}},TextEncoder,TextDecoder,console}};
vm.runInNewContext(a.applicationRealmImportPromises(changed),scope,{{timeout:3000}});
assert(modules.has(NET_PRIVATE));modules.get(NET_PRIVATE).assertEmpty();
const token=modules.get(NET_PRIVATE).reserve();assert.throws(content.__lsfNodeNetRootCheck,/unclosed/);
assert.throws(()=>{{content.__lsfNodeNetRootCheck=()=>{{}}}},TypeError);
assert.equal(typeof token,'object');
""", parser=True)

    def test_actual_lowering_and_original_resolve_callbacks_cannot_admit_sockets(self):
        self.javascript(r"""
const {script}=await capturedInitializer(),modules=new Map();
class Encoder extends TextEncoder {}
const content={Promise,TextEncoder:Encoder,TextDecoder,__lsfAsyncImportBridge:{}};
const memory={buffer:new ArrayBuffer(65536)};
const scope=vm.createContext({contentGlobal:content,$bindings:[memory,()=>32,...Array(22).fill(()=>0)],
 defineBuiltinModule(name,value){modules.set(name,value)},TextEncoder:Encoder,TextDecoder,console});
vm.runInContext(script,scope,{timeout:3000});
const transport=modules.get(NET_PRIVATE),attempts=[];
scope.onResult=()=>{attempts.push('onResolve');assert.throws(()=>transport.reserve(),/canonical-return-admission/)};
vm.runInContext(`const originalCreateTask=createNewCurrentTask;
createNewCurrentTask=(args)=>{const original=originalCreateTask(args);original[0].registerOnResolveHandler(onResult);return original;};
api100Run=()=> 'real string';`,scope);
Object.defineProperty(Encoder.prototype,'encode',{configurable:true,get(){
 attempts.push('lowering-getter');assert.throws(()=>transport.reserve(),/canonical-return-admission/);
 return TextEncoder.prototype.encode;
}});
await scope[proofName(script)](0,123,0);
assert.deepEqual(attempts,['lowering-getter','onResolve']);transport.assertEmpty();
// The same ORIGINAL lowering helper can throw. Its exception is preserved,
// and finally releases only this successfully acquired synchronous fence.
const marker=Error('original-lowering-error');
Object.defineProperty(Encoder.prototype,'encode',{configurable:true,get(){throw marker}});
await assert.rejects(scope[proofName(script)](0,123,0),error=>error===marker);
const owner=transport.beginRootReturn();assert.throws(()=>transport.beginRootReturn(),/nested-root-return/);
assert.throws(()=>transport.reserve(),/canonical-return-admission/);
assert.throws(()=>transport.connect({},{}),/canonical-return-admission/);
assert.throws(()=>transport.endRootReturn({}),/root-return-not-held/);
transport.endRootReturn(owner);transport.assertEmpty();
const token=transport.reserve();assert.equal(typeof token,'object');assert.throws(transport.assertEmpty,/unclosed/);
function proofName(value){return parse(value,{ecmaVersion:'latest',sourceType:'module'}).body.find(node=>node.id?.name.startsWith('export_')).id.name;}
""", parser=True)

    def test_actual_generated_root_awaits_accepted_end_eof_ack_close_and_notification_tail(self):
        self.javascript(self.captured_ack_fixture() + r"""
const f=await ackFixture('eof','hold-close');let completed=false,closeTail=false;
const root=f.runApplication(()=>new Promise((yes,no)=>{
 const socket=f.net.connect(12345,'127.0.0.1');socket.on('error',no);
 socket.once('connect',()=>{socket.end();yes('ready')});
 socket.on('close',()=>{assert.equal(completed,false);assert.throws(f.original.assertEmpty,/unclosed/);
  assert.throws(()=>f.net.connect(12345,'127.0.0.1'),/canonical-return-admission/);closeTail=true});
}));
root.then(()=>{completed=true});
for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
assert.equal(completed,false);assert.equal(closeTail,false);
assert.throws(()=>f.original.reserve(),/canonical-return-admission/);
assert.throws(()=>f.original.beginAcceptedClose(),/nested-root-return/);
assert.throws(()=>f.original.endRootReturn({}),/root-return-not-held/);
read.ack.resolve();
for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='close');++i)await turn();
const close=[...f.records.values()].find(r=>r.kind==='close');assert(close?.finished);
assert.equal(completed,false);assert.equal(closeTail,false);assert.equal(f.drops,0);
close.ack.resolve();await root;
assert.equal(completed,true);assert.equal(closeTail,true);f.original.assertEmpty();
assert([...f.records.values()].every(r=>r.finished));
""", parser=True)

    def test_accepted_close_fence_is_lazy_exact_owned_and_refuses_open_siblings(self):
        self.javascript(r"""
let allocations=0;class P extends Promise{constructor(executor){++allocations;super(executor)}}
const t={...target(),Promise:P},transport=createNodeNetTransport({},t,()=>({}));
Object.defineProperty(Object.prototype,'promise',{configurable:true,get(){throw Error('inherited promise getter')}});
let empty;try{empty=transport.beginAcceptedClose();assert.equal(empty.promise,undefined);assert.equal(Object.hasOwn(empty,'promise'),true)}
finally{delete Object.prototype.promise}assert.equal(allocations,0);
assert.throws(()=>transport.endRootReturn({}),/root-return-not-held/);
assert.throws(()=>transport.beginAcceptedClose(),/nested-root-return/);
assert.throws(()=>transport.reserve(),/canonical-return-admission/);transport.endRootReturn(empty);
const one=transport.reserve(),two=transport.reserve();transport.acceptTerminal(one);
assert.throws(()=>transport.beginAcceptedClose(),/unclosed/);
// Refused acquisition did not fence an unrelated live owner or mint success.
assert.throws(()=>transport.connect({},{}),/foreign/);assert.throws(transport.assertEmpty,/unclosed/);
transport.acceptTerminal(two);const owner=transport.beginAcceptedClose();assert(owner.promise instanceof P);
assert.equal(allocations,1);assert.throws(()=>transport.endRootReturn(empty),/root-return-not-held/);
const caught=owner.promise.then(()=>assert.fail('poison cannot complete'),error=>assert.equal(error,undefined));
transport.poison(one,undefined);await caught;assert.throws(transport.assertEmpty,/unclosed/);
transport.endRootReturn(owner);assert.throws(()=>transport.beginAcceptedClose(),error=>error===undefined);
""")

    def test_actual_generated_close_join_keeps_undefined_rejection_through_original_task_exit(self):
        self.javascript(self.captured_ack_fixture() + r"""
for(const original of [undefined,Object.freeze({get message(){throw Error('rejection getter must not run')}})]) {
const f=await ackFixture('eof','hold-close');
const root=f.runApplication(()=>new Promise((yes,no)=>{
 const socket=f.net.connect(12345,'127.0.0.1');socket.on('error',()=>{});
 socket.once('connect',()=>{socket.end();yes('ready')});
}));
const failed=assert.rejects(root,error=>error===original);
for(let i=0;i<16&&![...f.records.values()].some(r=>r.kind==='read');++i)await turn();
const read=[...f.records.values()].find(r=>r.kind==='read');assert(read?.finished);
read.ack.reject(original);await failed;assert.throws(f.original.assertEmpty,/unclosed/);
}
""", parser=True)

    def test_accepted_destroy_join_waits_distinct_cancel_and_borrow_ack_then_close_tail(self):
        self.javascript(r"""
const logical=deferred(),borrow=deferred(),cancel=deferred(),started=deferred(),closeAck=deferred();let cancels=0,closeStarts=0,tail=false;
const f=fixture({read(){started.resolve();return {promise:logical.promise,borrowReleased:borrow.promise,
 cancel(){++cancels;logical.reject(Error('original cancellation'));return cancel.promise}}},
 close(){++closeStarts;return {promise:Promise.resolve({}),borrowReleased:closeAck.promise,cancel(){return closeAck.promise}}}});
const socket=f.net.connect(12345,'127.0.0.1');socket.on('error',()=>assert.fail('cancelled read must not become error'));
socket.on('data',()=>assert.fail('cancelled read must not deliver'));socket.on('close',()=>{tail=true;assert.throws(f.transport.assertEmpty,/unclosed/)});
await started.promise;socket.destroy();const owner=f.transport.beginAcceptedClose();let complete=false;
owner.promise.then(()=>{complete=true});assert.equal(cancels,1);
borrow.resolve();await turn();assert.equal(complete,false);assert.equal(closeStarts,0);
cancel.resolve();await turn();assert.equal(complete,false);assert.equal(tail,false);assert.equal(closeStarts,1);
closeAck.resolve();await owner.promise;assert.equal(complete,true);assert.equal(tail,true);f.transport.assertEmpty();
f.transport.endRootReturn(owner);
""")

    def test_paused_end_actual_data_retains_chunk_and_refuses_instead_of_fabricating_eof(self):
        self.javascript(r"""
const logical=deferred(),ack=deferred(),started=deferred();let copied=0,reported;
const f=fixture({read(){started.resolve();return {promise:logical.promise,borrowReleased:ack.promise,cancel(){return ack.promise}}},
 chunkBytes(){++copied;assert.fail('paused end cannot discard data through an implicit copy')}});
const socket=f.net.connect(12345,'127.0.0.1');socket.on('error',()=>assert.fail('original callback fault must not become EIO'));
socket.once('connect',()=>socket.end('x'));await started.promise;
const owner=f.transport.beginAcceptedClose();const refused=owner.promise.then(()=>assert.fail('data cannot become EOF'),error=>{reported=error});
const unhandled=[];const observe=error=>unhandled.push(error);process.on('unhandledRejection',observe);
logical.resolve(f.chunk);await turn();assert.equal(reported,undefined);assert.equal(f.drops,0);assert.equal(copied,0);
ack.resolve();await refused;await turn();process.removeListener('unhandledRejection',observe);
assert.equal(reported.code,'ERR_LSF_UNSUPPORTED_OPERATION');assert.equal(reported.syscall,'paused-end-unread-data');
assert.equal(socket.bytesWritten,1);assert.equal(reported.mayHaveApplied,true);assert.equal(reported.acceptedPrefixBytes,0);
assert(unhandled.includes(reported));assert.equal(socket.readableEnded,false);assert.equal(copied,0);assert.equal(f.drops,0);
assert.equal(f.calls.includes('close'),false);assert.throws(f.transport.assertEmpty,/unclosed/);f.transport.endRootReturn(owner);
""")

    def test_actual_generated_handoff_captures_resolver_before_application_mutation(self):
        self.javascript(r"""
const {script}=await capturedInitializer(),native=deferred(),ack=deferred(),reason={logicalCancellation:true};
const application=vm.createContext({TextEncoder,TextDecoder});
const content=vm.runInContext('globalThis',application),originalResolve=content.Promise.resolve;
const handle=Object.freeze({});let watched=0,finished=0,cancelled=0,borrowed=0,mutatorCalls=0;
content.__lsfAsyncImportBridge={reserve(){return 7},watchBorrow(id){assert.equal(id,7);++watched;return handle},
 lift(value){return value},delivered(_id,value){return value},finish(id){assert.equal(id,7);++finished},
 borrowReleased(value){assert.equal(value,handle);++borrowed;return ack.promise},
 cancelBorrow(value){assert.equal(value,handle);++cancelled;native.reject(reason);return ack.promise}};
let allocated=1024;const bindings=[{buffer:new ArrayBuffer(65536)},(_ptr,_old,_align,size)=>{const at=allocated;allocated+=size;return at},
 (id)=>{assert.equal(id,7);return native.promise},...Array(21).fill(()=>0)];
const initializer=vm.createContext({contentGlobal:content,$bindings:bindings,defineBuiltinModule(){},TextEncoder,TextDecoder,console});
vm.runInContext(script,initializer,{timeout:3000});
content.Promise.resolve=function(value){++mutatorCalls;return Reflect.apply(originalResolve,this,[mutatorCalls===1?value:undefined])};
const start=vm.runInContext('__lsfBorrowCalls.connect',initializer);
const operation=start({host:'127.0.0.1',port:12345,transport:'tcp',timeoutMillis:undefined});
const rejected=assert.rejects(operation.promise,error=>error===reason);
let released=false,cancelAck=false;const release=operation.borrowReleased;release.then(()=>released=true);
const cancel=operation.cancel();cancel.then(()=>cancelAck=true);await rejected;await turn();
assert.equal(watched,1);assert.equal(finished,1);assert.equal(borrowed,1);assert.equal(cancelled,1);
assert.equal(released,false);assert.equal(cancelAck,false);assert.equal(mutatorCalls,0);
ack.resolve();await release;await cancel;assert.equal(released,true);assert.equal(cancelAck,true);
""", parser=True)

    def test_empty_write_callbacks_are_deferred_pump_restarts_and_record_limit_is_finite(self):
        self.javascript(r"""
const connect=deferred(),events=[];let writes=0;
const f=fixture({connect:()=>({promise:connect.promise,borrowReleased:Promise.resolve(),cancel(){}}),
 write(_,bytes){++writes;assert.equal(bytes.length,1);return settled(1)}});
const socket=f.net.connect(12345,'localhost'),closed=deferred();
socket.on('error',closed.reject).on('close',closed.resolve).on('finish',()=>socket.destroy());
for(let i=0;i<16;++i)socket.write('',()=>events.push('queued-empty'));
assert.throws(()=>socket.write(''),error=>error.code==='ERR_LSF_RESOURCE_EXHAUSTED');
assert.equal(events.length,0);connect.resolve(f.connection);await turn();assert.equal(events.length,16);assert.equal(writes,0);
socket.write('',()=>events.push('empty'));events.push('returned');
socket.write('x',error=>{assert.equal(error,undefined);events.push('nonempty');socket.end()});
await closed.promise;
assert.deepEqual(events.slice(16),['returned','empty','nonempty']);assert.equal(writes,1);f.transport.assertEmpty();
""")

    def test_unconnected_and_destroyed_public_state_matches_normal_node_logical_state(self):
        self.javascript(r"""
const {Socket:NativeSocket}=await import('node:net');
for(const make of [()=>new NativeSocket(),()=>new (fixture().net.Socket)()]) {
 const socket=make();assert.equal(socket.pending,true);assert.equal(socket.readyState,'open');
 assert.equal(socket.closed,false);assert.equal(socket.timeout,undefined);socket.setTimeout(0);assert.equal(socket.timeout,0);
 socket.destroy();assert.equal(socket.destroyed,true);assert.equal(socket.pending,true);assert.equal(socket.closed,true);
 assert.equal(socket.readyState,'closed');
}
""")

    def test_selection_types_and_legacy_unselected_capture(self):
        identities = net_profile.identities(ROOT)
        self.assertIsNone(net_profile.selected({}, identities))
        for invalid in (False, 0, None, {}, ['net'], ['node:net', 'node:net']):
            with self.assertRaises(ValueError):
                net_profile.selected({'standardNetModules': invalid}, identities)
        selected = net_profile.selected({'standardNetModules': ['node:net'],
            'standardNetProfile': net_profile.PROFILE, 'standardNetIdentities': identities}, identities)
        self.assertTrue(selected['automaticCloseDrain'])
        self.assertEqual(selected['closeDrain'], 'accepted-terminal-intent-only-v1')
        self.assertEqual(selected['maximumRootCloseWaiters'], 1)
        self.assertEqual(selected['pausedEndRead'], 'eof-only-unread-data-refuses')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            self.assertEqual(net_profile.retain_selection(path, path, identities), ((), []))

    def test_actual_pinned_bundle_graph_dce_private_resolution_and_snapshot(self):
        frontend = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
        if not frontend:
            self.skipTest('Explicit normal pinned frontend required for actual bundler control')
        tools = Path(frontend)
        node = shutil.which('node')
        self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            imports = work/'imports.json'
            imports.write_text(json.dumps([net_profile.INTERFACE]), encoding='utf-8')
            configuration = {'runtimeProfile': 'spidermonkey-activation-promises-clocks-imports-v1',
                'nativeClockInterfaces': ['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'],
                'standardNetProfile': net_profile.PROFILE, 'standardNetIdentities': net_profile.identities(ROOT)}

            def bundle(source, configured=None, passed=True):
                (work/'src').mkdir(exist_ok=True)
                (work/'src/main.ts').write_text(source, encoding='utf-8')
                config = work/'config.json'
                config.write_text(json.dumps(configured or configuration), encoding='utf-8')
                output = work/'application.mjs'
                for path in (output, work/'application.mjs.inputs.json'):
                    path.unlink(missing_ok=True)
                result = subprocess.run([node, ROOT/'tools/typescript_guest/bundle.mjs',
                    tools/'node_modules/esbuild/lib/main.js', work, work/'src/main.ts', output,
                    imports, config, tools/'node_modules/acorn/dist/acorn.mjs'],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode == 0, passed, result.stdout + result.stderr)
                if not passed:
                    return result.stderr
                return output.read_text(encoding='utf-8'), json.loads((work/'application.mjs.inputs.json').read_bytes())

            unused, observation = bundle('export const answer = 7;')
            self.assertNotIn('standardNetModules', observation)
            disabled = {key: value for key, value in configuration.items() if not key.startswith('standardNet')}
            normal, _ = bundle('export const answer = 7;', disabled)
            self.assertEqual(normal, unused)
            erased, observation = bundle("import {Socket} from 'node:net'; export const answer = 7;")
            self.assertNotIn('standardNetModules', observation)
            self.assertNotIn('__lsfNetSnapshotTransport', erased)
            linked, observation = bundle("import net from 'net'; import {Socket} from 'node:net'; export const same = net.Socket === Socket; export const idle = new Socket();")
            self.assertEqual(observation['standardNetModules'], ['node:net'])
            self.assertIn('__lsfNetSnapshotTransport.assertEmpty();\n__lsfSnapshotActive = false;', linked)
            self.assertEqual(sum(name == 'lsf-owned-node-net:node:net' for name in observation['inputs']), 1)
            self.assertIn('compiler-private-node-net-transport', bundle(
                "import {reserve} from 'lsf:typescript-node-net-transport'; export const x=reserve;", passed=False))
            self.assertIn('standard-node-net-requires-exact-stream', bundle(
                "import {Socket} from 'net'; export const value=Socket;", disabled, passed=False))
            # Actual initializer and actual bundled ESM share this application
            # realm. Intrinsics/native entrypoints are host-control doubles;
            # no actual native/WIT operation is started by this constructor test.
            javascript = f"""
import {{parse}} from {json.dumps((tools/'node_modules/acorn/dist/acorn.mjs').as_uri())};
import {{nodeNetBindings,NET_PROFILE}} from {json.dumps((ROOT/net_profile.BINDINGS).as_uri())};
""" + self.captured_source() + r"""
import assert from 'node:assert/strict';import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const source=await readFile(process.argv[1],'utf8');
const context=vm.createContext({console,TextEncoder,TextDecoder,setTimeout,clearTimeout,queueMicrotask,performance:{now(){return 0},timeOrigin:0}});
const content=vm.runInContext('globalThis',context);content.__lsfAsyncImportBridge={};
const registered=new Map(),{script}=await capturedInitializer();
vm.runInNewContext(script,{contentGlobal:content,$bindings:[{buffer:new ArrayBuffer(65536)},()=>0,...Array(22).fill(()=>0)],
 defineBuiltinModule(name,exports){registered.set(name,exports)},TextEncoder,TextDecoder,console},{timeout:3000});
const privateTransport=registered.get('lsf:typescript-node-net-transport');
assert.equal(privateTransport.assertEmpty,content.__lsfNodeNetRootCheck);
assert.equal(Object.getOwnPropertyDescriptor(content,'__lsfNodeNetRootCheck').writable,false);
const modules=new Map();
const module=new vm.SourceTextModule(source,{context});
await module.link(async name=>{
 if(name!=='lsf:typescript-node-net-transport')throw Error('unexpected external '+name);
 if(!modules.has(name))modules.set(name,new vm.SyntheticModule(Object.keys(privateTransport),function(){
   for(const [key,value] of Object.entries(privateTransport))this.setExport(key,value);
 },{context}));
 return modules.get(name);
});
await module.evaluate();assert.equal(module.namespace.same,true);privateTransport.assertEmpty();
// Same immutable registry survives module evaluation. Its actual reservation
// is then visible to both the application-global and the private module check.
privateTransport.reserve();assert.throws(content.__lsfNodeNetRootCheck,/unclosed/);
assert.throws(privateTransport.assertEmpty,/unclosed/);
"""
            # Restore the actually linked source after negative builds.
            linked_path = work/'linked.mjs'
            linked_path.write_text(linked, encoding='utf-8')
            result = subprocess.run([node, '--experimental-vm-modules', '--input-type=module', '-e',
                                     javascript, linked_path], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pinned_typescript_ordinary_socket_declaration_and_unsupported_refusal(self):
        frontend = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
        if not frontend:
            self.skipTest('Explicit normal pinned frontend required for actual TSC control')
        node = shutil.which('node')
        self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work/'net.d.ts').write_bytes((ROOT/net_profile.DECLARATION).read_bytes())
            (work/'buffer.d.ts').write_bytes((ROOT/'sdk/typescript-guest/runtime/buffer.d.ts').read_bytes())
            config = {'compilerOptions': {'target': 'ES2022', 'module': 'ESNext',
                'moduleResolution': 'Bundler', 'strict': True, 'noEmit': True, 'lib': ['ES2022'],
                'types': [], 'paths': {'net': ['./net.d.ts'], 'node:net': ['./net.d.ts'],
                                      'node:buffer': ['./buffer.d.ts']}}, 'include': ['*.ts']}
            (work/'tsconfig.json').write_text(json.dumps(config), encoding='utf-8')
            source = """import net, {Socket} from 'node:net';
const socket: Socket = net.createConnection({host:'127.0.0.1',port:12345});
socket.on('connect',()=>socket.write('hello',error=>{if(error)socket.destroy(error);else socket.end()}));
socket.on('data',chunk=>{const copy:string=chunk.toString('utf8');if(copy==='done')socket.destroy()});
const closed:Promise<void>=new Promise(resolve=>socket.once('close',hadError=>{if(!hadError)resolve()}));
void closed;
"""
            path = work/'main.ts'
            path.write_text(source, encoding='utf-8')
            command = [node, Path(frontend)/'node_modules/typescript/bin/tsc', '--project', work/'tsconfig.json']
            good = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            path.write_text(source + "socket.connect({host:'example.test',port:443,tls:true});\nnet.createServer();\n", encoding='utf-8')
            bad = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('tls: boolean', bad.stdout)
            self.assertIn('createServer', bad.stdout)


class NodeNetOwningControls(unittest.TestCase):
    """Closed normal project/row guards only; no compiler or owning execution."""

    def test_normal_owning_project_keeps_exact_no_gate_sources_and_original_limits(self):
        from tools.typescript_guest import borrow_signed_controls as owner
        from tools.phase2_operator_process import WorkflowError
        from tools.rust_capsule_project import snapshot, read_file
        with tempfile.TemporaryDirectory() as temporary:
            source = owner.node_net_project(Path(temporary)/'project')
            files = owner.verify_node_net_project(source)
            value = json.loads(files['capsule-project.json'])
            self.assertEqual(value['limits'], owner.NET_LIMITS)
            self.assertEqual(value['limits']['cpuFuel'], 1_000_000_000)
            self.assertEqual(value['limits']['outboundRequests'], 8)
            self.assertEqual(value['world'].split(':',1)[0],value['tenant'])
            self.assertTrue(files['wit/world.wit'].decode().startswith('package '+value['tenant']+':'))
            self.assertEqual({name for name in files if name.startswith(('src/', 'wit/'))}, set(owner.NET_INPUTS))
            for name, path in owner.NET_INPUTS.items():
                self.assertEqual(files[name], read_file(ROOT/path))
            sdk = snapshot(source/'vendor')
            wrong_scope=dict(value,world='tests:typescript-node-net/service@1.0.0')
            (source/'capsule-project.json').write_text(json.dumps(wrong_scope),encoding='utf-8')
            with self.assertRaisesRegex(WorkflowError,'exact-normal-project'):
                owner.verify_node_net_project(source)
            (source/'capsule-project.json').write_bytes(files['capsule-project.json'])
            altered = dict(value, limits={**value['limits'], 'cpuFuel':10_000_000_000})
            (source/'capsule-project.json').write_text(json.dumps(altered), encoding='utf-8')
            with self.assertRaisesRegex(WorkflowError, 'exact-normal-project'):
                owner.verify_node_net_project(source)
            (source/'capsule-project.json').write_bytes(files['capsule-project.json'])
            (source/'src/extra.ts').write_text('export const hidden = 1;', encoding='utf-8')
            with self.assertRaisesRegex(WorkflowError, 'exact-ordinary-source'):
                owner.verify_node_net_project(source)
            self.assertEqual(snapshot(source/'vendor'), sdk)

    def test_owning_records_require_all_actual_cases_and_precise_unclosed_attribution(self):
        import copy
        from tools.typescript_guest import borrow_signed_controls as owner
        from tools.phase2_operator_process import WorkflowError
        cases = [{'case':name,'mode':mode,'index':index,
            'status':'failed-with-unclosed-stream-owners' if mode==4 else 'succeeded',
            'outboundRequests':1,'cpuFuel':100,'peakMemoryBytes':4096,'grantFuel':1_000_000_000,
            'outboundCeiling':8,'sameBackend':True,'kernelRetirementQualified':False}
            for index,(name,mode) in enumerate(owner.NET_CASES)]
        def owners(held, count=None):
            count=(2 if held else 0) if count is None else count
            return {'stream':dict.fromkeys(('owners','connections','pendingOperations','retainedChunks'),count),
                'io':{'calls':count,'streams':count,'stagedBytes':32768*count if held else 0,'buffers':2*count if held else 0,
                      'running':0,'queued':0,'resultBytes':0,'metadataBytes':0},
                'poolConnections':count,'poolRunningRequests':0,'liveStores':1 if held else 0,
                'activeActivations':1 if held else 0,'liveInstances':1 if held else 0,'queuedActivations':0,'kernelRetirementQualified':False}
        for row in cases:
            mode=row['mode']; row['outboundRequests']=0 if mode==6 else 1
            row.update(grantMemoryBytes=128*1024**2,grantWallTimeMillis=120000,
                publicErrorCode='guest-trap' if mode==4 else 'none',
                publicTrap={'kind':'unreachable-code','code':'guest-trap','phase':None,'message':'guest trapped: unreachable-code'} if mode==4 else None,
                originalFailureCause='unknown' if mode==4 else 'not-applicable',
                guardAttribution='source-only' if mode==4 else 'not-applicable',recordedAdmissionRefusal=False,
                postRoot=owners(False),heldOwnerBeforePermit=owners(True) if mode in (1,3,4) else None,
                controlPeerEOF=mode in (1,3,4),primaryReleasedAfterObservation=mode==4,
                acceptedCloseBeforeEOF=owners(True,1) if mode==5 else None)
        reference = {'name':'node-net-reference-t32-q32-n128-v1',
            'runtimeLimits':{'tasks':32,'executors':2,'queuedWork':32,'waits':8,'timers':8,'results':8,'native':128},
            'activationRuntimeProfile':'activation-owned-v1',
            'runtimeLimitsConfiguration':'RuntimeLimits { tasks: 32, executors: 2, queued_work: 32, waits: 8, timers: 8, results: 8, native_owners: 128 }',
            'preparation':{'backend':'wasmtime-component-phase-1','release':'sha256:'+'1'*64,
                'publication':'publication:sha256:'+'2'*64,'componentDigest':'sha256:'+'1'*64,
                'engineConfigurationDigest':'blake3:'+'3'*64,'engineVersion':'48.0.7',
                'targetTriple':'x86_64-unknown-linux-gnu','cpuFeatureSet':'host-baseline'}}
        for row in cases: row['referenceProfile']=copy.deepcopy(reference)
        complete = {'cases':8,'guestComponents':1,'gateComponent':False,'wholeAC7':False,
                    'wholeCostQualification':False,'productionEnablement':False,'referenceProfile':reference}

        def raw(rows, done=complete):
            return ('\n'.join('TYPESCRIPT_NODE_NET_CASE '+json.dumps(row) for row in rows)
                    +'\nTYPESCRIPT_NODE_NET_COMPLETE '+json.dumps(done)
                    +'\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n').encode()

        self.assertEqual(owner.node_net_records(raw(cases)), cases)
        # No missing, mixed, boolean, expanded or relabelled stress-profile limits.
        for replacement in (None,{}, {**reference,'name':'node-net-reference-t16-q16-v1'},
                {**reference,'name':'node-net-reference-t32-q32-v1'},
                {**reference,'runtimeLimits':{**reference['runtimeLimits'],'tasks':16}},
                {**reference,'runtimeLimits':{**reference['runtimeLimits'],'queuedWork':16}},
                {**reference,'runtimeLimits':{**reference['runtimeLimits'],'native':64}},
                {**reference,'runtimeLimits':{**reference['runtimeLimits'],'executors':True}},
                {**reference,'runtimeLimits':{**reference['runtimeLimits'],'extra':0}},
                {**reference,'runtimeLimitsConfiguration':reference['runtimeLimitsConfiguration'].replace('32','16')},
                {**reference,'preparation':{**reference['preparation'],'publication':'sha256:'+'2'*64}},
                {**reference,'preparation':{**reference['preparation'],'componentDigest':'sha256:'+'4'*64}},
                {**reference,'preparation':{**reference['preparation'],'engineConfigurationDigest':'sha256:'+'3'*64}}):
            changed=copy.deepcopy(cases)
            for row in changed: row['referenceProfile']=copy.deepcopy(replacement)
            with self.subTest(profile=replacement),self.assertRaises(WorkflowError):
                owner.node_net_records(raw(changed,{**complete,'referenceProfile':replacement}))
        changed=copy.deepcopy(cases);changed[1]['referenceProfile']['preparation']['engineConfigurationDigest']='blake3:'+'4'*64
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);del changed[0]['referenceProfile']
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        for done in ({k:v for k,v in complete.items() if k!='referenceProfile'},
                {**complete,'referenceProfile':{**reference,'name':'foreign'}}):
            with self.assertRaises(WorkflowError): owner.node_net_records(raw(cases,done))
        generic=copy.deepcopy(cases);generic[4]['publicTrap']={'kind':'runtime-error','code':'guest-runtime-error',
            'phase':'call-and-postreturn','message':'guest execution failed'}
        self.assertEqual(owner.node_net_records(raw(generic)),generic)
        for field,value in (('status','guest-trap'),('mode',True),('grantFuel',10_000_000_000),
                            ('outboundRequests',9),('sameBackend',1),('publicErrorCode','deadline-exceeded'),
                            ('originalFailureCause','unclosed-guard'),('guardAttribution','actual-instruction'),
                            ('heldOwnerBeforePermit',None),('controlPeerEOF',False),
                            ('primaryReleasedAfterObservation',False),('recordedAdmissionRefusal',True)):
            changed=copy.deepcopy(cases); changed[4][field]=value
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                owner.node_net_records(raw(changed))
        for kind in ('stack-overflow','memory-out-of-bounds','allocation-too-large','cannot-block-sync-task'):
            changed=copy.deepcopy(cases)
            changed[4]['publicTrap']={'kind':kind,'code':'guest-trap','phase':None,'message':'guest trapped: '+kind}
            with self.subTest(knownKind=kind),self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);changed[4]['publicTrap']=None
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);changed[4]['publicTrap']['message']='arbitrary/private text'
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);changed[4]['heldOwnerBeforePermit']['stream']['pendingOperations']=0
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);changed[4]['postRoot']['io']['calls']=1
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        changed=copy.deepcopy(cases);changed[3]['status']='guest-trap'
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        for value in (None, owners(True), {**owners(True,1),'liveStores':0}):
            changed=copy.deepcopy(cases);changed[6]['acceptedCloseBeforeEOF']=value
            with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        for index,value in ((6,0),(7,1)):
            changed=copy.deepcopy(cases);changed[index]['outboundRequests']=value
            with self.assertRaises(WorkflowError): owner.node_net_records(raw(changed))
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(cases[:-1]))
        with self.assertRaises(WorkflowError): owner.node_net_records(raw(cases, {**complete,'gateComponent':0}))

    def test_unknown_or_cross_programme_inputs_refuse_before_filesystem_or_process(self):
        from unittest.mock import patch
        from tools.typescript_guest import borrow_signed_controls as owner
        from tools.phase2_operator_process import WorkflowError
        with patch.object(Path, 'resolve', side_effect=AssertionError('no path access')) as paths, \
                patch.object(owner, 'run_bounded_result', side_effect=AssertionError('no process')) as process:
            for programme, native in [('foreign', None), (False, None), (None, None), ('borrow', Path('foreign-native'))]:
                with self.subTest(programme=programme), self.assertRaisesRegex(WorkflowError, 'closed-signed-stream-programme'):
                    owner.qualify(Path('tools'), Path('inputs'), Path('output'), programme=programme, prepared_native=native)
            paths.assert_not_called(); process.assert_not_called()
        import contextlib
        import io
        import runpy
        import sys
        from tools.typescript_guest import borrow_signed_inputs
        from tools import java_phase_native_products
        for extra in (['--programme','node-net'], ['--prepared-native','foreign-native']):
            with patch.object(borrow_signed_inputs,'prepare',side_effect=AssertionError('no acquisition')) as acquire, \
                    patch.object(java_phase_native_products,'prepare',side_effect=AssertionError('no native acquisition')) as native, \
                    patch.object(sys,'argv',['qualify','--tools','tools','--inputs','inputs','--output','output',*extra]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as refused:
                runpy.run_path(str(ROOT/'tools/qualify_typescript_borrow_signed.py'),run_name='__main__')
            self.assertEqual(refused.exception.code,2)
            acquire.assert_not_called(); native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
