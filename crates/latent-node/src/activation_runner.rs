use std::collections::HashMap;
use std::future::pending;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use latent_activation::{
    ActivationEnvelope, ActivationManager, ActivationOutcome, ActivationSuccess,
};
use latent_core::{
    ActivationId, ActivationTerminalState, BoxFuture, BudgetConsumption, ErrorDetail, Metadata,
    PlatformError, PlatformErrorCode,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe,
    ExecutionCell, ExecutionCleanup, ExecutionReport, ExecutionRequest, GuestInterruptionKind,
    GuestOutcome, PreparedComponent,
};
use latent_scheduler::{CellClass, CellLease, CellPool};
use tokio::sync::watch;

const MAX_DIAGNOSTIC_BYTES: usize = 512;
const MAX_ERROR_DETAILS: usize = 8;
const MAX_DETAIL_FIELDS: usize = 16;
const MAX_DETAIL_NAME_BYTES: usize = 64;
const MAX_DETAIL_VALUE_BYTES: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase0ActivationRunnerConfig {
    pub cell_class: CellClass,
    pub maximum_cancellation_reason_bytes: usize,
    pub maximum_quarantine_reason_bytes: usize,
}

impl Default for Phase0ActivationRunnerConfig {
    fn default() -> Self {
        Self {
            cell_class: CellClass::Standard,
            maximum_cancellation_reason_bytes: 256,
            maximum_quarantine_reason_bytes: 256,
        }
    }
}

impl Phase0ActivationRunnerConfig {
    fn validate(&self) -> Result<(), PlatformError> {
        if self.maximum_cancellation_reason_bytes == 0
            || self.maximum_quarantine_reason_bytes == 0
        {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "activation runner diagnostic limits must be non-zero",
                false,
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ActivationRunnerSnapshot {
    pub active_cancellation_registrations: u64,
    pub running_invocations: u64,
    pub total_invocations: u64,
    pub released_cells: u64,
    pub quarantined_cells: u64,
    pub disposition_failures: u64,
}

#[derive(Debug, Default)]
struct RunnerCounters {
    running_invocations: AtomicU64,
    total_invocations: AtomicU64,
    released_cells: AtomicU64,
    quarantined_cells: AtomicU64,
    disposition_failures: AtomicU64,
}

/// Minimal Phase 0 orchestrator joining one affine cell lease to one contained
/// backend invocation.
pub struct Phase0ActivationRunner {
    config: Phase0ActivationRunnerConfig,
    pool: Arc<dyn CellPool>,
    backend: Arc<dyn ExecutionBackend>,
    prepared: PreparedComponent,
    imports: Vec<BoundImport>,
    registrations: Arc<Mutex<HashMap<ActivationId, Arc<CancellationState>>>>,
    counters: RunnerCounters,
}

impl Phase0ActivationRunner {
    pub fn new(
        config: Phase0ActivationRunnerConfig,
        pool: Arc<dyn CellPool>,
        backend: Arc<dyn ExecutionBackend>,
        prepared: PreparedComponent,
        imports: Vec<BoundImport>,
    ) -> Result<Self, PlatformError> {
        config.validate()?;
        if prepared.backend != backend.backend_id() {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "prepared component belongs to a different execution backend",
                false,
            ));
        }
        if imports
            .iter()
            .any(|import| import.opaque_handle.is_empty() || import.contract.is_empty())
        {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "activation runner imports must have contracts and opaque handles",
                false,
            ));
        }

