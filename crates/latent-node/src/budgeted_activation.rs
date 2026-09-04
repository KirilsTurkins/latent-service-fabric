use std::collections::HashMap;
use std::fmt;
use std::ops::Deref;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome};
use latent_core::{
    ActivationBudget, ActivationId, ActivationTerminalState, BoxFuture, BudgetConsumption,
    BudgetError, CancelDisposition, EffectiveActivationBudget, ErrorDetail, Metadata,
    PlatformError, PlatformErrorCode, ResourceBudget,
};

use crate::cancellation::{
    ActivationCancellationRegistry, CancellationRegistrySnapshot, CancellationToken,
};

const DEFAULT_MAXIMUM_CANCELLATION_REASON_BYTES: usize = 256;
const CANCELLATION_MESSAGE: &str = "activation cancelled";
const DEADLINE_MESSAGE: &str = "activation wall-clock deadline exceeded";

/// Clock boundary used to bind an admitted wall-clock deadline to monotonic
/// process time. Tests may inject a deterministic implementation.
pub trait ActivationClock: Send + Sync {
    fn unix_millis(&self) -> u64;
    fn monotonic(&self) -> Instant;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct SystemActivationClock;

impl ActivationClock for SystemActivationClock {
    fn unix_millis(&self) -> u64 {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        u64::try_from(millis).unwrap_or(u64::MAX)
    }

    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}

/// Reusable deployment and node ceilings applied to every wrapped invocation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationBudgetPolicy {
    pub deployment_ceiling: ResourceBudget,
    pub node_ceiling: ResourceBudget,
    pub maximum_cancellation_reason_bytes: usize,
}

impl ActivationBudgetPolicy {
    #[must_use]
    pub fn new(deployment_ceiling: ResourceBudget, node_ceiling: ResourceBudget) -> Self {
        Self {
            deployment_ceiling,
            node_ceiling,
            maximum_cancellation_reason_bytes: DEFAULT_MAXIMUM_CANCELLATION_REASON_BYTES,
        }
    }
}

/// Constant-time observations for live activation budget state.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ActivationBudgetRegistrySnapshot {
    pub active_registrations: u64,
}

/// Shared activation-ID lookup used by execution and host-capability adapters.
#[derive(Debug, Clone, Default)]
pub struct ActivationBudgetRegistry {
    inner: Arc<Mutex<HashMap<ActivationId, ActivationBudget>>>,
}

impl ActivationBudgetRegistry {
    fn register(
        &self,
        activation_id: ActivationId,
        budget: ActivationBudget,
    ) -> Result<ActivationBudgetRegistration, PlatformError> {
        let mut registrations = self.lock();
        if registrations.contains_key(&activation_id) {
            return Err(PlatformError {
                code: PlatformErrorCode::AlreadyExists,
                message: "activation already has live budget accounting".to_owned(),
                retryable: false,
                details: vec![ErrorDetail {
                    kind: "activation.budget-duplicate-registration".to_owned(),
                    fields: Metadata::from([(
                        "activation_id".to_owned(),
                        activation_id.0.clone(),
                    )]),
                }],
            });
        }
        registrations.insert(activation_id.clone(), budget.clone());
        Ok(ActivationBudgetRegistration {
            registry: self.clone(),
            activation_id,
            budget,
        })
    }

    #[must_use]
    pub fn get(&self, activation_id: &ActivationId) -> Option<ActivationBudget> {
        self.lock().get(activation_id).cloned()
    }

    #[must_use]
    pub fn snapshot(&self) -> ActivationBudgetRegistrySnapshot {
        ActivationBudgetRegistrySnapshot {
            active_registrations: u64::try_from(self.lock().len()).unwrap_or(u64::MAX),
        }
    }

    fn remove_if_current(&self, activation_id: &ActivationId, budget: &ActivationBudget) {
        let mut registrations = self.lock();
        if registrations
            .get(activation_id)
            .is_some_and(|current| current.is_same_instance(budget))
        {
            registrations.remove(activation_id);
        }
    }

