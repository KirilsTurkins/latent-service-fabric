//! Versioned activation-owned runtime bridge. Logical scheduling remains in
//! each maintained language runtime. Store access is bounded and never spans
//! the executor-neutral timer await; no thread sleeps for a guest timer.
use super::HostState;
use latent_capabilities::broker::{AuditProviderOutcome, CapabilityCallCost, ProviderCall};
use latent_component_bindings::host::activation::latent::runtime::activation as wit;
use latent_core::{
    activation_runtime::{
        ActivationRuntime, OwnerKind, RuntimeLimits, RuntimeOwner, RuntimePhase, RuntimeTimer,
        RuntimeToken, TimerWait,
    },
    HostMemoryReservation, PlatformError, PlatformErrorCode,
};
use latent_executor::{GuestInterruptionKind, PreparationReadWait};
use latent_policy::capability::ResourceTarget;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use wasmtime::{
    component::{Accessor, InlineConcurrentHost, Linker},
    AsContextMut,
};

mod fixed_result;
pub(super) use fixed_result::Completion;
use fixed_result::FixedValue;
mod positive_timer_observer;
use positive_timer_observer::{Event as TimerEvent, Observer as TimerObserver};

#[cfg(test)]
mod tests;

pub(crate) const CAPABILITY: &str = "latent:runtime/activation@0.1.0";
const STOP_OBSERVATION: Duration = Duration::from_millis(10);
// Per-allocation bookkeeping in the existing native accounting model; this is
// not a measurement or a bound on process RSS.
const BACKING_ALLOCATION_BOOKKEEPING: usize = 64;

fn backing_bytes<T>(count: usize) -> Option<u64> {
    if count == 0 || std::mem::size_of::<T>() == 0 {
        return Some(0);
    }
    std::alloc::Layout::array::<T>(count)
        .ok()?
        .size()
        .checked_add(BACKING_ALLOCATION_BOOKKEEPING)
        .and_then(|bytes| u64::try_from(bytes).ok())
}

/// Guards are held with actual Store-owned logical work. Tokens alone cannot
/// remove an owner, mint another activation, or establish native retirement.
pub(crate) struct Table {
    owners: Vec<RuntimeOwner>,
    timers: Vec<RuntimeTimer>,
    runtime: ActivationRuntime,
    pub(crate) native_stacks: Option<Arc<crate::native_stacks::StackContext>>,
    timer_observer: Option<TimerObserver>,
    #[cfg(feature = "development-go-timer-overlap")]
    overlap: Option<crate::development_go_timer_overlap::Observer>,
    // All actual Vec backings and the other owned fields drop before refund.
    allocation: HostMemoryReservation,
}
impl Table {
    fn new(
        budget: latent_core::ActivationBudget,
        limits: RuntimeLimits,
        timer_observer: Option<TimerObserver>,
    ) -> Result<Self, PlatformError> {
        // Validated runtime limits cap total at 8192. Both Vec backings are
        // independently prepaid before either is allocated; a zero timer limit
        // leaves its Vec unallocated.
        let owner_count = limits.total();
        let timer_count = limits.timers as usize;
        let (owner_bytes, backings_bytes, bytes) = (|| {
            let owner_bytes = backing_bytes::<RuntimeOwner>(owner_count)?;
            let timer_bytes = backing_bytes::<RuntimeTimer>(timer_count)?;
            let backings = owner_bytes.checked_add(timer_bytes)?;
            let bytes = backings.checked_add(u64::try_from(std::mem::size_of::<Self>()).ok()?)?;
            Some((owner_bytes, backings, bytes))
        })()
        .ok_or_else(|| {
            failure(
                PlatformErrorCode::ResourceExhausted,
                "runtime-table-allocation",
            )
        })?;
        let mut allocation = budget
            .reserve_host_memory(bytes)
            .map_err(|e| e.to_host_memory_error())?;
        let mut owners = Vec::new();
        owners.try_reserve_exact(owner_count).map_err(|_| {
            failure(
                PlatformErrorCode::ResourceExhausted,
                "runtime-owner-allocation",
            )
        })?;
        // Confirm each backing as it physically appears, even if a later
        // allocation fails. Unused envelope capacity stays reserved.
        allocation.confirm_bytes(owner_bytes);
        let mut timers = Vec::new();
        timers.try_reserve_exact(timer_count).map_err(|_| {
            failure(
                PlatformErrorCode::ResourceExhausted,
                "runtime-timer-allocation",
            )
        })?;
        allocation.confirm_bytes(backings_bytes);
        // Pinned Global RawVec preserves the requested exact capacities.
        // No owner is published under an unexpected backing-size contract.
        if owners.capacity() != owner_count || timers.capacity() != timer_count {
            return Err(failure(
                PlatformErrorCode::ResourceExhausted,
                "runtime-table-capacity",
            ));
        }
        let runtime = ActivationRuntime::new(budget, limits)?;
        let mut table = Self {
            owners,
            timers,
            runtime,
            native_stacks: None,
            timer_observer,
            #[cfg(feature = "development-go-timer-overlap")]
            overlap: None,
            allocation,
        };
        table.allocation.confirm();
        Ok(table)
    }
    pub(crate) fn finalize(&mut self) -> Result<(), PlatformError> {
        self.runtime.begin_drain();
        match &self.native_stacks {
            Some(stacks) => stacks.finish_logical(),
            None => self.runtime.retire(),
        }
    }
}
impl Drop for Table {
    fn drop(&mut self) {
        if let Some(stacks) = &self.native_stacks {
            stacks.cancel_unstarted();
        }
        self.runtime.cancel();
        #[cfg(feature = "development-go-timer-overlap")]
        if let Some(observer) = &self.overlap {
            observer.report();
        }
    }
}

