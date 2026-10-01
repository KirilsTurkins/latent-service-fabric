//! Versioned activation-owned runtime bridge. Logical scheduling remains in
//! each maintained language runtime. Store access is bounded and never spans
//! the executor-neutral timer await; no thread sleeps for a guest timer.
use super::HostState;
use latent_capabilities::broker::{AuditProviderOutcome, ProviderCall};
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
use wasmtime::{component::Linker, AsContextMut};

mod fixed_result;
use fixed_result::{Completion, FixedValue};

pub(crate) const CAPABILITY: &str = "latent:runtime/activation@0.1.0";
const STOP_OBSERVATION: Duration = Duration::from_millis(10);

/// Guards are held with actual Store-owned logical work. Tokens alone cannot
/// remove an owner, mint another activation, or establish native retirement.
pub(crate) struct Table {
    owners: Vec<RuntimeOwner>,
    timers: Vec<RuntimeTimer>,
    runtime: ActivationRuntime,
    _allocation: HostMemoryReservation,
}
impl Table {
    fn new(
        budget: latent_core::ActivationBudget,
        limits: RuntimeLimits,
    ) -> Result<Self, PlatformError> {
        let bytes = limits.total() as u64 * std::mem::size_of::<RuntimeOwner>() as u64
            + u64::from(limits.timers) * std::mem::size_of::<RuntimeTimer>() as u64
            + std::mem::size_of::<Self>() as u64
            + 64;
        let mut allocation = budget
            .reserve_host_memory(bytes)
            .map_err(|e| e.to_platform_error())?;
        let mut owners = Vec::new();
        owners.try_reserve_exact(limits.total()).map_err(|_| {
            failure(
                PlatformErrorCode::ResourceExhausted,
                "runtime-owner-allocation",
            )
        })?;
        let mut timers = Vec::new();
        timers
            .try_reserve_exact(limits.timers as usize)
            .map_err(|_| {
                failure(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-timer-allocation",
                )
            })?;
        let runtime = ActivationRuntime::new(budget, limits)?;
        allocation.confirm();
        Ok(Self {
            owners,
            timers,
            runtime,
            _allocation: allocation,
        })
    }
    pub(crate) fn finalize(&mut self) -> Result<(), PlatformError> {
        self.runtime.begin_drain();
        self.runtime.retire()
    }
}
impl Drop for Table {
    fn drop(&mut self) {
        self.runtime.cancel();
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
        state.runtime = Some(Table::new(state.accounting.budget().clone(), limits)?);
    }
    let table = state.runtime.as_mut().expect("initialized table");
    table.runtime.check_live()?;
    Ok(table)
}
fn authorize(state: &HostState, operation: &str) -> Result<ProviderCall, PlatformError> {
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
    state
        .capabilities
        .begin(CAPABILITY, operation, ResourceTarget::Clock, &[], 128)?
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
        Err(error) => return Completion::new(Err(convert(error)), None),
    };
    let result = table(state).and_then(execute);
    let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
    state.record_host_call(started);
    Completion::new(result.map_err(convert), Some(call))
}

#[expect(
    clippy::too_many_lines,
    reason = "register the eleven authoritative operations together, with explicit sync and async ABI shapes"
)]
pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    macro_rules! sync {
        ($name:literal, $args:pat, $ty:ty, $execute:expr) => {
            linker
                .instance(CAPABILITY)?
                .func_wrap_async($name, |mut store, $args: $ty| {
                    Box::new(async move {
                        super::service::checkpoint(&mut store)?;
                        let result = synchronous(store.data_mut(), $name, $execute);
                        super::service::synchronize(&mut store)?;
                        Ok((result,))
                    })
                })?;
        };
    }
    sync!(
        "register",
        (kind, continuation),
        (wit::OwnerKind, Option<wit::Token>),
        |table| {
            let owner = table
                .runtime
                .register(owner_kind(kind), continuation.map(token))?;
            let value = owner.token();
            table.owners.push(owner);
            Ok(wit::Token {
                generation: value.generation,
                id: value.id,
            })
        }
    );
    sync!("park", (owner,), (wit::Token,), |table| {
        table.runtime.park(token(owner))?;
        Ok(())
    });
    sync!("wake", (owner,), (wit::Token,), |table| {
        if table.runtime.wake(token(owner)) {
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
    linker.instance(CAPABILITY)?.func_wrap_async(
        "timer-start",
        |mut store, (delay, period, continuation): (u64, Option<u64>, Option<wit::Token>)| {
            Box::new(async move {
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
                    let timer = RuntimeTimer::new(
                        &table.runtime,
                        first,
                        period.map(Duration::from_nanos),
                        continuation.map(token),
                    )?;
                    let value = timer.token();
                    table.timers.push(timer);
                    Ok(wit::Token {
                        generation: value.generation,
                        id: value.id,
                    })
                });
                super::service::synchronize(&mut store)?;
                Ok((result,))
            })
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
        drop(timer);
        Ok(())
    });
    linker.instance(CAPABILITY)?.func_wrap_concurrent(
        "timer-next",
        |access, (timer,): (wit::Token,)| {
            Box::pin(async move {
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
            })
        },
    )?;
    for operation in ["wait-for", "wait-until"] {
        linker.instance(CAPABILITY)?.func_wrap_concurrent(
            operation,
            move |access, (value, continuation): (u64, Option<wit::Token>)| {
                Box::pin(async move {
                    let started = Instant::now();
                    let PreparedWait {
                        result: prepared,
                        failed_call,
                    } = access.with(|mut access| {
                        let mut store = access.as_context_mut();
                        super::service::checkpoint(&mut store)?;
                        let prepared = prepare_wait(
                            store.data_mut(),
                            operation,
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
                })
            },
        )?;
    }
    Ok(())
}

struct WaitingTimer {
    runtime: ActivationRuntime,
    _owner: Option<RuntimeOwner>,
    timer_wait: Option<TimerWait>,
    wait: Arc<dyn PreparationReadWait>,
    clock: Arc<dyn latent_core::ActivationClock>,
    stop: Arc<crate::containment::StopControl>,
    requested: Instant,
    call: ProviderCall,
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
            }
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
        let runtime = table(state)?.runtime.clone();
        let owner = runtime.register(OwnerKind::Timer, continuation)?;
        Ok(WaitingTimer {
            runtime,
            _owner: Some(owner),
            timer_wait: None,
            wait,
            clock,
            stop,
            requested,
            call: call.take().expect("original accepted runtime call"),
        })
    })();
    // A failed timer preparation has no pending producer, but its accepted
    // call still owns the fixed error result through actual canonical lowering.
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
            }
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
        let requested = timer_wait.requested();
        Ok(WaitingTimer {
            runtime: table.runtime.clone(),
            _owner: None,
            timer_wait: Some(timer_wait),
            wait,
            clock,
            stop,
            requested,
            call: call.take().expect("original accepted runtime call"),
        })
    })();
    PreparedWait {
        result,
        failed_call: call,
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
                        .wait_until(self.call.deadline().min(now + STOP_OBSERVATION))
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
                return self
                    .timer_wait
                    .as_mut()
                    .map_or(Ok(0), |timer| timer.complete(now));
            }
            let next = self
                .requested
                .min(self.call.deadline())
                .min(now + STOP_OBSERVATION);
            self.wait.wait_until(next).await;
        }
    }
}

fn token(value: wit::Token) -> RuntimeToken {
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
fn convert(value: PlatformError) -> wit::Error {
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