    fn lock(&self) -> MutexGuard<'_, HashMap<ActivationId, ActivationBudget>> {
        self.inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

struct ActivationBudgetRegistration {
    registry: ActivationBudgetRegistry,
    activation_id: ActivationId,
    budget: ActivationBudget,
}

impl Drop for ActivationBudgetRegistration {
    fn drop(&mut self) {
        self.registry
            .remove_if_current(&self.activation_id, &self.budget);
    }
}

/// Activation manager decorator that makes admission budgets and terminal
/// accounting mandatory before delegating to a cell-allocating manager.
///
/// The wrapper is deliberately generic and dereferences to the wrapped manager,
/// preserving access to implementation-specific observations such as the Phase
/// 0 runner snapshot while providing the Phase 1 budget/cancellation surface.
pub struct BudgetedActivationManager<M> {
    inner: Arc<M>,
    policy: ActivationBudgetPolicy,
    clock: Arc<dyn ActivationClock>,
    budgets: ActivationBudgetRegistry,
    cancellations: ActivationCancellationRegistry,
}

impl<M> fmt::Debug for BudgetedActivationManager<M> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BudgetedActivationManager")
            .field("policy", &self.policy)
            .field("budget_registry", &self.budgets.snapshot())
            .field("cancellation_registry", &self.cancellations.snapshot())
            .finish_non_exhaustive()
    }
}

impl<M> BudgetedActivationManager<M>
where
    M: ActivationManager + 'static,
{
    pub fn new(inner: Arc<M>, policy: ActivationBudgetPolicy) -> Result<Self, PlatformError> {
        Self::new_with_clock(inner, policy, Arc::new(SystemActivationClock))
    }

    pub fn new_with_clock(
        inner: Arc<M>,
        policy: ActivationBudgetPolicy,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        let cancellations =
            ActivationCancellationRegistry::new(policy.maximum_cancellation_reason_bytes)?;
        Ok(Self {
            inner,
            policy,
            clock,
            budgets: ActivationBudgetRegistry::default(),
            cancellations,
        })
    }

    #[must_use]
    pub fn policy(&self) -> &ActivationBudgetPolicy {
        &self.policy
    }

    #[must_use]
    pub fn budget_registry(&self) -> ActivationBudgetRegistry {
        self.budgets.clone()
    }

    #[must_use]
    pub fn cancellation_registry(&self) -> ActivationCancellationRegistry {
        self.cancellations.clone()
    }

    #[must_use]
    pub fn budget_snapshot(&self) -> ActivationBudgetRegistrySnapshot {
        self.budgets.snapshot()
    }

    #[must_use]
    pub fn cancellation_snapshot(&self) -> CancellationRegistrySnapshot {
        self.cancellations.snapshot()
    }

    fn admit(
        &self,
        envelope: &ActivationEnvelope,
    ) -> Result<EffectiveActivationBudget, BudgetError> {
        let grant = EffectiveActivationBudget::admit_at(
            &envelope.budget,
            &self.policy.deployment_ceiling,
            &self.policy.node_ceiling,
            envelope.deadline_unix_millis,
            self.clock.unix_millis(),
            self.clock.monotonic(),
        )?;
        grant.require_executable_capacity()?;
        Ok(grant)
    }

    async fn invoke_admitted(
        &self,
        mut envelope: ActivationEnvelope,
        grant: EffectiveActivationBudget,
    ) -> ActivationOutcome {
        let activation_id = envelope.activation_id.clone();
        envelope.budget = grant.budget.clone();
        envelope.deadline_unix_millis = grant.deadline.unix_millis();

        let accounting = ActivationBudget::new(grant);
        let budget_registration =
            match self
                .budgets
                .register(activation_id.clone(), accounting.clone())
            {
                Ok(registration) => registration,
                Err(error) => return platform_failure(error, BudgetConsumption::default()),
            };
        let cancellation_registration = match self.cancellations.register(activation_id.clone()) {
            Ok(registration) => registration,
            Err(error) => {
                drop(budget_registration);
                return platform_failure(error, BudgetConsumption::default());
            }
        };
        let token = cancellation_registration.token();

        let outcome = self.inner.invoke(envelope).await;
        let now = self.clock.monotonic();
        let outcome = apply_terminal_precedence(outcome, &token, &accounting, now);
        let reported = outcome_consumption(&outcome);
        let finalized = match accounting.finalize_at(Some(&reported), now) {
            Ok(finalized) => finalized,
            Err(error) => {
                let consumption = accounting
                    .finalize_at(None, now)
                    .unwrap_or_else(|_| accounting.snapshot_at(now));
                drop(cancellation_registration);
                drop(budget_registration);
                return budget_failure(error, consumption);
            }
        };
        let outcome = replace_consumption(outcome, finalized);
        drop(cancellation_registration);
        drop(budget_registration);
        outcome
    }
}

