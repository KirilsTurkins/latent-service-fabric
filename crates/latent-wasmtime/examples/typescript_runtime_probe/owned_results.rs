//! Actual canonical OWN lowering/drop and capacity-one payload reuse. This is
//! a diagnostic Component linker, not signed node/policy/provider qualification.
use super::{Component,Engine};
use std::{sync::{Arc,Mutex},time::Duration};
use wasmtime::{component::{Linker,Resource,ResourceType,Val},Store,StoreLimits,StoreLimitsBuilder,ResourceLimiter};
use latent_core::activation_runtime::{ActivationRuntime,RuntimeOwner,RuntimeToken,OwnerKind};
#[path="owned_results_runtime.rs"]
mod runtime_bridge;

const MEMORY:usize=128*1024*1024;
const FUEL:u64=1_000_000_000;
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
enum Kind {Connection,Chunk}
struct Connection;
struct Chunk;
#[derive(Clone,Default,Debug)]
struct Counts {allocations:u32,drops:u32,connection_drops:u32,chunk_drops:u32,payload_drops:u32,
    exhaustions:u32,future_starts:u32,future_drops:u32,pending_mode_starts:u32}
struct Payload {kind:Kind,rep:u32,counts:Arc<Mutex<Counts>>}
impl Drop for Payload {fn drop(&mut self){self.counts.lock().unwrap().payload_drops+=1;}}
struct Pending(Arc<Mutex<Counts>>);
impl Pending {fn new(counts:Arc<Mutex<Counts>>)->Self {counts.lock().unwrap().future_starts+=1;Self(counts)}}
impl Drop for Pending {fn drop(&mut self){self.0.lock().unwrap().future_drops+=1;}}

#[derive(Clone,Copy)]
struct Registration {kind:OwnerKind,parent:Option<RuntimeToken>,token:RuntimeToken}
#[derive(Clone,Copy)]
struct ImportOwners {record:RuntimeToken,buffer:RuntimeToken,result:RuntimeToken}