fn table(state: &mut HostState) -> Result<&mut Table, PlatformError> {
    let limits = state.runtime_limits.ok_or_else(|| {
        failure(
            PlatformErrorCode::Unavailable,
            "runtime-profile-unavailable",
        )
    })?;
    if state.runtime.is_none() {
        let observer = TimerObserver::for_activation(&state.context.activation_id.0);
        let created = Table::new(state.accounting.budget().clone(), limits, observer)?;
        #[cfg(feature = "development-go-timer-overlap")]
        let created = {
            let mut created = created;
            if let Some(case) = crate::development_go_timer_overlap::Observer::select(
                &state.context.activation_id.0,
            ) {
                created.overlap = Some(crate::development_go_timer_overlap::Observer::new(
                    case,
                    state.accounting.budget(),
                )?);
            }
            created
        };
        state.runtime = Some(created);
    }
    let table = state.runtime.as_mut().expect("initialized table");
    table.runtime.check_live()?;
    Ok(table)
}
pub(super) fn native_context(
    state: &mut HostState,
) -> Result<Arc<crate::native_stacks::StackContext>, PlatformError> {
    let table = table(state)?;
    let context = table.native_stacks.clone().ok_or_else(|| {
        failure(
            PlatformErrorCode::Unavailable,
            "native-thread-profile-unavailable",
        )
    })?;
    Ok(context)
}
pub(crate) fn prepare_native_stack(
    state: &mut HostState,
    size: usize,
    maximum_children: usize,
    async_workers: bool,
    #[cfg(feature = "development-rust-http-combined")] combined: Option<(
        &crate::component_threading::Authentication,
        &latent_executor::PreparedComponent,
    )>,
) -> Result<Arc<crate::native_stacks::StackContext>, PlatformError> {
    let budget = state.accounting.budget().clone();
    let maximum_native = state.runtime_limits.map(|limits| limits.native_owners);
    let table = table(state)?;
    if table.native_stacks.is_some() {
        return Err(failure(
            PlatformErrorCode::Internal,
            "native-stack-context-already-created",
        ));
    }
    #[cfg(feature = "development-rust-http-combined")]
    if let Some((proof, descriptor)) = combined {
        let maximum = maximum_native.expect("initialized original runtime limits") as usize;
        if async_workers || maximum_children != maximum.saturating_sub(1) {
            return Err(failure(
                PlatformErrorCode::Internal,
                "native-stack-profile-conflict",
            ));
        }
        let context = crate::native_stacks::StackContext::with_combined_http(
            budget,
            table.runtime.clone(),
            size,
            maximum,
            proof,
            descriptor,
        )?;
        table.native_stacks = Some(Arc::clone(&context));
        return Ok(context);
    }
    let context = if async_workers {
        if maximum_children != 0 {
            return Err(failure(
                PlatformErrorCode::Internal,
                "native-stack-profile-conflict",
            ));
        }
        crate::native_stacks::StackContext::with_async_workers(
            budget,
            table.runtime.clone(),
            size,
            maximum_native.expect("initialized original runtime limits") as usize,
        )?
    } else if maximum_children == 0 {
        crate::native_stacks::StackContext::new(budget, table.runtime.clone(), size)?
    } else {
        crate::native_stacks::StackContext::with_children(
            budget,
            table.runtime.clone(),
            size,
            maximum_children,
        )?
    };
    table.native_stacks = Some(Arc::clone(&context));
    Ok(context)
}

