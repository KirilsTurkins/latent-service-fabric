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

/// The terminal-success fields retained by `GetActivation`.
///
/// Payload bytes are returned only by the immediate invocation response. A
/// retained status instead preserves the committed-state, effect, and metadata
/// fields that describe the completed activation without losing their meaning
/// on the domain-to-wire-to-domain path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationSuccessSummary {
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub metadata: Metadata,
}

impl From<&ActivationSuccess> for ActivationSuccessSummary {
    fn from(success: &ActivationSuccess) -> Self {
        Self {
            committed_state_version: success.committed_state_version.clone(),
            effect_ids: success.effect_ids.clone(),
            metadata: success.metadata.clone(),
        }
    }
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
    Succeeded(ActivationSuccessSummary),
    DeclaredError(DeclaredError),
    PlatformFailure(PlatformError),
}

impl ActivationOutcome {
    /// Produces the lossless retained terminal classification for diagnostics.
    #[must_use]
    pub fn retained_terminal_outcome(&self) -> RetainedActivationOutcome {
        match self {
            Self::Succeeded(success) => {
                RetainedActivationOutcome::Succeeded(ActivationSuccessSummary::from(success))
            }
            Self::DeclaredError { error, .. } => {
                RetainedActivationOutcome::DeclaredError(error.clone())
            }
            Self::Failed { error, .. } => RetainedActivationOutcome::PlatformFailure(error.clone()),
        }
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_success_keeps_every_advertised_status_field() {
        let success = ActivationSuccess {
            output: b"immediate-only".to_vec(),
            output_media_type: "application/octet-stream".to_owned(),
            consumption: BudgetConsumption::default(),
            committed_state_version: Some("state-v42".to_owned()),
            effect_ids: vec!["effect-a".to_owned(), "effect-b".to_owned()],
            metadata: Metadata::from([("commit".to_owned(), "complete".to_owned())]),
        };

        assert_eq!(
            ActivationOutcome::Succeeded(success).retained_terminal_outcome(),
            RetainedActivationOutcome::Succeeded(ActivationSuccessSummary {
                committed_state_version: Some("state-v42".to_owned()),
                effect_ids: vec!["effect-a".to_owned(), "effect-b".to_owned()],
                metadata: Metadata::from([("commit".to_owned(), "complete".to_owned())]),
            })
        );
    }
}