pub(super) struct State {
    runtime:ActivationRuntime,
    owners:Vec<RuntimeOwner>,
    limits:StoreLimits,
    memory:usize,
    pending_growth:usize,
    slot:Option<Payload>,
    next_rep:u32,
    refuse_drop:bool,
    counts:Arc<Mutex<Counts>>,
    // Diagnostic observations only. These scalar copies grant no authority,
    // settle nothing and never replace the original ActivationRuntime owners.
    recent_registrations:[Option<Registration>;4],
    import_owners:[Option<ImportOwners>;2],
    observed_imports:usize,
    observation_failed:bool,
}
impl State {
    fn registered(&mut self,kind:OwnerKind,parent:Option<RuntimeToken>,token:RuntimeToken)->wasmtime::Result<()> {
        wasmtime::ensure!(!self.observation_failed,"own-probe-owner-observation-stopped");
        let observed=(||->wasmtime::Result<Option<ImportOwners>> {
            if kind!=OwnerKind::Result {return Ok(None);}
            // Authenticated SDK source sequence: Imports::reserve admits its
            // Record Native, then BrokerAccounting Task/Queued, then the
            // buffer Native and Result in BrokerImportAccounting::admit.
            // Persistent-root field construction between these steps does not
            // construct a JS object or invoke a host registration.
            let [Some(record),Some(task),Some(queue),Some(buffer)]=self.recent_registrations else {
                wasmtime::bail!("own-probe-owner-registration-prefix-missing");
            };
            wasmtime::ensure!(record.kind==OwnerKind::Native&&task.kind==OwnerKind::Task&&
                queue.kind==OwnerKind::QueuedWork&&buffer.kind==OwnerKind::Native,
                "own-probe-owner-registration-prefix-kind");
            wasmtime::ensure!(record.parent.is_some()&&record.parent==task.parent&&
                record.parent==buffer.parent&&queue.parent==Some(task.token)&&parent==Some(task.token),
                "own-probe-owner-registration-prefix-parent");
            wasmtime::ensure!([record.token,task.token,queue.token,buffer.token].iter()
                .all(|value|value.generation==token.generation&&value.id!=0)&&token.id!=0,
                "own-probe-owner-registration-prefix-generation");
            wasmtime::ensure!(record.token!=buffer.token&&record.token!=token&&buffer.token!=token,
                "own-probe-owner-registration-prefix-identity");
            wasmtime::ensure!(self.observed_imports<self.import_owners.len()&&
                self.import_owners[self.observed_imports].is_none(),"own-probe-owner-observation-capacity");
            Ok(Some(ImportOwners{record:record.token,buffer:buffer.token,result:token}))
        })();
        match observed {
            Ok(Some(owners))=>{self.import_owners[self.observed_imports]=Some(owners);self.observed_imports+=1;},
            Ok(None)=>{},
            Err(error)=>{self.observation_failed=true;return Err(error);},
        }
        self.recent_registrations.rotate_left(1);
        self.recent_registrations[3]=Some(Registration{kind,parent,token});
        Ok(())
    }
    fn allocate(&mut self,kind:Kind)->Result<u32,u32> {
        if self.slot.is_some(){self.counts.lock().unwrap().exhaustions+=1;return Err(33);}
        let rep=self.next_rep;self.next_rep=self.next_rep.checked_add(1).ok_or(33_u32)?;
        self.counts.lock().unwrap().allocations+=1;
        self.slot=Some(Payload{kind,rep,counts:self.counts.clone()});Ok(rep)
    }
    fn destroy(&mut self,kind:Kind,rep:u32)->wasmtime::Result<()> {
        {let mut counts=self.counts.lock().unwrap();counts.drops+=1;
         match kind {Kind::Connection=>counts.connection_drops+=1,Kind::Chunk=>counts.chunk_drops+=1}}
        let payload=self.slot.as_ref().ok_or_else(||wasmtime::Error::msg("own-probe-empty-slot-drop"))?;
        wasmtime::ensure!(payload.kind==kind&&payload.rep==rep,"own-probe-type-or-representation-mismatch");
        wasmtime::ensure!(!self.refuse_drop,"owned-probe-drop-refusal");
        drop(self.slot.take());Ok(())
    }
}
impl ResourceLimiter for State {
    fn memory_growing(&mut self,current:usize,desired:usize,maximum:Option<usize>)->wasmtime::Result<bool> {
        self.pending_growth=0;
        let growth=desired.saturating_sub(current);
        let total=self.memory.checked_add(growth).ok_or_else(||wasmtime::Error::msg("own-probe-memory-overflow"))?;
        wasmtime::ensure!(total<=MEMORY,"own-probe-aggregate-memory-limit");
        let allowed=self.limits.memory_growing(current,desired,maximum)?;
        if allowed {self.memory=total;self.pending_growth=growth;}Ok(allowed)
    }
    fn memory_grow_failed(&mut self,error:wasmtime::Error)->wasmtime::Result<()> {
        self.memory-=self.pending_growth;self.pending_growth=0;self.limits.memory_grow_failed(error)
    }
    fn table_growing(&mut self,current:usize,desired:usize,maximum:Option<usize>)->wasmtime::Result<bool> {
        self.pending_growth=0;self.limits.table_growing(current,desired,maximum)
    }
}
fn install(linker:&mut Linker<State>)->wasmtime::Result<()> {
    runtime_bridge::install(linker)?;
    let mut provider=linker.instance("tests:owned-result/provider@1.0.0")?;
    provider.resource("connection",ResourceType::host::<Connection>(),|mut store,rep|
        store.data_mut().destroy(Kind::Connection,rep))?;
    provider.resource("chunk",ResourceType::host::<Chunk>(),|mut store,rep|
        store.data_mut().destroy(Kind::Chunk,rep))?;
    provider.func_wrap_concurrent("take-connection",|access,(mode,):(u32,)| {
        Box::pin(async move {
            let counter=access.with(|mut store|store.data_mut().counts.clone());
            let _pending=Pending::new(counter);
            if mode==1 {tokio::task::yield_now().await;}
            if mode==4 {
                access.with(|mut store|store.data_mut().counts.lock().unwrap().pending_mode_starts+=1);
                std::future::pending::<()>().await;
            }
            let value=match mode {
                2=>Ok(None),3=>Err(17),
                _=>access.with(|mut store|store.data_mut().allocate(Kind::Connection)).map(|rep|Some(Resource::<Connection>::new_own(rep))),
            };
            Ok((value,))
        })
    })?;
    provider.func_wrap_concurrent("take-chunk",|access,(mode,):(u32,)| {
        Box::pin(async move {
            let counter=access.with(|mut store|store.data_mut().counts.clone());let _pending=Pending::new(counter);
            if mode==1 {tokio::task::yield_now().await;}
            let value=access.with(|mut store|store.data_mut().allocate(Kind::Chunk))
                .map(|rep|Some(Resource::<Chunk>::new_own(rep)));Ok((value,))
        })
    })?;
    provider.func_wrap_concurrent("nested",|access,(mode,):(u32,)| {
        Box::pin(async move {
            let counter=access.with(|mut store|store.data_mut().counts.clone());let _pending=Pending::new(counter);
            let value=if mode==2 {Ok(vec![None])} else {
                access.with(|mut store|store.data_mut().allocate(Kind::Connection))
                    .map(|rep|vec![Some(Resource::<Connection>::new_own(rep))])
            };Ok((value,))
        })
    })?;
    Ok(())
}