impl<M> Deref for BudgetedActivationManager<M> {
    type Target = M;

    fn deref(&self) -> &Self::Target {
        self.inner.as_ref()
    }
}

impl<M> ActivationManager for BudgetedActivationManager<M>
where
    M: ActivationManager + 'static,
{
    fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome> {
        Box::pin(async move {
            let grant = match self.admit(&envelope) {
                Ok(grant) => grant,
                Err(error) => return budget_failure(error, BudgetConsumption::default()),
            };
            self.invoke_admitted(envelope, grant).await
        })
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        Box::pin(async move {
            let local = self.cancellations.cancel(activation_id, reason);
            let delegated = self.inner.cancel(activation_id, reason).await;
            match local {
                CancelDisposition::Accepted => Ok(CancelDisposition::Accepted),
                CancelDisposition::NotFound | CancelDisposition::AlreadyTerminal(_) => delegated,
            }
        })
    }
}

fn apply_terminal_precedence(
    outcome: ActivationOutcome,
    cancellation: &CancellationToken,
    accounting: &ActivationBudget,
    now: Instant,
) -> ActivationOutcome {
    let consumption = outcome_consumption(&outcome);
    if cancellation.is_cancelled() {
        return platform_failure(cancellation_error(cancellation.reason()), consumption);
    }
    if accounting.check_deadline_at(now).is_err() {
        return platform_failure(deadline_error(), consumption);
    }
    outcome
}

fn replace_consumption(
    outcome: ActivationOutcome,
    consumption: BudgetConsumption,
) -> ActivationOutcome {
    match outcome {
        ActivationOutcome::Succeeded(mut success) => {
            success.consumption = consumption;
            ActivationOutcome::Succeeded(success)
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            ActivationOutcome::DeclaredError { error, consumption }
        }
        ActivationOutcome::Failed {
            terminal_state,
            error,
            ..
        } => ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption,
        },
    }
}

fn outcome_consumption(outcome: &ActivationOutcome) -> BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => success.consumption.clone(),
        ActivationOutcome::DeclaredError { consumption, .. }
        | ActivationOutcome::Failed { consumption, .. } => consumption.clone(),
    }
}

fn budget_failure(error: BudgetError, consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: error.terminal_state(),
        error: error.to_platform_error(),
        consumption,
    }
}

fn platform_failure(error: PlatformError, consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: terminal_state_for_code(error.code),
        error,
        consumption,
    }
}

fn cancellation_error(reason: Option<String>) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Cancelled,
        message: reason
            .filter(|reason| !reason.trim().is_empty())
            .unwrap_or_else(|| CANCELLATION_MESSAGE.to_owned()),
        retryable: false,
        details: vec![ErrorDetail {
            kind: "activation.cancelled".to_owned(),
            fields: Metadata::new(),
        }],
    }
}

fn deadline_error() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::DeadlineExceeded,
        message: DEADLINE_MESSAGE.to_owned(),
        retryable: false,
        details: vec![ErrorDetail {
            kind: "activation.deadline-exceeded".to_owned(),
            fields: Metadata::new(),
        }],
    }
}

