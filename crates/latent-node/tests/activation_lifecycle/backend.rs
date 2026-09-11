use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, Weak};
use std::task::{Context, Poll};
use std::time::Instant;

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    BoxFuture, BudgetConsumption, DeclaredError, Metadata, PlatformError, PlatformErrorCode,
    ReleaseDigest,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe, ExecutionReport,
    ExecutionRequest, GuestInterruptionKind, GuestOutcome, GuestTrap, PreparationKey,
    PreparedComponent, PreparedUse,
};

use super::support::{error, Gate, LiveGuard};

pub const SUCCESS: u8 = 0;
pub const DECLARED: u8 = 1;
pub const TRAP: u8 = 2;
pub const UNAVAILABLE: u8 = 3;
pub const PANIC: u8 = 4;
pub const QUARANTINE: u8 = 5;
pub const FUEL: u8 = 6;
pub const DROP_PANIC: u8 = 7;

pub struct Backend {
    pub gate: Gate,
    pub prepare_gate: Gate,
    pub mode: AtomicU8,
    pub entered: AtomicUsize,
    pub preparation_calls: AtomicUsize,
    pub preparation_fault: AtomicU8,
    pub live_calls: Arc<AtomicUsize>,
    pub live_prepared: Arc<AtomicUsize>,
    pub requests: Mutex<Vec<ExecutionRequest>>,
    pub deadlines: Mutex<Vec<Option<Instant>>>,
    pub probes: Mutex<Vec<Weak<dyn ExecutionCancellationProbe>>>,
}

impl Default for Backend {
    fn default() -> Self {
        Self {
            gate: Gate::new(true),
            prepare_gate: Gate::new(true),
            mode: AtomicU8::new(SUCCESS),
            entered: AtomicUsize::new(0),
            preparation_calls: AtomicUsize::new(0),
            preparation_fault: AtomicU8::new(0),
            live_calls: Arc::default(),
            live_prepared: Arc::default(),
            requests: Mutex::new(Vec::new()),
            deadlines: Mutex::new(Vec::new()),
            probes: Mutex::new(Vec::new()),
        }
    }
}

fn descriptor(key: PreparationKey) -> PreparedComponent {
    PreparedComponent {
        key,
        backend: "lifecycle-fixture".to_owned(),
        opaque_handle: "prepared-fixture".to_owned(),
        metadata: Metadata::new(),
    }
}

impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &'static str {
        "lifecycle-fixture"
    }

    fn preparation_key(&self, release: &ReleaseDigest) -> Result<PreparationKey, PlatformError> {
        Ok(PreparationKey {
            release: release.clone(),
            engine_version: "fixture-1".to_owned(),
            engine_configuration_digest: "fixture-config".to_owned(),
            target_triple: "fixture-target".to_owned(),
            cpu_feature_set: "fixture-cpu".to_owned(),
        })
    }

    fn prepare_for_use<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedUse, PlatformError>> {
        Box::pin(async move {
            assert_eq!(artifact.descriptor.release_digest, key.release);
            self.preparation_calls.fetch_add(1, Ordering::Relaxed);
            let pin = LiveGuard::new(&self.live_prepared);
            self.prepare_gate.wait().await;
            let mut prepared = descriptor(key.clone());
            match self.preparation_fault.load(Ordering::Acquire) {
                1 => prepared.key.release = ReleaseDigest("foreign-release".to_owned()),
                2 => prepared.backend = "foreign-backend".to_owned(),
                _ => {}
            }
            Ok(PreparedUse::new(prepared, pin))
        })
    }

    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        let future: BoxFuture<'a, ExecutionReport> = Box::pin(async move {
            assert_eq!(prepared.descriptor(), &request.prepared);
            let _prepared = prepared;
            let _live = LiveGuard::new(&self.live_calls);
            assert_eq!(
                cancellation.activation_id(),
                &request.activation.activation_id
            );
            let accounting = cancellation
                .budget_accounting()
                .expect("manager shares its ledger");
            assert_eq!(accounting.granted(), &request.budget);
            let probe = cancellation.probe().expect("live independent stop probe");
            self.probes.lock().unwrap().push(Arc::downgrade(&probe));
            self.deadlines
                .lock()
                .expect("deadlines")
                .push(accounting.deadline().monotonic());
            assert!(request.activation.resolved_revision.is_some());
            self.requests
                .lock()
                .expect("requests")
                .push(request.clone());
            self.entered.fetch_add(1, Ordering::Relaxed);
            accounting.consume_cpu_fuel(3).expect("small fuel");
            accounting.consume_log_bytes(4).expect("host log");
            accounting.observe_peak_memory(8).expect("small memory");
            self.gate.wait().await;
            let consumed = accounting.snapshot_at(Instant::now());
            match self.mode.load(Ordering::Acquire) {
                PANIC => panic!("controlled backend panic"),
                QUARANTINE => ExecutionReport::quarantine(
                    Err(error(PlatformErrorCode::Internal, "uncertain cleanup")),
                    "fixture quarantine",
                ),
                mode => ExecutionReport::reusable(outcome(mode, request, consumed)),
            }
        });
        if self.mode.load(Ordering::Acquire) == DROP_PANIC {
            Box::pin(PanicOnDrop { inner: future })
        } else {
            future
        }
    }

    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async { panic!("manager must use affine preparation") })
    }

    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async { panic!("manager must use contained owned invocation") })
    }

    fn release(&self, _prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async {
            panic!("shared preparation must not be globally evicted after each activation")
        })
    }
}

struct PanicOnDrop<'a> {
    inner: BoxFuture<'a, ExecutionReport>,
}

impl Future for PanicOnDrop<'_> {
    type Output = ExecutionReport;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        self.get_mut().inner.as_mut().poll(context)
    }
}

impl Drop for PanicOnDrop<'_> {
    fn drop(&mut self) {
        // Exercise normal destruction, while avoiding a process-aborting second
        // panic if an independent fixture assertion already started unwinding.
        assert!(
            std::thread::panicking(),
            "controlled backend future destructor panic"
        );
    }
}

fn outcome(
    mode: u8,
    request: ExecutionRequest,
    consumption: BudgetConsumption,
) -> Result<GuestOutcome, PlatformError> {
    match mode {
        DECLARED => Ok(GuestOutcome::DeclaredError {
            error: DeclaredError {
                code: "guest.invalid-input".to_owned(),
                message: "declared fixture error".to_owned(),
                payload: b"domain payload".to_vec(),
                media_type: "application/octet-stream".to_owned(),
                metadata: Metadata::new(),
            },
            consumption,
        }),
        TRAP => Ok(GuestOutcome::Trapped {
            trap: GuestTrap {
                code: "fixture-trap".to_owned(),
                message: "controlled trap".to_owned(),
                guest_backtrace: Vec::new(),
                metadata: Metadata::new(),
            },
            consumption,
        }),
        FUEL => Ok(GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::FuelExhausted,
            reason: "controlled fuel exhaustion".to_owned(),
            consumption,
        }),
        UNAVAILABLE => Err(error(
            PlatformErrorCode::Unavailable,
            "controlled unavailable",
        )),
        _ => Ok(GuestOutcome::Returned {
            output: request.activation.input,
            output_media_type: request.activation.input_media_type,
            consumption,
        }),
    }
}