        Ok(Self {
            config,
            pool,
            backend,
            prepared,
            imports,
            registrations: Arc::new(Mutex::new(HashMap::new())),
            counters: RunnerCounters::default(),
        })
    }

    /// Constant-time resource observations used by containment and leak tests.
    pub fn snapshot(&self) -> ActivationRunnerSnapshot {
        let registrations = self.lock_registrations().len();
        ActivationRunnerSnapshot {
            active_cancellation_registrations: u64::try_from(registrations).unwrap_or(u64::MAX),
            running_invocations: self.counters.running_invocations.load(Ordering::Relaxed),
            total_invocations: self.counters.total_invocations.load(Ordering::Relaxed),
            released_cells: self.counters.released_cells.load(Ordering::Relaxed),
            quarantined_cells: self.counters.quarantined_cells.load(Ordering::Relaxed),
            disposition_failures: self.counters.disposition_failures.load(Ordering::Relaxed),
        }
    }

    async fn invoke_registered(
        &self,
        mut envelope: ActivationEnvelope,
        cancellation: CancellationToken,
    ) -> ActivationOutcome {
        let activation_id = envelope.activation_id.clone();
        let effective_deadline = earliest_deadline(
            envelope.deadline_unix_millis,
            envelope.budget.wall_deadline_unix_millis,
        );
        envelope.deadline_unix_millis = effective_deadline;
        envelope.budget.wall_deadline_unix_millis = effective_deadline;

        if cancellation.is_cancelled() {
            return cancellation_failure(cancellation.reason());
        }
        if deadline_expired(effective_deadline) {
            return deadline_failure("activation deadline expired before cell acquisition");
        }

        let Some(tenant) = envelope.principal.tenant.clone() else {
            return failure(
                platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "activation principal must carry a tenant for cell acquisition",
                    false,
                ),
                BudgetConsumption::default(),
            );
        };
        let budget = envelope.budget.clone();

        // The inner scope guarantees that a losing acquisition future is dropped
        // before cancel_waiting is invoked or the envelope proceeds to execution.
        let resolution = {
            let acquire = self.pool.acquire(
                &activation_id,
                &tenant,
                self.config.cell_class,
                &budget,
            );
            tokio::pin!(acquire);
            let deadline_wait = wait_for_deadline(effective_deadline);
            tokio::pin!(deadline_wait);

            tokio::select! {
                biased;
                () = cancellation.cancelled() => LeaseResolution::Cancelled,
                () = &mut deadline_wait => LeaseResolution::DeadlineExceeded,
                result = &mut acquire => LeaseResolution::Acquired(result),
            }
        };

        let lease = match resolution {
            LeaseResolution::Cancelled => {
                let _ = self.pool.cancel_waiting(&activation_id).await;
                return cancellation_failure(cancellation.reason());
            }
            LeaseResolution::DeadlineExceeded => {
                let _ = self.pool.cancel_waiting(&activation_id).await;
                return deadline_failure("activation deadline expired while queued");
            }
            LeaseResolution::Acquired(Ok(lease)) => lease,
            LeaseResolution::Acquired(Err(error)) => {
                return failure(sanitize_error(error), BudgetConsumption::default());
            }
        };

        if cancellation.is_cancelled() {
            return self
                .release_before_execution(lease, cancellation_failure(cancellation.reason()))
                .await;
        }
        if deadline_expired(effective_deadline) {
            return self
                .release_before_execution(
                    lease,
                    deadline_failure("activation deadline expired before guest execution"),
                )
                .await;
        }

        self.execute_with_lease(envelope, lease, cancellation).await
    }

    async fn release_before_execution(
        &self,
        lease: CellLease,
        intended_outcome: ActivationOutcome,
    ) -> ActivationOutcome {
        match self.pool.release(lease).await {
            Ok(()) => {
                self.counters.released_cells.fetch_add(1, Ordering::Relaxed);
                intended_outcome
            }
            Err(error) => {
                self.counters
                    .disposition_failures
                    .fetch_add(1, Ordering::Relaxed);
                failure(sanitize_error(error), outcome_consumption(&intended_outcome))
            }
        }
    }

    async fn execute_with_lease(
        &self,
        envelope: ActivationEnvelope,
        lease: CellLease,
        cancellation: CancellationToken,
    ) -> ActivationOutcome {
        let cell_id = lease.id.clone();
        let mut cell_metadata = Metadata::new();
        cell_metadata.insert("node-id".to_owned(), lease.node.0.clone());
        cell_metadata.insert(
            "lease-expires-at-unix-millis".to_owned(),
            lease.expires_at_unix_millis.to_string(),
        );
        let cell = ExecutionCell {
            id: cell_id.clone(),
            class: cell_class_name(lease.class).to_owned(),
            maximum_memory_bytes: lease.granted_budget.memory_bytes,
            metadata: cell_metadata,
        };
        let request = ExecutionRequest {
            budget: envelope.budget.clone(),
            activation: envelope,
            prepared: self.prepared.clone(),
            cell,
            imports: self.imports.clone(),
        };

        let running_guard = AtomicCounterGuard::new(&self.counters.running_invocations);
        let report = self
            .backend
            .invoke_contained(request, &cancellation)
            .await;
        drop(running_guard);

        let ExecutionReport { outcome, cleanup } = report;
        let disposition_name = match &cleanup {
            ExecutionCleanup::Reusable => "released",
            ExecutionCleanup::Quarantine { .. } => "quarantined",
        };
        let mapped = map_execution_outcome(outcome, &cell_id.0, disposition_name);
        let consumption = outcome_consumption(&mapped);

        let disposition = match cleanup {
            ExecutionCleanup::Reusable => {
                let result = self.pool.release(lease).await;
                if result.is_ok() {
                    self.counters.released_cells.fetch_add(1, Ordering::Relaxed);
                }
                result
            }
            ExecutionCleanup::Quarantine { reason } => {
                let reason = bounded_text(
                    if reason.is_empty() {
                        "execution backend could not prove safe cell reuse"
                    } else {
                        &reason
                    },
                    self.config.maximum_quarantine_reason_bytes,
                );
                let result = self.pool.quarantine(lease, reason).await;
                if result.is_ok() {
                    self.counters
                        .quarantined_cells
                        .fetch_add(1, Ordering::Relaxed);
                }
                result
            }
        };

        match disposition {
            Ok(()) => mapped,
            Err(error) => {
                self.counters
                    .disposition_failures
                    .fetch_add(1, Ordering::Relaxed);
                failure(sanitize_error(error), consumption)
            }
        }
    }

    fn register(
        &self,
        activation_id: ActivationId,
    ) -> Result<(CancellationToken, RegistrationGuard), PlatformError> {
        let mut registrations = self.lock_registrations();
        if registrations.contains_key(&activation_id) {
            return Err(platform_error(
                PlatformErrorCode::AlreadyExists,
                "activation already has a live cancellation registration",
                false,
            ));
        }

        let state = Arc::new(CancellationState::new(activation_id.clone()));
        registrations.insert(activation_id.clone(), Arc::clone(&state));
        drop(registrations);
        let token = CancellationToken {
            state: Arc::clone(&state),
        };
        let guard = RegistrationGuard {
            registrations: Arc::clone(&self.registrations),
            activation_id,
            state,
        };
        Ok((token, guard))
    }

    fn lock_registrations(
        &self,
    ) -> MutexGuard<'_, HashMap<ActivationId, Arc<CancellationState>>> {
        self.registrations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ActivationManager for Phase0ActivationRunner {
    fn invoke<'a>(
        &'a self,
        envelope: ActivationEnvelope,
    ) -> BoxFuture<'a, ActivationOutcome> {
        Box::pin(async move {
            self.counters.total_invocations.fetch_add(1, Ordering::Relaxed);
            let activation_id = envelope.activation_id.clone();
            let (cancellation, registration) = match self.register(activation_id) {
                Ok(registration) => registration,
                Err(error) => return failure(error, BudgetConsumption::default()),
            };
            let outcome = self.invoke_registered(envelope, cancellation).await;
            drop(registration);
            outcome
        })
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let state = self
                .lock_registrations()
                .get(activation_id)
                .cloned()
                .ok_or_else(|| {
                    platform_error(
                        PlatformErrorCode::NotFound,
                        "activation has no live cancellation registration",
                        false,
                    )
                })?;
            state.cancel(bounded_text(
                if reason.is_empty() { "cancelled" } else { reason },
                self.config.maximum_cancellation_reason_bytes,
            ));

            // Cancellation is owned by the runner token. Pool cancellation is a
            // best-effort queue acceleration and cannot revoke an accepted signal.
            let _ = self.pool.cancel_waiting(activation_id).await;
            Ok(())
        })
    }
}

