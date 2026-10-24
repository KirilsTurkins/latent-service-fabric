//! Diagnostic wire bridge to the ORIGINAL ActivationRuntime, without policy,
//! node installation, networking or any claim of complete runtime cost.
use super::{State, Linker};
use latent_component_bindings::host::activation::latent::runtime::activation as wit;
use latent_core::activation_runtime::{ActivationRuntime,OwnerKind,RuntimeOwner,RuntimeToken,RuntimePhase,RuntimeLimits};
use latent_core::{ActivationBudget,BudgetProfile,ClockSample,EffectiveActivationBudget,ResourceBudget,PlatformError,PlatformErrorCode};
use std::{sync::Arc,time::{Instant,SystemTime,UNIX_EPOCH}};

struct Signal;
impl latent_core::BudgetCancellationProbe for Signal {
    fn is_cancelled(&self)->bool {false}
    fn cancelled(&self)->latent_core::BoxFuture<'_,()> {Box::pin(std::future::pending())}
    fn mark_terminal(&self) {}
}
pub(super) fn runtime()->wasmtime::Result<ActivationRuntime> {
    let grant=ResourceBudget {cpu_fuel:1_000_000_000,memory_bytes:128*1024*1024,
        wall_time_limit_millis:Some(20_000),child_calls:0,outbound_requests:0,state_read_bytes:0,
        state_write_bytes:0,blob_read_bytes:0,blob_write_bytes:0,log_bytes:0,effect_count:0};
    let effective=EffectiveActivationBudget::admit_profile_at(BudgetProfile::Phase3,&grant,&grant,&grant,
        None,ClockSample::system_now()).map_err(|e|wasmtime::Error::msg(format!("probe admission: {e:?}")))?;
    let budget=ActivationBudget::with_profile(effective,BudgetProfile::Phase3)
        .map_err(|e|wasmtime::Error::msg(format!("probe budget: {e:?}")))?;
    budget.enable_descendants(latent_core::DelegationLimits::default(),Arc::new(Signal)).map_err(error)?;
    ActivationRuntime::new(budget,RuntimeLimits {tasks:16,executors:2,queued_work:16,waits:8,
        timers:8,results:8,native_owners:64}).map_err(error)
}
fn error(e:PlatformError)->wasmtime::Error {wasmtime::Error::msg(format!("original runtime: {e:?}"))}
fn convert(e:PlatformError)->wit::Error {
    match e.code {PlatformErrorCode::ResourceExhausted=>wit::Error::ResourceExhausted,
        PlatformErrorCode::Cancelled=>wit::Error::Cancelled,PlatformErrorCode::DeadlineExceeded=>wit::Error::Deadline,
        PlatformErrorCode::InvalidArgument=>wit::Error::InvalidToken,_=>wit::Error::InvalidState}
}
fn token(value:wit::Token)->RuntimeToken {RuntimeToken{generation:value.generation,id:value.id}}
fn kind(value:wit::OwnerKind)->OwnerKind {match value {
    wit::OwnerKind::Task=>OwnerKind::Task,wit::OwnerKind::ManagedIdleWorker=>OwnerKind::ManagedIdleWorker,
    wit::OwnerKind::Executor=>OwnerKind::Executor,wit::OwnerKind::QueuedWork=>OwnerKind::QueuedWork,
    wit::OwnerKind::Wait=>OwnerKind::Wait,wit::OwnerKind::Timer=>OwnerKind::Timer,
    wit::OwnerKind::Result=>OwnerKind::Result,wit::OwnerKind::Native=>OwnerKind::Native}}
fn phase(value:RuntimePhase)->wit::Phase {match value {
    RuntimePhase::Running=>wit::Phase::Running,RuntimePhase::Waiting=>wit::Phase::Waiting,
    RuntimePhase::Closing=>wit::Phase::Closing,RuntimePhase::Draining=>wit::Phase::Draining,
    RuntimePhase::Cancelling=>wit::Phase::Cancelling,RuntimePhase::Retired=>wit::Phase::Retired}}