pub(super) async fn run(engine:&Engine,component:&Component)->wasmtime::Result<()> {
    let mut linker=Linker::new(engine);install(&mut linker)?;
    let expected=[1_u32,2,2,2,1,0,2,0,1,2,0];
    let expected_imports=[1_usize,2,2,2,2,1,2,1,1,2,1];
    for (which,allocations) in expected.into_iter().enumerate() {
        let counts=Arc::new(Mutex::new(Counts::default()));
        let state=State{runtime:runtime_bridge::runtime()?,owners:Vec::with_capacity(122),
            limits:StoreLimitsBuilder::new().memory_size(MEMORY).build(),memory:0,pending_growth:0,
            slot:None,next_rep:1,refuse_drop:which==8,counts:counts.clone(),
            recent_registrations:[None;4],import_owners:[None;2],observed_imports:0,observation_failed:false};
        let mut store=Store::new(engine,state);store.limiter(|state|state);store.set_fuel(FUEL)?;
        let instance=linker.instantiate_async(&mut store,component).await?;
        let (_,api)=instance.get_export(&mut store,None,"tests:owned-result/api@1.0.0")
            .ok_or_else(||wasmtime::Error::msg("own-probe-api-missing"))?;
        let (_,export)=instance.get_export(&mut store,Some(&api),"run")
            .ok_or_else(||wasmtime::Error::msg("own-probe-run-missing"))?;
        let function=instance.get_func(&mut store,export).ok_or_else(||wasmtime::Error::msg("own-probe-function-missing"))?;
        let mut output=[Val::Bool(false)];
        let result=tokio::time::timeout(Duration::from_secs(20),
            function.call_async(&mut store,&[Val::U32(u32::try_from(which)?)],&mut output)).await?;
        if which==8 {
            let error=result.expect_err("canonical destructor refusal must trap");
            wasmtime::ensure!(format!("{error:#}").contains("owned-probe-drop-refusal"),"own-probe-unexpected-trap");
        } else {result?;wasmtime::ensure!(output==[Val::Bool(true)],"own-probe-public-result");}
        let before=counts.lock().unwrap().clone();
        let live=store.data().slot.is_some();let snapshot=store.data().runtime.snapshot();
        wasmtime::ensure!(!store.data().observation_failed&&store.data().observed_imports==expected_imports[which],
            "own-probe-exact-import-owner-observations");
        let mut matched_native_live=0;let mut matched_result_live=0;
        for original in store.data().import_owners.iter().flatten() {
            for token in [original.record,original.buffer] {
                matched_native_live+=u32::from(store.data().owners.iter().any(|owner|owner.token()==token));
            }
            matched_result_live+=u32::from(store.data().owners.iter().any(|owner|owner.token()==original.result));
        }
        if which==8 {
            wasmtime::ensure!(matched_native_live==2&&matched_result_live==1&&snapshot.owners[5]>0&&
                snapshot.owners[6]>=matched_native_live,"own-probe-refused-original-owners-must-remain");
        } else {
            wasmtime::ensure!(snapshot.owners[5]==0&&matched_native_live==0&&matched_result_live==0,
                "own-probe-original-import-owners-not-retired-before-store-drop");
        }
        wasmtime::ensure!(before.allocations==allocations&&before.drops==allocations,"own-probe-exact-destructor-count");
        wasmtime::ensure!(before.exhaustions==0&&before.future_starts==before.future_drops,"own-probe-retained-provider-future");
        wasmtime::ensure!(before.pending_mode_starts==u32::from(which==7),"own-probe-real-pending-provider-branch");
        if which==7 {
            // Wasmtime call_async_lower -> Instance::first_poll polls the real
            // host Future before returning STARTED to this canonical caller.
            // cancelMode2 runs only AFTER that original native call returns.
            // This is the actual start-before-cancel barrier, not a sleep or
            // a fabricated waitable/status/pump event.
            wasmtime::ensure!(before.future_starts==1&&before.future_drops==1&&before.allocations==0,
                "own-probe-started-pending-future-not-physically-dropped");
        }
        wasmtime::ensure!(live==(which==8),"own-probe-physical-slot-state");
        wasmtime::ensure!(before.payload_drops==if which==8 {0}else{allocations},"own-probe-payload-not-physically-dropped");
        if which==3 {wasmtime::ensure!(before.chunk_drops==2&&before.connection_drops==0,"own-probe-chunk-type-binding");}
        if which==9 {wasmtime::ensure!(before.chunk_drops==1&&before.connection_drops==1,"own-probe-distinct-type-binding");}
        let memory=store.data().memory;let fuel=FUEL-store.get_fuel()?;drop(store);
        let after=counts.lock().unwrap().clone();
        wasmtime::ensure!(after.payload_drops==allocations,"own-probe-store-drop-retained-payload");
        println!("{}",serde_json::json!({"schemaVersion":"latent.typescript.canonical-own-case.v1",
            "case":which,"status":"passed","canonicalResourceDropActual":before.drops>0,"payloadCapacity":1,
            "sameStorePayloadReuse":matches!(which,1|2|3|6|9),"canonicalTableIndexObserved":false,"allocations":before.allocations,
            "destructorCalls":before.drops,"connectionDestructorCalls":before.connection_drops,
            "chunkDestructorCalls":before.chunk_drops,"payloadDropsBeforeStoreDrop":before.payload_drops,
            "payloadDropsAfterStoreDrop":after.payload_drops,"liveBeforeStoreDrop":live,
            "futureStarts":before.future_starts,"futureDrops":before.future_drops,
            "pendingProviderStarts":before.pending_mode_starts,"matchedImportNativeOwnersBeforeStoreDrop":matched_native_live,
            "matchedImportResultOwnersBeforeStoreDrop":matched_result_live,"observedImports":expected_imports[which],
            "runtimeOwnersBeforeStoreDrop":snapshot.owners,"peakLinearMemoryBytes":memory,"fuel":fuel,
            "nestedBackingStorageQualified":false,"physicalProviderQualified":false,"signedExecution":false}));
    }
    Ok(())
}
