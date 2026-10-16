//! Exact child-native retirement; no Store borrow spans the host wait.
use super::{runtime, HostState};
use latent_capabilities::broker::{AuditProviderOutcome, ProviderCall};
use latent_component_bindings::host::activation::latent::runtime::activation as wit;
use latent_core::{activation_runtime::ActivationRuntime, PlatformError, PlatformErrorCode};
use latent_executor::{GuestInterruptionKind, PreparationReadWait};
use latent_policy::capability::ResourceTarget;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use wasmtime::{component::Linker, AsContextMut};

pub(crate) const CAPABILITY: &str = "latent:runtime-native/threads@0.1.0";
pub(crate) const PROFILE: &str = "original-native-retirement-v1";
pub(crate) const OPERATIONS: [&str; 3] = ["start", "join", "reap"];

fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    crate::containment::platform_error(code, reason, false)
}

fn authorize(state: &HostState, operation: &str) -> Result<ProviderCall, PlatformError> {
    runtime::authorize_for(state, CAPABILITY, operation, ResourceTarget::Context)
}

pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    let [start, join, reap] = OPERATIONS;
    linker.instance(CAPABILITY)?.func_wrap_async(
        start,
        move |mut store, (value,): (wit::Token,)| {
            Box::new(async move {
                let started = Instant::now();
                super::service::checkpoint(&mut store)?;
                let mut call = match authorize(store.data(), "start") {
                    Ok(call) => call,
                    Err(error) => {
                        super::service::synchronize(&mut store)?;
                        store.data_mut().record_host_call(started);
                        return Ok((runtime::Completion::new(Err(runtime::convert(error)), None),));
                    }
                };
                let result = runtime::native_context(store.data_mut()).and_then(|(context, _)| {
                    context.reserve_child(runtime::token(value)).map(|child| {
                        let token = child.token();
                        wit::Token {
                            generation: token.generation,
                            id: token.id,
                        }
                    })
                });
                let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
                super::service::synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((runtime::Completion::new(
                    result.map_err(runtime::convert),
                    Some(call),
                ),))
            })
        },
    )?;
    linker
        .instance(CAPABILITY)?
        .func_wrap_async(reap, |mut store, (value,): (wit::Token,)| {
            Box::new(async move {
                let started = Instant::now();
                super::service::checkpoint(&mut store)?;
                let mut call = match authorize(store.data(), "reap") {
                    Ok(call) => call,
                    Err(error) => {
                        super::service::synchronize(&mut store)?;
                        store.data_mut().record_host_call(started);
                        return Ok((runtime::Completion::new(Err(runtime::convert(error)), None),));
                    }
                };
                let result = runtime::native_context(store.data_mut())
                    .and_then(|(context, _)| context.reap_child(runtime::token(value)));
                let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
                super::service::synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((runtime::Completion::new(
                    result.map_err(runtime::convert),
                    Some(call),
                ),))
            })
        })?;
    linker.instance(CAPABILITY)?.func_wrap_concurrent(
        join,
        |access, (native, continuation): (wit::Token, wit::Token)| {
            Box::pin(async move {
                let started = Instant::now();
                let PreparedNative {
                    result,
                    failed_call,
                } = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    super::service::checkpoint(&mut store)?;
                    let prepared = prepare_join(store.data_mut(), native, continuation);
                    super::service::synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(prepared)
                })?;
                let (result, mut call) = match result {
                    Ok(mut wait) => (wait.run().await, Some(wait.call)),
                    Err(error) => (Err(error), failed_call),
                };
                if let Some(call) = call.as_mut() {
                    let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
                }
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    super::service::checkpoint(&mut store)?;
                    super::service::synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((runtime::Completion::new(
                        result.map_err(runtime::convert),
                        call,
                    ),))
                })
            })
        },
    )?;
    Ok(())
}

struct PreparedNative {
    result: Result<WaitingNative, PlatformError>,
    failed_call: Option<ProviderCall>,
}

fn prepare_join(
    state: &mut HostState,
    native: wit::Token,
    continuation: wit::Token,
) -> PreparedNative {
    let mut call = match authorize(state, "join") {
        Ok(call) => Some(call),
        Err(error) => {
            return PreparedNative {
                result: Err(error),
                failed_call: None,
            }
        }
    };
    let result = (|| {
        let clock = Arc::clone(&state.clock);
        let wait = state.currentness_read_wait.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "native-join-wait-provider-unavailable",
            )
        })?;
        let stop = state.runtime_stop.clone().ok_or_else(|| {
            failure(
                PlatformErrorCode::Unavailable,
                "native-join-stop-owner-unavailable",
            )
        })?;
        let (context, runtime) = runtime::native_context(state)?;
        let child = context.child(runtime::token(native))?;
        child.prepare_wait(runtime::token(continuation))?;
        Ok(WaitingNative {
            child,
            runtime,
            clock,
            wait,
            stop,
            call: call.take().expect("original accepted native call"),
        })
    })();
    PreparedNative {
        result,
        failed_call: call,
    }
}

struct WaitingNative {
    child: Arc<crate::native_stacks::Child>,
    runtime: ActivationRuntime,
    clock: Arc<dyn latent_core::ActivationClock>,
    wait: Arc<dyn PreparationReadWait>,
    stop: Arc<crate::containment::StopControl>,
    call: ProviderCall,
}

impl WaitingNative {
    async fn run(&mut self) -> Result<(), PlatformError> {
        loop {
            if let Some(kind) = self.stop.observe() {
                self.runtime.cancel();
                return Err(failure(
                    if kind == GuestInterruptionKind::DeadlineExceeded {
                        PlatformErrorCode::DeadlineExceeded
                    } else {
                        PlatformErrorCode::Cancelled
                    },
                    "native-join-root-stopped",
                ));
            }
            let now = self.clock.monotonic_now();
            if now >= self.call.deadline() {
                return Err(failure(
                    PlatformErrorCode::DeadlineExceeded,
                    "native-join-deadline",
                ));
            }
            if let Err(error) = self.call.recheck_authority() {
                if latent_capabilities::broker::is_authority_bookkeeping_busy(&error) {
                    self.wait
                        .wait_until(self.call.deadline().min(now + Duration::from_millis(10)))
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
                    return Err(failure(PlatformErrorCode::Cancelled, "native-join-revoked"));
                }
                return Err(error);
            }
            self.runtime.check_live()?;
            let now = self.clock.monotonic_now();
            if now >= self.call.deadline() {
                return Err(failure(
                    PlatformErrorCode::DeadlineExceeded,
                    "native-join-deadline",
                ));
            }
            if self.child.retirement_failed() {
                return Err(failure(
                    PlatformErrorCode::Internal,
                    "native-join-retirement-unproven",
                ));
            }
            if self.child.physically_retired() {
                return Ok(());
            }
            tokio::select! {
                () = self.child.changed() => {},
                () = self.wait.wait_until(self.call.deadline().min(now + Duration::from_millis(10))) => {},
            }
        }
    }
}