enum LeaseResolution {
    Acquired(Result<CellLease, PlatformError>),
    Cancelled,
    DeadlineExceeded,
}

struct CancellationState {
    activation_id: ActivationId,
    cancelled: AtomicBool,
    reason: Mutex<Option<String>>,
    signal: watch::Sender<bool>,
}

impl CancellationState {
    fn new(activation_id: ActivationId) -> Self {
        let (signal, _) = watch::channel(false);
        Self {
            activation_id,
            cancelled: AtomicBool::new(false),
            reason: Mutex::new(None),
            signal,
        }
    }

    fn cancel(&self, reason: String) {
        let mut current_reason = self
            .reason
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.cancelled.load(Ordering::Acquire) {
            return;
        }
        *current_reason = Some(reason);
        self.cancelled.store(true, Ordering::Release);
        self.signal.send_replace(true);
    }

    fn cancelled_flag(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    fn current_reason(&self) -> Option<String> {
        self.reason
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    async fn notified(&self) {
        let mut receiver = self.signal.subscribe();
        if *receiver.borrow() {
            return;
        }
        while receiver.changed().await.is_ok() {
            if *receiver.borrow() {
                return;
            }
        }
    }
}

impl ExecutionCancellationProbe for CancellationState {
    fn is_cancelled(&self) -> bool {
        self.cancelled_flag()
    }

    fn reason(&self) -> Option<String> {
        self.current_reason()
    }
}

#[derive(Clone)]
struct CancellationToken {
    state: Arc<CancellationState>,
}

impl CancellationToken {
    fn is_cancelled(&self) -> bool {
        self.state.cancelled_flag()
    }

    fn reason(&self) -> Option<String> {
        self.state.current_reason()
    }

    async fn cancelled(&self) {
        self.state.notified().await;
    }
}

impl ExecutionCancellation for CancellationToken {
    fn activation_id(&self) -> &ActivationId {
        &self.state.activation_id
    }

    fn is_cancelled(&self) -> bool {
        self.is_cancelled()
    }

    fn reason(&self) -> Option<String> {
        self.reason()
    }

    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(self.state.clone())
    }
}

struct RegistrationGuard {
    registrations: Arc<Mutex<HashMap<ActivationId, Arc<CancellationState>>>>,
    activation_id: ActivationId,
    state: Arc<CancellationState>,
}

impl Drop for RegistrationGuard {
    fn drop(&mut self) {
        let mut registrations = self
            .registrations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if registrations
            .get(&self.activation_id)
            .is_some_and(|current| Arc::ptr_eq(current, &self.state))
        {
            registrations.remove(&self.activation_id);
        }
    }
}

struct AtomicCounterGuard<'a> {
    counter: &'a AtomicU64,
}

