//! Activation envelope, state machine, results, events, and manager interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BoxFuture, BudgetConsumption,
    CancelDisposition, DeclaredError, IdempotencyKey, InvocationPrincipal, Metadata, Payload,
    PlatformError, ResourceBudget, SpanId, TraceId,
};
use latent_routing::{InvocationTarget, ResolvedRevision};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TraceContext {
    pub trace_id: TraceId,
    pub span_id: SpanId,
    pub trace_flags: u8,
    pub baggage: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationEnvelope {
    pub activation_id: ActivationId,
    pub parent_activation_id: Option<ActivationId>,
    pub root_activation_id: ActivationId,
    pub principal: InvocationPrincipal,
    pub target: InvocationTarget,
    pub resolved_revision: Option<ResolvedRevision>,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub trace: TraceContext,
    pub idempotency_key: Option<IdempotencyKey>,
    pub retry_attempt: u32,
    pub budget: ResourceBudget,
    pub metadata: Metadata,
    pub input: Payload,
    pub input_media_type: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationSuccess {
    pub output: Payload,
    pub output_media_type: String,
    pub consumption: BudgetConsumption,
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationOutcome {
    Succeeded(ActivationSuccess),
    DeclaredError {
        error: DeclaredError,
        consumption: BudgetConsumption,
    },
    Failed {
        terminal_state: ActivationTerminalState,
        error: PlatformError,
        consumption: BudgetConsumption,
    },
}

/// The terminal result retained for `GetActivation` and CLI diagnostics.
///
/// A status record must retain an outcome classification and finalized resource
/// consumption for every terminal activation; it must not collapse a declared
/// component error into a platform failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RetainedActivationOutcome {
    Succeeded,
    DeclaredError(DeclaredError),
    PlatformFailure(PlatformError),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationStatus {
    pub activation_id: ActivationId,
    pub phase: ActivationPhase,
    pub terminal_state: Option<ActivationTerminalState>,
    pub terminal_outcome: Option<RetainedActivationOutcome>,
    pub final_consumption: Option<BudgetConsumption>,
    pub last_updated_unix_millis: u64,
    pub terminal_at_unix_millis: Option<u64>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationEvent {
    pub activation_id: ActivationId,
    pub phase: ActivationPhase,
    pub occurred_at_unix_millis: u64,
    pub sequence: u64,
    pub attributes: Metadata,
}

pub trait ActivationManager: Send + Sync {
    fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome>;

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>>;
}

pub trait ActivationJournal: Send + Sync {
    fn append<'a>(&'a self, event: ActivationEvent) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn read<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<Vec<ActivationEvent>, PlatformError>>;
}
