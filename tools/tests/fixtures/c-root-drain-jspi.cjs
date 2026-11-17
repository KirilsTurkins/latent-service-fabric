/* JSPI scheduling ports only; not a Wasmtime or original-ledger run. */
const fs=require('node:fs');
const assert=require('node:assert/strict');
function gate(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
async function until(predicate,label){
 for(let n=0;n<100;++n){if(predicate())return;await Promise.resolve();}
 throw Error('missing deterministic transition: '+label);
}
function harness(module,scenario){
 const memory=new WebAssembly.Memory({initial:64,maximum:64});
 const contexts={},queues={10:[],11:[],12:[]},parkCounts={10:0,11:0,12:0},cancelOnResume=new Set();
 const hold=gate(),held=gate(),admit=gate(),admitted=gate(),park=gate(),parked=gate();
 const importsFor=id=>({env:{memory},test:{context:()=>contexts[id],
  hold:new WebAssembly.Suspending(()=>{held.resolve();return hold.promise;}),
  admit:new WebAssembly.Suspending(()=>{admitted.resolve();return admit.promise;}),
  park:new WebAssembly.Suspending(()=>{parked.resolve();return park.promise;})},
  '$root':{'[thread-yield-then-promote]':()=>0,
   '[thread-suspend]':new WebAssembly.Suspending(()=>{
    const next=gate();queues[id].push(next);++parkCounts[id];return next.promise;
   }),
   '[thread-resume-later]':target=>{
    assert.ok(queues[target]&&queues[target].length,'only a suspended target may resume');
    queues[target].shift().resolve(cancelOnResume.has(target)?1:0);
   }}});
 const root=new WebAssembly.Instance(module,importsFor(10));
 const first=new WebAssembly.Instance(module,importsFor(11));
 const second=new WebAssembly.Instance(module,importsFor(12));
 root.exports.__stack_pointer.value=0x110000;
 first.exports.__stack_pointer.value=0x210000;
 second.exports.__stack_pointer.value=0x310000;
 root.exports.setup(scenario);
 contexts[10]=root.exports.root_pointer();contexts[11]=root.exports.first_pointer();contexts[12]=root.exports.second_pointer();
 return {root,first,second,queues,parkCounts,cancelOnResume,hold,held,admit,admitted,park,parked};
}
async function joinChain(module,claimedBeforeRoot){
 const h=harness(module,0),e=h.root.exports;
 let firstPromise,rootPromise,rootDone=false;
 if(claimedBeforeRoot){
  firstPromise=WebAssembly.promising(h.first.exports.start_first)();
  firstPromise.catch(()=>{});
  await until(()=>h.parkCounts[11]===1,'application join');
  assert.equal(e.read_second_claimed(),1);
 }
 rootPromise=WebAssembly.promising(e.start_root)();rootPromise.then(()=>{rootDone=true;},()=>{});
 await until(()=>h.parkCounts[10]===1,'root drain');
 if(!claimedBeforeRoot){
  firstPromise=WebAssembly.promising(h.first.exports.start_first)();
  firstPromise.catch(()=>{});
  await until(()=>h.parkCounts[11]===1,'application join after root closure');
 }
 assert.equal(e.read_second_claimed(),1);assert.equal(e.read_live(),2);
 h.second.exports.start_second();
 assert.equal(e.read_second_phase(),5,'deferred wake must follow the wrapper exit');
 await h.held.promise;
 await until(()=>h.parkCounts[10]===2,'root re-parks for still-live joiner');
 assert.equal(rootDone,false);assert.equal(e.read_first_phase(),2);
 assert.equal(e.read_second_joined(),1);assert.equal(e.read_live(),1);
 assert.equal(e.read_released(),3);assert.equal(e.read_freed(),2);
 h.hold.resolve();await firstPromise;await rootPromise;
 assert.equal(e.read_first_phase(),5);assert.equal(e.read_root_observer(),0);
 assert.equal(e.read_admitted(),3);assert.equal(e.read_settled(),3);
 assert.equal(e.read_peak(),2);assert.equal(e.read_live(),0);
 assert.equal(e.read_released(),6);assert.equal(e.read_freed(),4);assert.equal(e.read_tls(),3);
}
async function admissionRace(module){
 const h=harness(module,1),e=h.root.exports;
 const root=WebAssembly.promising(e.start_root)();await h.admitted.promise;
 assert.equal(e.read_live(),1);assert.equal(e.read_root_observer(),0);
 await WebAssembly.promising(h.first.exports.start_first)();assert.equal(e.read_first_phase(),5);
 h.admit.resolve();await root;
 assert.equal(h.parkCounts[10],0);assert.equal(e.read_admitted(),2);
 assert.equal(e.read_settled(),2);assert.equal(e.read_live(),0);assert.equal(e.read_released(),3);
}
async function parkRace(module){
 const h=harness(module,2),e=h.root.exports;
 const root=WebAssembly.promising(e.start_root)();await h.parked.promise;
 assert.equal(e.read_root_observer(),1);
 await WebAssembly.promising(h.first.exports.start_first)();assert.equal(e.read_first_phase(),5);
 assert.equal(e.read_root_observer(),0);h.park.resolve();await root;
 assert.equal(h.parkCounts[10],0);assert.equal(e.read_live(),0);assert.equal(e.read_settled(),2);
}
async function cancelled(module){
 const h=harness(module,3),e=h.root.exports;
 const root=WebAssembly.promising(e.start_root)();
 await until(()=>h.parkCounts[10]===1,'cancelled root');
 h.queues[10].shift().resolve(1);await assert.rejects(root,WebAssembly.RuntimeError);
 assert.equal(e.read_live(),1);assert.equal(e.read_settled(),0);
 assert.equal(e.read_released(),0);assert.equal(e.read_freed(),0);
 assert.equal(e.read_root_observer(),1);
}
async function oldPreclaimed(module){
 const h=harness(module,0),e=h.root.exports;
 const first=WebAssembly.promising(h.first.exports.start_first)();first.catch(()=>{});
 await until(()=>h.parkCounts[11]===1,'original application join');
 assert.equal(e.read_second_claimed(),1);
 await assert.rejects(WebAssembly.promising(e.start_root)(),WebAssembly.RuntimeError);
 assert.equal(e.read_live(),1);assert.equal(e.read_released(),0);assert.equal(e.read_freed(),0);
 console.log('BASELINE REPRODUCED: root traps on an existing application join');
}
async function oldLater(module){
 const h=harness(module,0),e=h.root.exports;
 const root=WebAssembly.promising(e.start_root)();root.catch(()=>{});
 await until(()=>h.parkCounts[10]===1,'original root claim');
 assert.equal(e.read_second_claimed(),1);
 await assert.rejects(WebAssembly.promising(h.first.exports.start_first)(),WebAssembly.RuntimeError);
 assert.equal(e.read_live(),1);assert.equal(e.read_released(),0);assert.equal(e.read_freed(),0);
 console.log('BASELINE REPRODUCED: root steals a later application join');
}
async function rwlockControls(module){
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();
  assert.equal(e.rw_init_default(),0);assert.equal(e.rw_read(),0);assert.equal(e.rw_read(),0);
  assert.equal(e.rw_trywrite(),e.rw_busy());assert.equal(e.rw_destroy(),e.rw_busy());
  const writer=WebAssembly.promising(h.first.exports.rw_write)();
  await until(()=>h.parkCounts[11]===1,'writer waits for readers');assert.equal(e.read_live(),1);
  assert.equal(h.second.exports.rw_read(),0,'reader priority admits a later reader');
  assert.equal(e.rw_unlock(),0);assert.equal(e.rw_unlock(),0);assert.equal(e.read_live(),1);
  assert.equal(h.second.exports.rw_unlock(),0);assert.equal(await writer,0);
  assert.equal(e.read_live(),0);assert.equal(e.read_settled(),1);
  assert.equal(e.rw_tryread(),e.rw_busy());assert.equal(e.rw_unlock(),e.rw_perm());
  assert.equal(h.first.exports.rw_write(),e.rw_deadlock());
  assert.equal(h.first.exports.rw_trywrite(),e.rw_busy());assert.equal(h.first.exports.rw_unlock(),0);
  assert.equal(e.rw_destroy(),0);assert.equal(e.rw_errno(),37);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();assert.equal(e.rw_write(),0);
  const a=WebAssembly.promising(h.first.exports.rw_read)(),b=WebAssembly.promising(h.second.exports.rw_read)();
  await until(()=>h.parkCounts[11]===1 && h.parkCounts[12]===1,'readers wait for writer');
  assert.equal(e.read_live(),2);assert.equal(e.rw_unlock(),0);assert.deepEqual(await Promise.all([a,b]),[0,0]);
  assert.equal(e.read_live(),0);assert.equal(e.read_settled(),2);assert.equal(e.rw_trywrite(),e.rw_busy());
  assert.equal(h.first.exports.rw_unlock(),0);assert.equal(h.second.exports.rw_unlock(),0);
  assert.equal(e.rw_trywrite(),0);assert.equal(e.rw_unlock(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();assert.equal(e.rw_read(),0);
  const a=WebAssembly.promising(h.first.exports.rw_write)(),b=WebAssembly.promising(h.second.exports.rw_write)();
  await until(()=>h.parkCounts[11]===1 && h.parkCounts[12]===1,'writers queue');
  assert.equal(e.rw_unlock(),0);assert.equal(await a,0);assert.equal(e.read_live(),1);
  assert.equal(h.first.exports.rw_unlock(),0);assert.equal(await b,0);assert.equal(e.read_live(),0);
  assert.equal(h.second.exports.rw_unlock(),0);assert.equal(e.read_settled(),2);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();e.rw_set_shared();
  assert.equal(e.rw_init_default(),e.rw_notsup());assert.equal(e.rw_read(),0);assert.equal(e.rw_unlock(),0);
  assert.equal(e.rw_timedread(),e.rw_notsup());assert.equal(e.rw_timedwrite(),e.rw_notsup());
  e.rw_set_reader_limit();assert.equal(e.rw_read(),e.rw_again());assert.equal(e.read_admitted(),0);
  assert.equal(e.rw_errno(),37);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();assert.equal(e.rw_write(),0);e.rw_refuse_wait(1);
  assert.equal(await WebAssembly.promising(h.first.exports.rw_read)(),e.rw_again());
  assert.equal(e.read_live(),0);assert.equal(e.rw_tryread(),e.rw_busy());e.rw_refuse_wait(0);
  assert.equal(e.rw_unlock(),0);assert.equal(h.first.exports.rw_read(),0);assert.equal(h.first.exports.rw_unlock(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();assert.equal(e.rw_write(),0);e.rw_pause_admission();
  const reader=WebAssembly.promising(h.first.exports.rw_read)();await h.admitted.promise;
  assert.equal(e.read_live(),1);assert.equal(e.rw_unlock(),0);h.admit.resolve();assert.equal(await reader,0);
  assert.equal(h.parkCounts[11],0);assert.equal(e.read_live(),0);assert.equal(e.read_settled(),1);
  assert.equal(h.first.exports.rw_unlock(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();assert.equal(e.rw_write(),0);
  const reader=WebAssembly.promising(h.first.exports.rw_read)();
  await until(()=>h.parkCounts[11]===1,'cancelled rwlock wait');h.queues[11].shift().resolve(1);
  await assert.rejects(reader,WebAssembly.RuntimeError);assert.equal(e.read_live(),1);assert.equal(e.read_settled(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;e.rw_setup();
  assert.equal(e.rw_tryread(),0);assert.equal(e.rw_tryread(),0);assert.equal(e.rw_unlock(),0);
  assert.equal(e.rw_trywrite(),e.rw_busy());assert.equal(e.rw_unlock(),0);assert.equal(e.rw_destroy(),0);
 }
 console.log('PASS rwlock source: readers, writers, wakeups, refusals and cancellation; JSPI test ports only');
}
async function semaphoreControls(module){
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(1),0);assert.equal(e.ss_getvalue(),1);assert.equal(e.ss_errno(),37);
  assert.equal(e.ss_trywait(),0);assert.equal(e.ss_getvalue(),0);
  assert.equal(e.ss_trywait(),-1);assert.equal(e.ss_errno(),e.ss_eagain());
  assert.equal(e.ss_post(),0);assert.equal(e.ss_getvalue(),1);assert.equal(e.ss_wait(),0);
  assert.equal(e.ss_getvalue(),0);assert.equal(e.ss_destroy(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);
  const first=WebAssembly.promising(h.first.exports.ss_wait)();
  const second=WebAssembly.promising(h.second.exports.ss_wait)();
  await until(()=>h.parkCounts[11]===1 && h.parkCounts[12]===1,'both semaphore waiters');
  assert.equal(e.read_live(),2);assert.equal(e.ss_getvalue(),0);
  assert.equal(e.ss_destroy(),-1);assert.equal(e.ss_errno(),e.ss_ebusy());
  assert.equal(e.ss_post(),0);assert.equal(await first,0);assert.equal(e.read_live(),1);
  assert.equal(e.ss_getvalue(),0);assert.equal(e.ss_trywait(),-1);assert.equal(e.ss_errno(),e.ss_eagain());
  assert.equal(e.ss_post(),0);assert.equal(await second,0);
  assert.equal(e.read_live(),0);assert.equal(e.read_admitted(),2);assert.equal(e.read_settled(),2);
  assert.equal(e.ss_destroy(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);e.ss_refuse_wait(1);
  assert.equal(await WebAssembly.promising(h.first.exports.ss_wait)(),-1);
  assert.equal(e.ss_errno(),e.ss_eagain());assert.equal(e.read_live(),0);assert.equal(e.read_admitted(),0);
  assert.equal(e.ss_post(),0);assert.equal(e.ss_getvalue(),1);assert.equal(e.ss_destroy(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);e.ss_pause_admission();
  const waiter=WebAssembly.promising(h.first.exports.ss_wait)();await h.admitted.promise;
  assert.equal(e.read_live(),1);assert.equal(e.ss_post(),0);assert.equal(e.ss_getvalue(),1);
  h.admit.resolve();assert.equal(await waiter,0);assert.equal(h.parkCounts[11],0);
  assert.equal(e.ss_getvalue(),0);assert.equal(e.read_live(),0);assert.equal(e.read_settled(),1);
 }
 {
  const h=harness(module,2),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);const waiter=WebAssembly.promising(e.ss_wait)();await h.parked.promise;
  assert.equal(e.read_live(),1);assert.equal(h.first.exports.ss_post(),0);h.park.resolve();
  assert.equal(await waiter,0);assert.equal(h.parkCounts[10],0);assert.equal(e.read_live(),0);
  assert.equal(e.read_settled(),1);assert.equal(e.ss_getvalue(),0);
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);const waiter=WebAssembly.promising(h.first.exports.ss_wait)();
  await until(()=>h.parkCounts[11]===1,'cancelled semaphore wait');h.queues[11].shift().resolve(1);
  await assert.rejects(waiter,WebAssembly.RuntimeError);
  assert.equal(e.read_live(),1);assert.equal(e.read_settled(),0);assert.equal(e.ss_getvalue(),0);
  assert.equal(e.ss_destroy(),-1);assert.equal(e.ss_errno(),e.ss_ebusy());
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);const waiter=WebAssembly.promising(h.first.exports.ss_wait)();
  await until(()=>h.parkCounts[11]===1,'handoff before cancelled continuation');
  h.cancelOnResume.add(11);assert.equal(e.ss_post(),0);await assert.rejects(waiter,WebAssembly.RuntimeError);
  assert.equal(e.read_live(),1);assert.equal(e.read_settled(),0);
  assert.equal(e.ss_getvalue(),0);assert.equal(e.ss_trywait(),-1);assert.equal(e.ss_errno(),e.ss_eagain());
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(0),0);const waiter=WebAssembly.promising(h.first.exports.ss_wait)();
  await until(()=>h.parkCounts[11]===1,'posted waiter before semaphore destruction');
  assert.equal(e.ss_post(),0);assert.equal(e.ss_destroy(),0);
  assert.equal(await waiter,0);assert.equal(e.read_live(),0);assert.equal(e.read_settled(),1);
 }
 {
  const h=harness(module,0),e=h.root.exports;
  assert.equal(e.ss_setup(e.ss_intmax()),0);assert.equal(e.ss_post(),-1);assert.equal(e.ss_errno(),e.ss_overflow());
  assert.equal(e.ss_getvalue(),e.ss_intmax());assert.equal(e.ss_shared(),-1);assert.equal(e.ss_errno(),e.ss_notsup());
  assert.equal(e.ss_invalid(),-1);assert.equal(e.ss_errno(),e.ss_einval());
  assert.equal(e.ss_getvalue(),e.ss_intmax());assert.equal(e.ss_timedwait(),-1);assert.equal(e.ss_errno(),e.ss_notsup());
  assert.equal(e.read_admitted(),0);assert.equal(e.ss_destroy(),0);
 }
 console.log('PASS semaphore source: permits, wait ownership, races, refusal and cancellation; JSPI test ports only');
}
function createHarness(module,options={}){
 const memory=new WebAssembly.Memory({initial:64,maximum:64});
 const contexts=[],last=[],admission=gate(),admissionReached=gate(),settle=gate(),settleReached=gate();
 const native=gate(),nativeReached=gate();let nativeCalls=0;
 const memoryView=()=>new DataView(memory.buffer);
 function admitted(index,ptr){
  last[index]=ptr;
  memoryView().setUint8(ptr+80,options.denyNative?1:0);
  memoryView().setUint8(ptr+81,options.denyNative?2:0);
  if(options.denyNative)return 0;
  memoryView().setUint8(ptr+82,1);
  return 100+index;
 }
 const imports=index=>({env:{memory},test:{context:()=>contexts[index],
  'hold-admission':new WebAssembly.Suspending(()=>{admissionReached.resolve();return admission.promise;}),
  'hold-settle':new WebAssembly.Suspending(()=>{settleReached.resolve();return settle.promise;})},
  '$root':{'[thread-new-indirect-v0]':new WebAssembly.Suspending((table,ptr)=>{
   assert.ok(table>0);++nativeCalls;
   if(index===0 && options.pauseNative){nativeReached.resolve();return native.promise.then(()=>admitted(index,ptr));}
   return admitted(index,ptr);
  }),
  '[thread-yield-then-promote]':()=>{
   assert.ok(last[index]);memoryView().setUint8(last[index]+82,2);
   memoryView().setUint32(last[index]+20,2,true);return 0;
  }}});
 const a=new WebAssembly.Instance(module,imports(0)),b=new WebAssembly.Instance(module,imports(1));
 a.exports.__stack_pointer.value=0x110000;b.exports.__stack_pointer.value=0x210000;
 a.exports.setup_create(options.existing||31,options.stage||0,
  options.failKind===undefined?0xffffffff:options.failKind,
  options.pauseKind===undefined?0xffffffff:options.pauseKind,options.pauseSettle?1:0);
 contexts[0]=a.exports.caller_pointer(0);contexts[1]=a.exports.caller_pointer(1);
 return {a,b,admission,admissionReached,settle,settleReached,native,nativeReached,
  nativeCalls:()=>nativeCalls};
}
async function oldCreateLimit(module){
 const h=createHarness(module,{pauseKind:0}),e=h.a.exports;
 const first=WebAssembly.promising(e.start_create)();await h.admissionReached.promise;
 assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),0);
 h.admission.resolve();assert.equal(await first,0);
 assert.equal(e.create_count(),33);assert.equal(e.create_list_count(),33);
 console.log('BASELINE REPRODUCED: concurrent creation exceeds the 32-record bound');
}
async function createControls(module){
 {
  const h=createHarness(module,{pauseKind:0}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.admissionReached.promise;
  assert.equal(e.create_count(),32);assert.equal(e.create_list_count(),31);
  assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),e.create_eagain());
  assert.equal(e.create_admissions(),1);h.admission.resolve();assert.equal(await first,0);
  assert.equal(e.create_count(),32);assert.equal(e.create_list_count(),32);assert.equal(e.create_live(),3);
 }
 {
  const h=createHarness(module,{pauseNative:true}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.nativeReached.promise;
  assert.equal(e.create_count(),32);assert.equal(e.create_list_count(),31);assert.equal(e.create_live(),3);
  assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),e.create_eagain());
  h.native.resolve();assert.equal(await first,0);
  assert.equal(e.create_count(),32);assert.equal(e.create_list_count(),32);assert.equal(h.nativeCalls(),1);
 }
 for(const pauseKind of [0,7,6]){
  const h=createHarness(module,{existing:2,pauseKind}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.admissionReached.promise;
  assert.equal(e.create_count(),3);assert.equal(e.create_list_count(),2);
  e.close_create_root();h.admission.resolve();assert.equal(await first,e.create_eagain());
  assert.equal(e.create_count(),2);assert.equal(e.create_list_count(),2);assert.equal(e.create_live(),0);
  assert.equal(e.create_settled(),3);assert.equal(e.create_allocations(),0);assert.equal(h.nativeCalls(),0);
 }
 {
  const h=createHarness(module,{existing:2,pauseNative:true}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.nativeReached.promise;
  e.close_create_root();h.native.resolve();assert.equal(await first,0);
  assert.equal(e.create_count(),3);assert.equal(e.create_list_count(),3);assert.equal(e.create_live(),3);
  assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),e.create_eagain());
 }
 {
  const h=createHarness(module,{existing:2,pauseNative:true,denyNative:true}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.nativeReached.promise;
  e.close_create_root();h.native.resolve();assert.equal(await first,e.create_eagain());
  assert.equal(e.create_count(),2);assert.equal(e.create_list_count(),2);assert.equal(e.create_live(),0);
  assert.equal(e.create_settled(),3);assert.equal(e.create_allocations(),e.create_frees());
 }
 for(const [failKind,live] of [[7,1],[6,2]]){
  const h=createHarness(module,{failKind,pauseSettle:true}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.settleReached.promise;
  assert.equal(e.create_count(),32);assert.equal(e.create_live(),live);
  assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),e.create_eagain());
  h.settle.resolve();assert.equal(await first,e.create_eagain());
  assert.equal(e.create_count(),31);assert.equal(e.create_live(),0);assert.equal(e.create_settled(),live);
 }
 {
  const h=createHarness(module,{denyNative:true,pauseSettle:true}),e=h.a.exports;
  const first=WebAssembly.promising(e.start_create)();await h.settleReached.promise;
  assert.equal(e.create_count(),32);assert.equal(e.create_live(),3);
  assert.equal(e.create_allocations(),3);assert.equal(e.create_frees(),2);
  assert.equal(await WebAssembly.promising(h.b.exports.start_create)(),e.create_eagain());
  h.settle.resolve();assert.equal(await first,e.create_eagain());
  assert.equal(e.create_count(),31);assert.equal(e.create_live(),0);assert.equal(e.create_settled(),3);
  assert.equal(e.create_frees(),3);
 }
 for(const options of [{stage:1},{stage:2},{failKind:0},{failKind:7},{failKind:6},
                       {stage:11},{stage:12},{stage:13},{denyNative:true}]){
  const h=createHarness(module,{existing:2,...options}),e=h.a.exports;
  const result=await WebAssembly.promising(e.start_create)();
  assert.ok(result===e.create_eagain() || result===e.create_enomem());
  assert.equal(e.create_count(),2);assert.equal(e.create_list_count(),2);assert.equal(e.create_live(),0);
  assert.equal(e.create_allocations(),e.create_frees());
 }
 console.log('PASS create source: concurrent capacity, closing, paid cleanup and refusal paths; JSPI test ports only');
}
(async()=>{
 const module=new WebAssembly.Module(fs.readFileSync(process.argv[2]));
 const mode=process.argv[3]||'all';
 if(mode==='semaphore-imports'){
  const imports=WebAssembly.Module.imports(module).filter(value=>value.kind==='function').map(value=>value.name);
  const expected=['sem_init','sem_destroy','sem_getvalue','sem_trywait','sem_wait','sem_post','sem_timedwait'];
  for(const name of expected){assert.ok(imports.includes('__lsf_c_'+name));assert.ok(!imports.includes(name));}
  console.log('PASS captured semaphore caller: seven private SDK imports');return;
 }
 if(mode==='rwlock'){await rwlockControls(module);return;}
 if(mode==='semaphore'){await semaphoreControls(module);return;}
 if(mode==='baseline-create'){await oldCreateLimit(module);return;}
 if(mode==='create'){await createControls(module);return;}
 if(mode==='baseline-preclaimed'){await oldPreclaimed(module);return;}
 if(mode==='baseline-later'){await oldLater(module);return;}
 if(mode==='all'||mode==='preclaimed')await joinChain(module,true);
 if(mode==='all'||mode==='later')await joinChain(module,false);
 if(mode==='all'||mode==='admission')await admissionRace(module);
 if(mode==='all'||mode==='park')await parkRace(module);
 if(mode==='all'||mode==='cancel')await cancelled(module);
 console.log('PASS root drain: existing and later joins, admission and park races, cancellation custody; JSPI test ports only');
})().catch(error=>{console.error(error);process.exitCode=1;});