impl<'a> AtomicCounterGuard<'a> {
    fn new(counter: &'a AtomicU64) -> Self {
        counter.fetch_add(1, Ordering::Relaxed);
        Self { counter }
    }
}

impl Drop for AtomicCounterGuard<'_> {
    fn drop(&mut self) {
        let previous = self.counter.fetch_sub(1, Ordering::Relaxed);
        debug_assert!(previous > 0, "activation runner counter underflow");
    }
}

fn map_execution_outcome(
    outcome: Result<GuestOutcome, PlatformError>,
    cell_id: &str,
    disposition: &str,
) -> ActivationOutcome {
    match outcome {
        Ok(GuestOutcome::Returned {
            output,
            output_media_type,
            consumption,
        }) => {
            let mut metadata = Metadata::new();
            metadata.insert("cell-id".to_owned(), cell_id.to_owned());
            metadata.insert("cell-disposition".to_owned(), disposition.to_owned());
            ActivationOutcome::Succeeded(ActivationSuccess {
                output,
                output_media_type,
                consumption,
                committed_state_version: None,
                effect_ids: Vec::new(),
                metadata,
            })
        }
        Ok(GuestOutcome::Trapped { trap, consumption }) => {
            let mut fields = Metadata::new();
            fields.insert(
                "code".to_owned(),
                bounded_text(&trap.code, MAX_DETAIL_VALUE_BYTES),
            );
            fields.insert("cell_id".to_owned(), cell_id.to_owned());
            failure(
                PlatformError {
                    code: PlatformErrorCode::GuestTrap,
                    message: bounded_text(&trap.message, MAX_DIAGNOSTIC_BYTES),
                    retryable: false,
                    details: vec![ErrorDetail {
                        kind: "activation.guest-trap".to_owned(),
                        fields,
                    }],
                },
                consumption,
            )
        }
        Ok(GuestOutcome::Interrupted {
            kind,
            reason,
            consumption,
        }) => {
            let (code, detail_kind) = match kind {
                GuestInterruptionKind::Cancelled => {
                    (PlatformErrorCode::Cancelled, "activation.cancelled")
                }
                GuestInterruptionKind::DeadlineExceeded => (
                    PlatformErrorCode::DeadlineExceeded,
                    "activation.deadline-exceeded",
                ),
                GuestInterruptionKind::FuelExhausted => (
                    PlatformErrorCode::ResourceExhausted,
                    "activation.fuel-exhausted",
                ),
                GuestInterruptionKind::MemoryExhausted => (
                    PlatformErrorCode::ResourceExhausted,
                    "activation.memory-exhausted",
                ),
            };
            let mut fields = Metadata::new();
            fields.insert("cell_id".to_owned(), cell_id.to_owned());
            failure(
                PlatformError {
                    code,
                    message: bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
                    retryable: false,
                    details: vec![ErrorDetail {
                        kind: detail_kind.to_owned(),
                        fields,
                    }],
                },
                consumption,
            )
        }
        Err(error) => failure(sanitize_error(error), BudgetConsumption::default()),
    }
}

