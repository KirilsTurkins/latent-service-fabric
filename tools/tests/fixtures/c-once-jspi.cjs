const fs=require('node:fs');const assert=require('node:assert/strict');
function gate(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
(async()=>{
 const mod=new WebAssembly.Module(fs.readFileSync(process.argv[2]));
 const memory=new WebAssembly.Memory({initial:64,maximum:64});
 const rootYield=gate(),rootEntered=gate(),parked={11:gate(),12:gate()},wakes={11:gate(),12:gate()};
 const contexts={};const importsFor=(id)=>({env:{memory},test:{context:()=>contexts[id],yield:new WebAssembly.Suspending(()=>{rootEntered.resolve();return rootYield.promise;})},'$root':{'[thread-suspend]':new WebAssembly.Suspending(()=>{parked[id].resolve();return wakes[id].promise.then(()=>0);}), '[thread-resume-later]':id=>{assert.ok(wakes[id]);wakes[id].resolve();}}});
 const root=new WebAssembly.Instance(mod,importsFor(10)),first=new WebAssembly.Instance(mod,importsFor(11)),second=new WebAssembly.Instance(mod,importsFor(12));
 root.exports.__stack_pointer.value=0x110000;first.exports.__stack_pointer.value=0x210000;second.exports.__stack_pointer.value=0x310000;
 root.exports.setup();contexts[10]=root.exports.root_pointer();contexts[11]=root.exports.first_pointer();contexts[12]=root.exports.second_pointer();
 const r=WebAssembly.promising(root.exports.start_root)();await rootEntered.promise;
 const f=WebAssembly.promising(first.exports.start_first)();await parked[11].promise;
 const s=WebAssembly.promising(second.exports.start_second)();await parked[12].promise;
 assert.equal(root.exports.read_init(),1);assert.equal(root.exports.read_finished(),0);assert.equal(root.exports.read_live(),2);assert.notEqual(root.exports.read_flag(),0);assert.notEqual(root.exports.read_flag(),1);
 rootYield.resolve();assert.equal(await r,0);assert.equal(await f,1);assert.equal(await s,1);
 assert.equal(root.exports.read_flag(),1);assert.equal(root.exports.read_init(),1);assert.equal(root.exports.read_admitted(),2);assert.equal(root.exports.read_settled(),2);assert.equal(root.exports.read_live(),0);assert.equal(root.exports.read_parked(),2);assert.equal(root.exports.read_woken(),2);
 for(const scenario of [1,2]){
  const mem=new WebAssembly.Memory({initial:64,maximum:64});const sleeping=gate(),release=gate();let ctx;
  const instance=new WebAssembly.Instance(mod,{env:{memory:mem},test:{context:()=>ctx,yield:new WebAssembly.Suspending(()=>{throw Error('unexpected initializer yield');})},'$root':{'[thread-suspend]':new WebAssembly.Suspending(()=>{sleeping.resolve();return release.promise;}),'[thread-resume-later]':()=>{throw Error('unexpected wake');}}});
  instance.exports.__stack_pointer.value=0x110000;instance.exports.setup();ctx=instance.exports.root_pointer();instance.exports.set_scenario(scenario);
  const pending=WebAssembly.promising(instance.exports.start_root)();
  if(scenario===1){await sleeping.promise;assert.equal(instance.exports.read_live(),1);assert.notEqual(instance.exports.read_flag(),1);release.resolve(1);}
  await assert.rejects(pending,WebAssembly.RuntimeError);
  assert.notEqual(instance.exports.read_flag(),1);assert.equal(instance.exports.read_init(),1);assert.equal(instance.exports.read_settled(),0);
  if(scenario===1)assert.equal(instance.exports.read_live(),1);
 }
 console.log('actual once source: one initializer, two suspended mixed-API waiters, two settled Wait doubles; recursion and initializer traps retained; JSPI test ports only');
})().catch(e=>{console.error(e);process.exitCode=1});