fn authorize(state: &HostState, operation: &str) -> Result<ProviderCall, PlatformError> {
    authorize_for(state, CAPABILITY, operation, ResourceTarget::Clock)
}

pub(super) fn authorize_for(
    state: &HostState,
    capability: &str,
    operation: &str,
    target: ResourceTarget<'_>,
) -> Result<ProviderCall, PlatformError> {
    if let Some(stop) = &state.runtime_stop {
        if let Some(kind) = stop.observe() {
            return Err(failure(
                if kind == GuestInterruptionKind::DeadlineExceeded {
                    PlatformErrorCode::DeadlineExceeded
                } else {
                    PlatformErrorCode::Cancelled
                },
                "runtime-stopped",
            ));
        }
    }
    // This exact capability/operation requires its own binding and grant.
    // Permission for either clock-read interface does not match this contract.
    // Match the installed activation-owned-v1 profile's mandatory host-call
    // charge before dispatch. Logical runtime work keeps its separate charges
    // on the same original ledger; ownership limits do not fund a host call.
    let cost =
        CapabilityCallCost::new(128).with_charge(latent_core::BudgetDimension::CpuFuel, 100)?;
    state
        .capabilities
        .begin_typed(capability, operation, target, &[], cost)?
        .ok_or_else(|| {
            failure(
                PlatformErrorCode::PermissionDenied,
                "runtime-grant-required",
            )
        })
}

fn synchronous<T>(
    state: &mut HostState,
    operation: &str,
    execute: impl FnOnce(&mut Table) -> Result<T, PlatformError>,
) -> Completion<Result<T, wit::Error>>
where
    Result<T, wit::Error>: FixedValue,
{
    let started = Instant::now();
    let mut call = match authorize(state, operation) {
        Ok(call) => call,
        Err(error) => {
            #[cfg(feature = "development-test-host")]
            observe_borrow_registration_refusal(state, operation, &error);
            return Completion::new(Err(convert(error)), None);
        }
    };
    let result = table(state).and_then(execute);
    if let Err(error) = &result {
        observe_runtime_refusal(state, error);
    }
    #[cfg(feature = "development-test-host")]
    if let Err(error) = &result {
        observe_borrow_registration_refusal(state, operation, error);
    }
    let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
    state.record_host_call(started);
    Completion::new(result.map_err(convert), Some(call))
}

pub(super) fn observe_runtime_refusal(state: &HostState, error: &PlatformError) {
    if let Some(session) = &state.capabilities.session {
        session.observe_runtime_refusal(error);
    }
}

#[cfg(feature = "development-test-host")]
fn observe_borrow_registration_refusal(
    state: &mut HostState,
    operation: &str,
    error: &PlatformError,
) {
    if operation != "register" || state.development_borrow_admission.is_none() {
        return;
    }
    let runtime = state.runtime.as_ref().map(|table| table.runtime.snapshot());
    let remaining = state.accounting.budget().remaining_at(Instant::now());
    let granted = state.accounting.budget().granted();
    state
        .development_borrow_admission
        .as_mut()
        .expect("selected original HostState")
        .refused(error, runtime, state.runtime_limits, granted, &remaining);
}