fn cancellation_failure(reason: Option<String>) -> ActivationOutcome {
    failure(
        platform_error(
            PlatformErrorCode::Cancelled,
            reason.as_deref().unwrap_or("activation cancelled"),
            false,
        ),
        BudgetConsumption::default(),
    )
}

fn deadline_failure(message: &str) -> ActivationOutcome {
    failure(
        platform_error(PlatformErrorCode::DeadlineExceeded, message, false),
        BudgetConsumption::default(),
    )
}

fn failure(error: PlatformError, consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: terminal_state_for_error(error.code),
        error,
        consumption,
    }
}

fn terminal_state_for_error(code: PlatformErrorCode) -> ActivationTerminalState {
    match code {
        PlatformErrorCode::DeadlineExceeded => ActivationTerminalState::DeadlineExceeded,
        PlatformErrorCode::Cancelled => ActivationTerminalState::Cancelled,
        PlatformErrorCode::ResourceExhausted => ActivationTerminalState::ResourceExhausted,
        PlatformErrorCode::GuestTrap => ActivationTerminalState::GuestTrap,
        PlatformErrorCode::StateConflict => ActivationTerminalState::StateConflict,
        PlatformErrorCode::DependencyFailed
        | PlatformErrorCode::Unavailable
        | PlatformErrorCode::RouteUnavailable => ActivationTerminalState::DependencyFailed,
        PlatformErrorCode::PermissionDenied
        | PlatformErrorCode::Unauthenticated
        | PlatformErrorCode::InvalidArgument
        | PlatformErrorCode::NotFound
        | PlatformErrorCode::AlreadyExists
        | PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::CorruptArtifact
        | PlatformErrorCode::AdmissionRejected => ActivationTerminalState::Rejected,
        PlatformErrorCode::Internal => ActivationTerminalState::PlatformFailed,
        _ => ActivationTerminalState::PlatformFailed,
    }
}

fn outcome_consumption(outcome: &ActivationOutcome) -> BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => success.consumption.clone(),
        ActivationOutcome::Failed { consumption, .. } => consumption.clone(),
    }
}

fn sanitize_error(mut error: PlatformError) -> PlatformError {
    error.message = bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES);
    error.details.truncate(MAX_ERROR_DETAILS);
    for detail in &mut error.details {
        detail.kind = bounded_text(&detail.kind, MAX_DETAIL_NAME_BYTES);
        detail.fields = detail
            .fields
            .iter()
            .take(MAX_DETAIL_FIELDS)
            .map(|(name, value)| {
                (
                    bounded_text(name, MAX_DETAIL_NAME_BYTES),
                    bounded_text(value, MAX_DETAIL_VALUE_BYTES),
                )
            })
            .collect();
    }
    error
}

fn platform_error(
    code: PlatformErrorCode,
    message: &str,
    retryable: bool,
) -> PlatformError {
    PlatformError {
        code,
        message: bounded_text(message, MAX_DIAGNOSTIC_BYTES),
        retryable,
        details: Vec::new(),
    }
}

fn earliest_deadline(first: Option<u64>, second: Option<u64>) -> Option<u64> {
    match (first, second) {
        (Some(first), Some(second)) => Some(first.min(second)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

async fn wait_for_deadline(deadline: Option<u64>) {
    let Some(deadline) = deadline else {
        pending::<()>().await;
        return;
    };
    tokio::time::sleep(Duration::from_millis(
        deadline.saturating_sub(now_unix_millis()),
    ))
    .await;
}

fn deadline_expired(deadline: Option<u64>) -> bool {
    deadline.is_some_and(|deadline| deadline <= now_unix_millis())
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}

fn bounded_text(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}