fn terminal_state_for_code(code: PlatformErrorCode) -> ActivationTerminalState {
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

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};

    use latent_activation::{
        ActivationManager, ActivationOutcome, ActivationSuccess, TraceContext,
    };
    use latent_core::{
        ContractId, DeclaredError, FunctionId, InvocationPrincipal, PrincipalKind, ServiceId,
        SpanId, TenantId, TraceId,
    };
    use latent_routing::InvocationTarget;

    use super::*;

    #[derive(Debug)]
    struct FixedClock {
        unix_millis: AtomicU64,
        started: Instant,
    }

    impl FixedClock {
        fn new(unix_millis: u64) -> Self {
            Self {
                unix_millis: AtomicU64::new(unix_millis),
                started: Instant::now(),
            }
        }
    }

    impl ActivationClock for FixedClock {
        fn unix_millis(&self) -> u64 {
            self.unix_millis.load(Ordering::Acquire)
        }

        fn monotonic(&self) -> Instant {
            self.started
        }
    }

    #[derive(Debug)]
    struct RecordingManager {
        invocations: AtomicU64,
        captured: Mutex<Vec<ActivationEnvelope>>,
        outcome: Mutex<ActivationOutcome>,
    }

    impl RecordingManager {
        fn new(outcome: ActivationOutcome) -> Self {
            Self {
                invocations: AtomicU64::new(0),
                captured: Mutex::new(Vec::new()),
                outcome: Mutex::new(outcome),
            }
        }
    }

    impl ActivationManager for RecordingManager {
        fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome> {
            Box::pin(async move {
                self.invocations.fetch_add(1, Ordering::AcqRel);
                self.captured
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(envelope);
                self.outcome
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .clone()
            })
        }

        fn cancel<'a>(
            &'a self,
            _activation_id: &'a ActivationId,
            _reason: &'a str,
        ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
            Box::pin(async move { Ok(CancelDisposition::Accepted) })
        }
    }

    fn budget() -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 1_024,
            wall_time_limit_millis: Some(500),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 100,
            effect_count: 0,
        }
    }

    fn envelope(deadline: Option<u64>) -> ActivationEnvelope {
        let id = ActivationId("budgeted-activation".to_owned());
        let tenant = TenantId("tenant".to_owned());
        ActivationEnvelope {
            activation_id: id.clone(),
            parent_activation_id: None,
            root_activation_id: id,
            principal: InvocationPrincipal {
                subject: "test".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(tenant.clone()),
                service: None,
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant,
                service: ServiceId("service".to_owned()),
                contract: ContractId("test:service/api@0.1.0".to_owned()),
                function: FunctionId("run".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: deadline,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace".to_owned()),
                span_id: SpanId("span".to_owned()),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget(),
            metadata: Metadata::new(),
            input: Vec::new(),
            input_media_type: "application/octet-stream".to_owned(),
        }
    }

    fn success(consumption: BudgetConsumption) -> ActivationOutcome {
        ActivationOutcome::Succeeded(ActivationSuccess {
            output: Vec::new(),
            output_media_type: "application/octet-stream".to_owned(),
            consumption,
            committed_state_version: None,
            effect_ids: Vec::new(),
            metadata: Metadata::new(),
        })
    }

    fn manager(
        inner: Arc<RecordingManager>,
        clock: Arc<FixedClock>,
    ) -> BudgetedActivationManager<RecordingManager> {
        let mut deployment = budget();
        deployment.cpu_fuel = 80;
        let mut node = budget();
        node.memory_bytes = 512;
        node.log_bytes = 60;
        BudgetedActivationManager::new_with_clock(
            inner,
            ActivationBudgetPolicy::new(deployment, node),
            clock,
        )
        .expect("manager is valid")
    }

    #[tokio::test]
    async fn rejects_invalid_or_expired_invocations_before_delegation() {
        let inner = Arc::new(RecordingManager::new(success(BudgetConsumption::default())));
        let clock = Arc::new(FixedClock::new(1_000));
        let manager = manager(Arc::clone(&inner), clock);

        let mut invalid = envelope(Some(1_500));
        invalid.budget.effect_count = 1;
        assert!(matches!(
            manager.invoke(invalid).await,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Rejected,
                ..
            }
        ));
        assert!(matches!(
            manager.invoke(envelope(Some(1_000))).await,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::DeadlineExceeded,
                ..
            }
        ));
        assert_eq!(inner.invocations.load(Ordering::Acquire), 0);
    }

    #[tokio::test]
    async fn delegates_only_the_bounded_intersection() {
        let inner = Arc::new(RecordingManager::new(success(BudgetConsumption {
            cpu_fuel: 7,
            peak_memory_bytes: 128,
            log_bytes: 9,
            ..BudgetConsumption::default()
        })));
        let clock = Arc::new(FixedClock::new(1_000));
        let manager = manager(Arc::clone(&inner), clock);
        let outcome = manager.invoke(envelope(Some(1_400))).await;
        assert!(matches!(outcome, ActivationOutcome::Succeeded(_)));
        let captured = inner
            .captured
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(captured.len(), 1);
        assert_eq!(captured[0].budget.cpu_fuel, 80);
        assert_eq!(captured[0].budget.memory_bytes, 512);
        assert_eq!(captured[0].budget.log_bytes, 60);
        assert_eq!(captured[0].deadline_unix_millis, Some(1_400));
        assert_eq!(manager.budget_snapshot().active_registrations, 0);
        assert_eq!(manager.cancellation_snapshot().active_registrations, 0);
    }

    #[tokio::test]
    async fn finalizes_every_terminal_outcome_shape() {
        let consumption = BudgetConsumption {
            cpu_fuel: 7,
            peak_memory_bytes: 128,
            log_bytes: 9,
            ..BudgetConsumption::default()
        };
        let outcomes = [
            success(consumption.clone()),
            ActivationOutcome::DeclaredError {
                error: DeclaredError {
                    code: "domain".to_owned(),
                    message: "declared".to_owned(),
                    payload: Vec::new(),
                    media_type: "application/octet-stream".to_owned(),
                    metadata: Metadata::new(),
                },
                consumption: consumption.clone(),
            },
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::GuestTrap,
                error: PlatformError {
                    code: PlatformErrorCode::GuestTrap,
                    message: "trap".to_owned(),
                    retryable: false,
                    details: Vec::new(),
                },
                consumption: consumption.clone(),
            },
        ];

        for (index, outcome) in outcomes.into_iter().enumerate() {
            let inner = Arc::new(RecordingManager::new(outcome));
            let clock = Arc::new(FixedClock::new(1_000));
            let manager = manager(inner, clock);
            let mut request = envelope(Some(1_400));
            request.activation_id = ActivationId(format!("terminal-{index}"));
            request.root_activation_id = request.activation_id.clone();
            let outcome = manager.invoke(request).await;
            assert_eq!(outcome_consumption(&outcome).cpu_fuel, 7);
            assert_eq!(outcome_consumption(&outcome).peak_memory_bytes, 128);
            assert_eq!(outcome_consumption(&outcome).log_bytes, 9);
            assert_eq!(manager.budget_snapshot().active_registrations, 0);
            assert_eq!(manager.cancellation_snapshot().active_registrations, 0);
        }
    }

    #[tokio::test]
    async fn forged_later_phase_consumption_becomes_platform_failure() {
        let inner = Arc::new(RecordingManager::new(success(BudgetConsumption {
            effect_count: 1,
            ..BudgetConsumption::default()
        })));
        let clock = Arc::new(FixedClock::new(1_000));
        let manager = manager(inner, clock);
        let outcome = manager.invoke(envelope(Some(1_400))).await;
        assert!(matches!(
            outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::PlatformFailed,
                error: PlatformError {
                    code: PlatformErrorCode::Internal,
                    ..
                },
                ..
            }
        ));
    }
}
