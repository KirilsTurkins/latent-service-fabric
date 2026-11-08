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
 const contexts={},queues={10:[],11:[],12:[]},parkCounts={10:0,11:0,12:0};
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
    queues[target].shift().resolve(0);
   }}});
 const root=new WebAssembly.Instance(module,importsFor(10));
 const first=new WebAssembly.Instance(module,importsFor(11));
 const second=new WebAssembly.Instance(module,importsFor(12));
 root.exports.__stack_pointer.value=0x110000;
 first.exports.__stack_pointer.value=0x210000;
 second.exports.__stack_pointer.value=0x310000;
 root.exports.setup(scenario);
 contexts[10]=root.exports.root_pointer();contexts[11]=root.exports.first_pointer();contexts[12]=root.exports.second_pointer();
 return {root,first,second,queues,parkCounts,hold,held,admit,admitted,park,parked};
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
(async()=>{
 const module=new WebAssembly.Module(fs.readFileSync(process.argv[2]));
 const mode=process.argv[3]||'all';
 if(mode==='baseline-preclaimed'){await oldPreclaimed(module);return;}
 if(mode==='baseline-later'){await oldLater(module);return;}
 if(mode==='all'||mode==='preclaimed')await joinChain(module,true);
 if(mode==='all'||mode==='later')await joinChain(module,false);
 if(mode==='all'||mode==='admission')await admissionRace(module);
 if(mode==='all'||mode==='park')await parkRace(module);
 if(mode==='all'||mode==='cancel')await cancelled(module);
 console.log('PASS root drain: existing and later joins, admission and park races, cancellation custody; JSPI test ports only');
})().catch(error=>{console.error(error);process.exitCode=1;});