#[expect(
    clippy::too_many_lines,
    reason = "register the eleven authoritative operations together, with explicit sync and async ABI shapes"
)]
pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    macro_rules! sync {
        ($name:literal, $args:pat, $ty:ty, $execute:expr $(, $register_kind:expr)?) => {
            linker
                .instance(CAPABILITY)?
                .func_wrap_ready($name, |mut store, $args: $ty| {
                    super::service::checkpoint(&mut store)?;
                    #[cfg(feature = "development-test-host")]
                    {
                        $(if let Some(observer) = &mut store.data_mut().development_borrow_admission {
                            observer.prepare_register(owner_kind($register_kind));
                        })?
                    }
                    let result = synchronous(store.data_mut(), $name, $execute);
                    super::service::synchronize(&mut store)?;
                    Ok((result,))
                })?;
        };
    }
    sync!(
        "register",
        (kind, continuation),
        (wit::OwnerKind, Option<wit::Token>),
        |table| {
            let kind = owner_kind(kind);
            let parent = continuation.map(token);
            let owner = table.runtime.register(kind, parent)?;
            let value = owner.token();
            table.owners.push(owner);
            #[cfg(feature = "development-go-timer-overlap")]
            if let Some(observer) = &table.overlap {
                observer.task(kind, value, parent);
            }
            Ok(wit::Token {
                generation: value.generation,
                id: value.id,
            })
        },
        kind
    );
    sync!("park", (owner,), (wit::Token,), |table| {
        let owner = token(owner);
        table.runtime.park(owner)?;
        #[cfg(feature = "development-go-timer-overlap")]
        if let Some(observer) = &table.overlap {
            observer.park(owner, table.runtime.snapshot().owners[3]);
        }
        Ok(())
    });
    sync!("wake", (owner,), (wit::Token,), |table| {
        let owner = token(owner);
        if table.runtime.wake(owner) {
            #[cfg(feature = "development-go-timer-overlap")]
            if let Some(observer) = &table.overlap {
                observer.wake(owner);
            }
            Ok(())
        } else {
            Err(failure(PlatformErrorCode::InvalidArgument, "runtime-token"))
        }
    });
    sync!("settle", (owner,), (wit::Token,), |table| {
        let token = token(owner);
        let index = table
            .owners
            .iter()
            .position(|owner| owner.token() == token)
            .ok_or_else(|| failure(PlatformErrorCode::InvalidArgument, "runtime-token"))?;
        drop(table.owners.swap_remove(index));
        Ok(())
    });
    sync!("close", (), (), |table| {
        table.runtime.close();
        if let Some(observer) = &table.timer_observer {
            observer.record(TimerEvent::RootClose, table.runtime.snapshot().owners);
        }
        Ok(())
    });
    sync!("observe", (), (), |table| {
        let snapshot = table.runtime.snapshot();
        Ok(wit::Observation {
            phase: phase(snapshot.phase),
            tasks: snapshot.owners[0],
            executors: snapshot.owners[1],
            queued_work: snapshot.owners[2],
            waits: snapshot.owners[3],
            timers: snapshot.owners[4],
            results: snapshot.owners[5],
            native_owners: snapshot.owners[6],
            parked_tasks: snapshot.parked_tasks,
            managed_idle_workers: snapshot.managed_idle_workers,
            native_memory_bytes: snapshot.host_memory_bytes,
            admission_failures: snapshot.admission_failures,
            stale_wakes: snapshot.stale_wakes,
        })
    });
    linker.instance(CAPABILITY)?.func_wrap_ready(
        "timer-start",
        |mut store, (delay, period, continuation): (u64, Option<u64>, Option<wit::Token>)| {
            super::service::checkpoint(&mut store)?;
            let first = store
                .data()
                .clock
                .monotonic_now()
                .checked_add(Duration::from_nanos(delay));
            let result = synchronous(store.data_mut(), "timer-start", |table| {
                let first = first.ok_or_else(|| {
                    failure(PlatformErrorCode::InvalidArgument, "runtime-timer-range")
                })?;
                let parent = continuation.map(token);
                let timer = RuntimeTimer::new(
                    &table.runtime,
                    first,
                    period.map(Duration::from_nanos),
                    parent,
                )?;
                let value = timer.token();
                table.timers.push(timer);
                #[cfg(feature = "development-go-timer-overlap")]
                if let Some(observer) = &table.overlap {
                    observer.timer_start(value, parent, period);
                }
                if let Some(observer) = &table.timer_observer {
                    observer.record(TimerEvent::StartAccepted, table.runtime.snapshot().owners);
                }
                Ok(wit::Token {
                    generation: value.generation,
                    id: value.id,
                })
            });
            super::service::synchronize(&mut store)?;
            Ok((result,))
        },
    )?;
    sync!("timer-stop", (timer,), (wit::Token,), |table| {
        let token = token(timer);
        let index = table
            .timers
            .iter()
            .position(|timer| timer.token() == token)
            .ok_or_else(|| failure(PlatformErrorCode::InvalidArgument, "runtime-timer-token"))?;
        let timer = table.timers.swap_remove(index);
        timer.close();
        #[cfg(feature = "development-go-timer-overlap")]
        if let Some(observer) = &table.overlap {
            observer.timer_stop(token, table.runtime.snapshot().owners[3]);
        }
        drop(timer);
        Ok(())
    });
    linker
        .instance(CAPABILITY)?
        .func_wrap_concurrent_inline("timer-next", TimerNext)?;
    for operation in ["wait-for", "wait-until"] {
        linker
            .instance(CAPABILITY)?
            .func_wrap_concurrent_inline(operation, RuntimeWait { operation })?;
    }
    Ok(())
}

