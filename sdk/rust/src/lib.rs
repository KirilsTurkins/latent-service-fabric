//! Interface-only Rust SDK for LSF clients and guest-facing abstractions.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BoxFuture, BudgetConsumption,
    CancelDisposition, ContractId, DeclaredError, FunctionId, IdempotencyKey, InvocationPrincipal,
    Metadata, Payload, ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration, ServiceId,
    TenantId, TraceId,
};

pub use latent_core::{ErrorDetail, PlatformError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationTarget {
    pub tenant: TenantId,
    pub service: ServiceId,
    pub contract: ContractId,
    pub function: FunctionId,
    pub route: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvokeOptions {
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub idempotency_key: Option<IdempotencyKey>,
    pub budget: ResourceBudget,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvokeRequest {
    pub target: InvocationTarget,
    pub payload: Payload,
    pub media_type: String,
    pub options: InvokeOptions,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvokeResponse {
    pub activation_id: ActivationId,
    pub revision_id: RevisionId,
    pub release_digest: ReleaseDigest,
    pub route_generation: RouteGeneration,
    pub payload: Payload,
    pub media_type: String,
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub consumption: BudgetConsumption,
    pub metadata: Metadata,
}

/// Common receipt fields returned for every terminal invocation outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationReceipt {
    pub activation_id: ActivationId,
    pub revision_id: RevisionId,
    pub release_digest: ReleaseDigest,
    pub route_generation: RouteGeneration,
    pub consumption: BudgetConsumption,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeclaredInvocationError {
    pub receipt: InvocationReceipt,
    pub error: DeclaredError,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformInvocationFailure {
    pub receipt: InvocationReceipt,
    pub error: PlatformError,
}

/// Wire-visible invocation results. Platform failures are values here rather
/// than transport errors so callers cannot confuse them with declared guest
/// errors or a failed RPC transport.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InvocationOutcome {
    Succeeded(InvokeResponse),
    DeclaredError(DeclaredInvocationError),
    PlatformFailure(PlatformInvocationFailure),
}

/// A cancellation result normalized from the wire representation.
///
/// The Protobuf response carries an enum plus an optional terminal-state
/// field. The SDK deliberately exposes a closed Rust enum instead, so an
/// already-terminal result has exactly one terminal state and accepted or
/// not-found results cannot carry a contradictory one.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CancelResponse {
    Accepted,
    AlreadyTerminal(ActivationTerminalState),
    NotFound,
}

impl From<CancelDisposition> for CancelResponse {
    fn from(disposition: CancelDisposition) -> Self {
        match disposition {
            CancelDisposition::Accepted => Self::Accepted,
            CancelDisposition::AlreadyTerminal(state) => Self::AlreadyTerminal(state),
            CancelDisposition::NotFound => Self::NotFound,
        }
    }
}

impl From<CancelResponse> for CancelDisposition {
    fn from(response: CancelResponse) -> Self {
        match response {
            CancelResponse::Accepted => Self::Accepted,
            CancelResponse::AlreadyTerminal(state) => Self::AlreadyTerminal(state),
            CancelResponse::NotFound => Self::NotFound,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RetainedInvocationOutcome {
    Succeeded {
        committed_state_version: Option<String>,
        effect_ids: Vec<String>,
        metadata: Metadata,
    },
    DeclaredError(DeclaredError),
    PlatformFailure(PlatformError),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationStatus {
    pub activation_id: ActivationId,
    pub phase: ActivationPhase,
    pub terminal_state: Option<ActivationTerminalState>,
    pub terminal_outcome: Option<RetainedInvocationOutcome>,
    pub final_consumption: Option<BudgetConsumption>,
    pub last_updated_unix_millis: u64,
    pub terminal_at_unix_millis: Option<u64>,
    pub metadata: Metadata,
}

/// Failure to send, receive, authenticate, or decode an RPC response.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientTransportError {
    pub message: String,
    pub retryable: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GuestInvocationContext {
    pub activation_id: ActivationId,
    pub root_activation_id: ActivationId,
    pub parent_activation_id: Option<ActivationId>,
    pub principal: InvocationPrincipal,
    pub trace_id: TraceId,
    pub deadline_unix_millis: Option<u64>,
    pub remaining_budget: ResourceBudget,
    pub metadata: Metadata,
}

pub trait LatentClient: Send + Sync {
    fn invoke<'a>(
        &'a self,
        request: InvokeRequest,
    ) -> BoxFuture<'a, Result<InvocationOutcome, ClientTransportError>>;

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelResponse, ClientTransportError>>;

    fn get_activation<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<ActivationStatus, ClientTransportError>>;
}

pub trait GuestContext: Send + Sync {
    fn current(&self) -> Result<GuestInvocationContext, PlatformError>;
}

pub trait ContractCodec<T>: Send + Sync {
    fn media_type(&self) -> &str;
    fn encode(&self, value: &T) -> Result<Vec<u8>, PlatformError>;
    fn decode(&self, bytes: &[u8]) -> Result<T, PlatformError>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancellation_response_has_one_canonical_terminal_state() {
        let response = CancelResponse::from(CancelDisposition::AlreadyTerminal(
            ActivationTerminalState::Completed,
        ));

        assert_eq!(
            response,
            CancelResponse::AlreadyTerminal(ActivationTerminalState::Completed)
        );
        assert_eq!(
            CancelDisposition::from(response),
            CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed)
        );
    }
}
