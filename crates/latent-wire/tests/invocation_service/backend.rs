use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    BoxFuture, DeclaredError, ErrorDetail, Metadata, PlatformError, PlatformErrorCode,
    ReleaseDigest,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedComponent, PreparedUse,
};

use super::support::{error, Gate, LiveGuard};

pub const RETURNED: u8 = 0;
pub const DECLARED: u8 = 1;
pub const FAILURE: u8 = 2;
pub const SECRET: &str = "postgres://operator:password@private.example/database";

pub struct Backend {
    pub gate: Gate,
    pub mode: AtomicU8,
    pub entered: AtomicUsize,
    pub live_calls: Arc<AtomicUsize>,
    pub live_prepared: Arc<AtomicUsize>,
    pub requests: Mutex<Vec<ExecutionRequest>>,
}

impl Default for Backend {
    fn default() -> Self {
        Self {
            gate: Gate::new(true),
            mode: AtomicU8::new(RETURNED),
            entered: AtomicUsize::new(0),
            live_calls: Arc::default(),
            live_prepared: Arc::default(),
            requests: Mutex::new(Vec::new()),
        }
    }
}

impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &'static str {
        "rpc-fixture"
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
            Ok(PreparedUse::new(
                PreparedComponent {
                    key: key.clone(),
                    backend: "rpc-fixture".to_owned(),
                    opaque_handle: "prepared-fixture".to_owned(),
                    metadata: Metadata::new(),
                },
                LiveGuard::new(&self.live_prepared),
            ))
        })
    }

    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            assert_eq!(prepared.descriptor(), &request.prepared);
            let _prepared = prepared;
            let _live = LiveGuard::new(&self.live_calls);
            let accounting = cancellation.budget_accounting().expect("manager ledger");
            assert_eq!(
                cancellation.activation_id(),
                &request.activation.activation_id
            );
            assert_eq!(accounting.granted(), &request.budget);
            self.requests
                .lock()
                .expect("requests")
                .push(request.clone());
            self.entered.fetch_add(1, Ordering::Relaxed);
            accounting.consume_cpu_fuel(3).expect("fuel");
            accounting.consume_log_bytes(4).expect("logs");
            accounting.observe_peak_memory(8).expect("memory");
            self.gate.wait().await;
            let consumption = accounting.snapshot_at(Instant::now());
            let outcome = match self.mode.load(Ordering::Acquire) {
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
                FAILURE => {
                    let mut failure = error(PlatformErrorCode::Unavailable, SECRET);
                    failure.retryable = true;
                    failure.details.push(ErrorDetail {
                        kind: "private-diagnostic".to_owned(),
                        fields: Metadata::from([("connection".to_owned(), SECRET.to_owned())]),
                    });
                    Err(failure)
                }
                _ => Ok(GuestOutcome::Returned {
                    output: request.activation.input,
                    output_media_type: request.activation.input_media_type,
                    consumption,
                }),
            };
            ExecutionReport::reusable(outcome)
        })
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
        Box::pin(async { panic!("owned preparation drops without global eviction") })
    }
}