struct TimerNext;
impl InlineConcurrentHost<HostState, (wit::Token,), (Completion<Result<u64, wit::Error>>,)>
    for TimerNext
{
    async fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (timer,): (wit::Token,),
    ) -> wasmtime::Result<(Completion<Result<u64, wit::Error>>,)> {
        let started = Instant::now();
        let PreparedWait {
            result: prepared,
            failed_call,
        } = access.with(|mut access| {
            let mut store = access.as_context_mut();
            super::service::checkpoint(&mut store)?;
            let prepared = prepare_timer_next(store.data_mut(), token(timer));
            super::service::synchronize(&mut store)?;
            Ok::<_, wasmtime::Error>(prepared)
        })?;
        let (result, call) = match prepared {
            Ok(mut wait) => {
                let result = wait.run().await;
                #[cfg(feature = "development-go-timer-overlap")]
                if let Some(overlap) = &mut wait.overlap {
                    overlap.returned = true;
                }
                let _ = wait
                    .call
                    .record_provider_outcome(AuditProviderOutcome::HostCompleted);
                (result.map_err(convert), Some(wait.call))
            }
            Err(error) => completed_failure(error, failed_call),
        };
        access.with(|mut access| {
            let mut store = access.as_context_mut();
            super::service::checkpoint(&mut store)?;
            super::service::synchronize(&mut store)?;
            store.data_mut().record_host_call(started);
            Ok((Completion::new(result, call),))
        })
    }
}

struct RuntimeWait {
    operation: &'static str,
}
impl
    InlineConcurrentHost<
        HostState,
        (u64, Option<wit::Token>),
        (Completion<Result<(), wit::Error>>,),
    > for RuntimeWait
{
    async fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (value, continuation): (u64, Option<wit::Token>),
    ) -> wasmtime::Result<(Completion<Result<(), wit::Error>>,)> {
        let started = Instant::now();
        let PreparedWait {
            result: prepared,
            failed_call,
        } = access.with(|mut access| {
            let mut store = access.as_context_mut();
            super::service::checkpoint(&mut store)?;
            let prepared = prepare_wait(
                store.data_mut(),
                self.operation,
                value,
                continuation.map(token),
            );
            super::service::synchronize(&mut store)?;
            Ok::<_, wasmtime::Error>(prepared)
        })?;
        let (result, call) = match prepared {
            Ok(mut wait) => {
                let result = wait.run().await;
                let _ = wait
                    .call
                    .record_provider_outcome(AuditProviderOutcome::HostCompleted);
                (result.map(|_| ()).map_err(convert), Some(wait.call))
            }
            Err(error) => completed_failure(error, failed_call),
        };
        access.with(|mut access| {
            let mut store = access.as_context_mut();
            super::service::checkpoint(&mut store)?;
            super::service::synchronize(&mut store)?;
            store.data_mut().record_host_call(started);
            Ok((Completion::new(result, call),))
        })
    }
}