pub(super) fn install(linker:&mut Linker<State>)->wasmtime::Result<()> {
    let mut host=linker.instance("latent:runtime/activation@0.1.0")?;
    host.func_wrap("register",|mut store,(k,parent):(wit::OwnerKind,Option<wit::Token>)| {
        let state=store.data_mut();
        let original_kind=kind(k);let original_parent=parent.map(token);
        let result=match state.runtime.register(original_kind,original_parent).map_err(convert) {
            Ok(owner)=>{
                let value=owner.token();state.owners.push(owner);
                // Observe only AFTER the original owner is held. Refusing an
                // unknown diagnostic prefix cannot refund that actual owner.
                state.registered(original_kind,original_parent,value)?;
                Ok(wit::Token{generation:value.generation,id:value.id})
            },
            Err(error)=>Err(error),
        };Ok((result,))
    })?;
    host.func_wrap("park",|store,(owner,):(wit::Token,)| {
        Ok((store.data().runtime.park(token(owner)).map(|_|()).map_err(convert),))
    })?;
    host.func_wrap("wake",|store,(owner,):(wit::Token,)| {
        Ok((if store.data().runtime.wake(token(owner)){Ok(())}else{Err(wit::Error::InvalidToken)},))
    })?;
    host.func_wrap("settle",|mut store,(owner,):(wit::Token,)| {
        let state=store.data_mut();let target=token(owner);
        let result=if let Some(index)=state.owners.iter().position(|item:&RuntimeOwner|item.token()==target) {
            drop(state.owners.swap_remove(index));Ok(())
        } else {Err(wit::Error::InvalidToken)};Ok((result,))
    })?;
    host.func_wrap("close",|store,():()| {store.data().runtime.close();Ok((Ok::<(),wit::Error>(()),))})?;
    host.func_wrap("observe",|store,():()| {
        let s=store.data().runtime.snapshot();Ok((Ok::<_,wit::Error>(wit::Observation{
            phase:phase(s.phase),tasks:s.owners[0],executors:s.owners[1],queued_work:s.owners[2],
            waits:s.owners[3],timers:s.owners[4],results:s.owners[5],native_owners:s.owners[6],
            parked_tasks:s.parked_tasks,managed_idle_workers:s.managed_idle_workers,
            native_memory_bytes:s.host_memory_bytes,admission_failures:s.admission_failures,stale_wakes:s.stale_wakes}),))
    })?;
    // No timer is used by this closed resource fixture. Refuse concrete timer
    // requests rather than simulate elapsed success or fabricate an owner.
    for name in ["wait-for","wait-until"] {
        host.func_wrap_concurrent(name,|_,(_n,_parent):(u64,Option<wit::Token>)| {
            Box::pin(async {Ok((Err::<(),_>(wit::Error::Unavailable),))})
        })?;
    }
    host.func_wrap("timer-start",|_,(_delay,_period,_parent):(u64,Option<u64>,Option<wit::Token>)|
        Ok((Err::<wit::Token,_>(wit::Error::Unavailable),)))?;
    host.func_wrap("timer-stop",|_,(_timer,):(wit::Token,)|Ok((Err::<(),_>(wit::Error::Unavailable),)))?;
    host.func_wrap_concurrent("timer-next",|_,(_timer,):(wit::Token,)| {
        Box::pin(async {Ok((Err::<u64,_>(wit::Error::Unavailable),))})
    })?;
    let epoch=Instant::now();
    linker.instance("latent:clock/monotonic@0.1.0")?.func_wrap("now-nanos",move|_,():()|
        Ok((u64::try_from(epoch.elapsed().as_nanos())?,)))?;
    linker.instance("latent:clock/wall@0.1.0")?.func_wrap("now-unix-millis",|_,():()|
        Ok((u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?,)))?;
    Ok(())
}
