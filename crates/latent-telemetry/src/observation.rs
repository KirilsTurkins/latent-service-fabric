//! Payload-free observations from the single owner of an activation lifecycle.

use std::time::Duration;

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BudgetConsumption, CancelDisposition,
    ContractId, FunctionId, Metadata, PlatformError, PlatformErrorCode, ReleaseDigest,
    ResourceBudget, RevisionId, RouteGeneration, ServiceId, SpanId, TenantId, TraceId,
};

use crate::LogSeverity;

/// Identifies one accepted lifecycle even after its caller ID is reused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ActivationObservationToken {
    pub manager: u64,
    pub sequence: u64,
}

/// Correlation only: no payload, caller metadata, principal claims, or baggage.
/// Observers must validate borrowed string bounds before retaining a copy.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationObservationContext {
    pub token: ActivationObservationToken,
    pub activation_id: ActivationId,
    pub root_activation_id: ActivationId,
    pub parent_activation_id: Option<ActivationId>,
    pub tenant: TenantId,
    pub service: ServiceId,
    pub contract: ContractId,
    pub function: FunctionId,
    pub trace_id: TraceId,
    pub span_id: SpanId,
    pub trace_flags: u8,
    pub release: Option<ReleaseDigest>,
    pub revision: Option<RevisionId>,
    pub route_generation: Option<RouteGeneration>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationOutcomeClass {
    GuestSuccess,
    GuestDomainError,
    PlatformFailure,
}

impl ActivationOutcomeClass {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::GuestSuccess => "guest_success",
            Self::GuestDomainError => "guest_domain_error",
            Self::PlatformFailure => "platform_failure",
        }
    }
}

/// The disposition actually observed, without an untrusted reason string.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationCleanupDisposition {
    NoCell,
    Released,
    Quarantined,
    ReclaimedBeforeExecution,
    Abandoned,
    Failed,
}

/// Emitted only after accounting and the terminal journal transaction finish.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationTerminalObservation {
    pub class: ActivationOutcomeClass,
    pub terminal_state: ActivationTerminalState,
    pub platform_code: Option<PlatformErrorCode>,
    pub consumption: BudgetConsumption,
    pub last_phase: ActivationPhase,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationObservationKind {
    Received,
    /// A successfully committed live journal transition.
    Phase {
        phase: ActivationPhase,
        sequence: u64,
    },
    AdmittedGrant(ResourceBudget),
    Cancellation(CancelDisposition),
    Cleanup(ActivationCleanupDisposition),
    Terminal(ActivationTerminalObservation),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationObservation {
    pub occurred_at_unix_millis: u64,
    /// Elapsed time from acceptance, measured in the manager's monotonic domain.
    pub elapsed: Duration,
    pub kind: ActivationObservationKind,
}

/// Borrowed host-log input is checked before any export allocation occurs.
#[derive(Debug, Clone, Copy)]
pub struct GuestLogRecord<'a> {
    pub activation_id: &'a ActivationId,
    pub severity: LogSeverity,
    pub body: &'a str,
    pub fields: &'a Metadata,
    pub observed_at_unix_millis: u64,
}

pub trait GuestLogObserver: Send + Sync {
    fn on_guest_log(&self, record: GuestLogRecord<'_>) -> Result<(), PlatformError>;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NoopActivationObserver;

impl crate::ActivationObserver for NoopActivationObserver {
    fn on_observation(
        &self,
        _context: &ActivationObservationContext,
        _event: &ActivationObservation,
    ) {
    }
}

impl GuestLogObserver for NoopActivationObserver {
    fn on_guest_log(&self, _record: GuestLogRecord<'_>) -> Result<(), PlatformError> {
        Ok(())
    }
}