struct WaitingTimer {
    runtime: ActivationRuntime,
    _owner: Option<RuntimeOwner>,
    timer_wait: Option<TimerWait>,
    // Struct fields drop in declaration order, including after `call` is moved
    // out. Thus the observer runs after the original TimerWait destruction.
    #[cfg(feature = "development-go-timer-overlap")]
    overlap: Option<OverlapCompletion>,
    wait_observer: Option<TimerObserver>,
    wait_observed: bool,
    wait: Arc<dyn PreparationReadWait>,
    clock: Arc<dyn latent_core::ActivationClock>,
    stop: Arc<crate::containment::StopControl>,
    requested: Instant,
    call: ProviderCall,
}

#[cfg(feature = "development-go-timer-overlap")]
struct OverlapCompletion {
    observer: crate::development_go_timer_overlap::Observer,
    token: RuntimeToken,
    barrier_done: bool,
    returned: bool,
}

#[cfg(feature = "development-go-timer-overlap")]
impl Drop for OverlapCompletion {
    fn drop(&mut self) {
        if self.returned {
            self.observer.next_finished(self.token);
        }
        self.observer.report_wait_drop(self.token, self.returned);
    }
}
struct PreparedWait {
    result: Result<WaitingTimer, PlatformError>,
    failed_call: Option<ProviderCall>,
}
fn completed_failure<T>(
    error: PlatformError,
    mut call: Option<ProviderCall>,
) -> (Result<T, wit::Error>, Option<ProviderCall>) {
    if let Some(call) = call.as_mut() {
        let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
    }
    (Err(convert(error)), call)
}
fn prepare_wait(
    state: &mut HostState,
    operation: &str,
    value: u64,
    continuation: Option<RuntimeToken>,
) -> PreparedWait {
    let mut call = match authorize(state, operation) {
        Ok(call) => Some(call),
        Err(error) => {
            return PreparedWait {
                result: Err(error),
                failed_call: None,
            };
        }
    };
    let result = (|| {
        let wait = state.currentness_read_wait.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "runtime-timer-provider-unavailable",
            )
        })?;
        let stop = state.runtime_stop.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "runtime-stop-owner-unavailable",
            )
        })?;
        let clock = Arc::clone(&state.clock);
        let sample = clock.sample();
        let elapsed = if operation == "wait-for" {
            Duration::from_nanos(value)
        } else {
            Duration::from_millis(value.saturating_sub(sample.unix_millis()))
        };
        let requested = sample.monotonic().checked_add(elapsed).ok_or_else(|| {
            failure(
                PlatformErrorCode::InvalidArgument,
                "runtime-timer-out-of-range",
            )
        })?;
        let table = table(state)?;
        let runtime = table.runtime.clone();
        let wait_observer = table.timer_observer.filter(|_| operation == "wait-for");
        let owner = runtime.register(OwnerKind::Timer, continuation)?;
        Ok(WaitingTimer {
            runtime,
            _owner: Some(owner),
            timer_wait: None,
            #[cfg(feature = "development-go-timer-overlap")]
            overlap: None,
            wait_observer,
            wait_observed: false,
            wait,
            clock,
            stop,
            requested,
            call: call.take().expect("original accepted runtime call"),
        })
    })();
    // A failed timer preparation has no pending producer, but its accepted
    // call still owns the fixed error result through actual canonical lowering.
    if let Err(error) = &result {
        observe_runtime_refusal(state, error);
    }
    PreparedWait {
        result,
        failed_call: call,
    }
}
fn prepare_timer_next(state: &mut HostState, token: RuntimeToken) -> PreparedWait {
    let mut call = match authorize(state, "timer-next") {
        Ok(call) => Some(call),
        Err(error) => {
            return PreparedWait {
                result: Err(error),
                failed_call: None,
            };
        }
    };
    let result = (|| {
        let wait = state.currentness_read_wait.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "runtime-timer-provider-unavailable",
            )
        })?;
        let stop = state.runtime_stop.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "runtime-stop-owner-unavailable",
            )
        })?;
        let clock = Arc::clone(&state.clock);
        let table = table(state)?;
        let timer = table
            .timers
            .iter()
            .find(|timer| timer.token() == token)
            .ok_or_else(|| failure(PlatformErrorCode::InvalidArgument, "runtime-timer-token"))?;
        let timer_wait = timer.begin_wait()?;
        #[cfg(feature = "development-go-timer-overlap")]
        let overlap = table.overlap.as_ref().and_then(|observer| {
            observer
                .next(token, table.runtime.snapshot().owners[3])
                .then(|| OverlapCompletion {
                    observer: observer.clone(),
                    token,
                    barrier_done: false,
                    returned: false,
                })
        });
        if let Some(observer) = &table.timer_observer {
            observer.record(TimerEvent::NextEntered, table.runtime.snapshot().owners);
        }
        let requested = timer_wait.requested();
        Ok(WaitingTimer {
            runtime: table.runtime.clone(),
            _owner: None,
            timer_wait: Some(timer_wait),
            #[cfg(feature = "development-go-timer-overlap")]
            overlap,
            // Existing timer-start/next observations remain byte-identical.
            wait_observer: None,
            wait_observed: false,
            wait,
            clock,
            stop,
            requested,
            call: call.take().expect("original accepted runtime call"),
        })
    })();
    if let Err(error) = &result {
        observe_runtime_refusal(state, error);
    }
    PreparedWait {
        result,
        failed_call: call,
    }
}
fn complete_elapsed_wait(
    runtime: &ActivationRuntime,
    timer: Option<&mut TimerWait>,
    now: Instant,
) -> Result<u64, PlatformError> {
    match timer {
        Some(timer) => timer.complete(now),
        None => {
            // Plain waits have no schedule commit. A final phase observation
            // orders their elapsed success against runtime cancellation.
            runtime.check_live()?;
            Ok(0)
        }
    }
}

impl WaitingTimer {
    async fn run(&mut self) -> Result<u64, PlatformError> {
        loop {
            // Cancellation/root deadline are observed before requested elapsed
            // success, including the boundary at which both become ready.
            if let Some(kind) = self.stop.observe() {
                self.runtime.cancel();
                return Err(failure(
                    if kind == GuestInterruptionKind::DeadlineExceeded {
                        PlatformErrorCode::DeadlineExceeded
                    } else {
                        PlatformErrorCode::Cancelled
                    },
                    "runtime-timer-stopped",
                ));
            }
            let now = self.clock.monotonic_now();
            if now >= self.call.deadline() {
                return Err(failure(
                    PlatformErrorCode::DeadlineExceeded,
                    "runtime-timer-deadline",
                ));
            }
            if let Err(error) = self.call.recheck_authority() {
                if latent_capabilities::broker::is_authority_bookkeeping_busy(&error) {
                    // Only an authority bookkeeping fence may be observed
                    // again. Keep the accepted call and original deadline;
                    // requested elapsed success still needs current authority.
                    self.wait
                        .wait_until_owned(
                            self.call.deadline().min(now + STOP_OBSERVATION),
                            self.call.budget_accounting(),
                        )?
                        .await;
                    continue;
                }
                if matches!(
                    error.code,
                    PlatformErrorCode::PermissionDenied
                        | PlatformErrorCode::AdmissionRejected
                        | PlatformErrorCode::Cancelled
                ) {
                    self.runtime.cancel();
                    self.stop.cancel_for_revocation();
                    return Err(failure(
                        PlatformErrorCode::Cancelled,
                        "runtime-timer-revoked",
                    ));
                }
                // A narrower broker deadline or unavailable authority is not
                // root cancellation. Preserve its structured failure.
                return Err(error);
            }
            if self.timer_wait.as_ref().is_some_and(TimerWait::is_closed) {
                #[cfg(feature = "development-go-timer-overlap")]
                if let Some(overlap) = &mut self.overlap {
                    if !overlap.barrier_done {
                        overlap.barrier_done = true;
                        overlap
                            .observer
                            .wait_for_second_park(
                                overlap.token,
                                self.wait.as_ref(),
                                self.call.budget_accounting(),
                                self.call.deadline(),
                                self.stop.as_ref(),
                            )
                            .await;
                        // Re-run the original stop, deadline and authority
                        // checks; the witness never supplies a timer result.
                        continue;
                    }
                }
                return Err(failure(
                    PlatformErrorCode::Cancelled,
                    "runtime-timer-closed",
                ));
            }
            self.runtime.check_live()?;
            let now = self.clock.monotonic_now();
            if now >= self.call.deadline() {
                return Err(failure(
                    PlatformErrorCode::DeadlineExceeded,
                    "runtime-timer-deadline",
                ));
            }
            if now >= self.requested {
                return complete_elapsed_wait(&self.runtime, self.timer_wait.as_mut(), now);
            }
            let next = self
                .requested
                .min(self.call.deadline())
                .min(now + STOP_OBSERVATION);
            let mut wait = self
                .wait
                .wait_until_owned(next, self.call.budget_accounting())?;
            std::future::poll_fn(|context| {
                positive_timer_observer::poll_pending(
                    std::pin::Pin::new(&mut wait),
                    context,
                    &mut self.wait_observed,
                    || {
                        if let Some(observer) = &self.wait_observer {
                            observer
                                .record(TimerEvent::WaitPending, self.runtime.snapshot().owners);
                        }
                        #[cfg(feature = "development-go-timer-overlap")]
                        if let Some(overlap) = &self.overlap {
                            overlap.observer.next_pending(overlap.token);
                        }
                    },
                )
            })
            .await;
        }
    }
}

pub(super) fn token(value: wit::Token) -> RuntimeToken {
    RuntimeToken {
        generation: value.generation,
        id: value.id,
    }
}
fn owner_kind(value: wit::OwnerKind) -> OwnerKind {
    match value {
        wit::OwnerKind::Task => OwnerKind::Task,
        wit::OwnerKind::ManagedIdleWorker => OwnerKind::ManagedIdleWorker,
        wit::OwnerKind::Executor => OwnerKind::Executor,
        wit::OwnerKind::QueuedWork => OwnerKind::QueuedWork,
        wit::OwnerKind::Wait => OwnerKind::Wait,
        wit::OwnerKind::Timer => OwnerKind::Timer,
        wit::OwnerKind::Result => OwnerKind::Result,
        wit::OwnerKind::Native => OwnerKind::Native,
    }
}
fn phase(value: RuntimePhase) -> wit::Phase {
    match value {
        RuntimePhase::Running => wit::Phase::Running,
        RuntimePhase::Waiting => wit::Phase::Waiting,
        RuntimePhase::Closing => wit::Phase::Closing,
        RuntimePhase::Draining => wit::Phase::Draining,
        RuntimePhase::Cancelling => wit::Phase::Cancelling,
        RuntimePhase::Retired => wit::Phase::Retired,
    }
}
pub(super) fn convert(value: PlatformError) -> wit::Error {
    let code = value.code;
    // Own and discard private diagnostics before exposing the frozen WIT enum.
    drop(value);
    match code {
        PlatformErrorCode::Unavailable => wit::Error::Unavailable,
        PlatformErrorCode::PermissionDenied | PlatformErrorCode::AdmissionRejected => {
            wit::Error::PermissionDenied
        }
        PlatformErrorCode::ResourceExhausted => wit::Error::ResourceExhausted,
        PlatformErrorCode::Cancelled => wit::Error::Cancelled,
        PlatformErrorCode::DeadlineExceeded => wit::Error::Deadline,
        PlatformErrorCode::InvalidArgument => wit::Error::InvalidToken,
        _ => wit::Error::InvalidState,
    }
}
fn failure(code: PlatformErrorCode, reason: &str) -> PlatformError {
    crate::containment::platform_error(code, reason, false)
}
