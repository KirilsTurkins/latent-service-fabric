//! Bounded invocation RPC adapters and a bridge to the local lifecycle owner.

mod authentication;
mod cancellation;
mod conversion;
mod deadline;
mod errors;
mod limits;
mod local;
mod service;
mod trace;
mod validation;

use latent_activation::{ActivationOutcome, ActivationStatus, TraceContext};
use latent_core::{
    ActivationId, BoxFuture, CancelDisposition, IdempotencyKey, InvocationPrincipal, Metadata,
    PlatformError, ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration,
};
use latent_routing::InvocationTarget;

pub(crate) use authentication::authenticated_tenant;
pub use authentication::{AuthenticatedInvocationContext, LocalPrincipalPolicy, PrincipalPolicy};
pub use cancellation::{InvocationCancellation, InvocationInterruption};
pub use conversion::{
    activation_status_from_proto, activation_status_to_proto, budget_from_proto, budget_to_proto,
    cancel_disposition_from_proto, cancel_disposition_to_proto, consumption_from_proto,
    consumption_to_proto, declared_error_from_proto, declared_error_to_proto,
    invocation_request_from_proto, invocation_request_to_proto, invocation_response_from_proto,
    invocation_response_to_proto, platform_error_from_proto, platform_error_to_proto,
    InvocationConversionError,
};
use errors::{boundary_error, platform_status, public_platform_message};
pub use latent_rpc::invocation::v1 as proto;
pub use limits::InvocationLimits;
pub use local::LocalInvocationRuntime;
pub use proto::invocation_service_client::InvocationServiceClient;
pub use proto::invocation_service_server::{InvocationService, InvocationServiceServer};
pub use service::{InvocationServiceAdapter, InvocationServiceServices};
pub use trace::{InvocationTraceSource, SystemInvocationTraceSource};

/// Missing IDs remain absent until the activation manager accepts the request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationRequest {
    pub requested_activation_id: Option<ActivationId>,
    pub parent_activation_id: Option<ActivationId>,
    pub root_activation_id: Option<ActivationId>,
    pub target: InvocationTarget,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub idempotency_key: Option<IdempotencyKey>,
    pub budget: ResourceBudget,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationCommand {
    pub principal: InvocationPrincipal,
    pub trace: TraceContext,
    pub request: InvocationRequest,
}

/// The exact pin known by the lifecycle owner, without fabricated routing data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationRevision {
    pub revision_id: RevisionId,
    pub release_digest: ReleaseDigest,
    pub route_generation: RouteGeneration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationReceipt {
    pub activation_id: ActivationId,
    /// Absent for accepted terminal failures before route resolution.
    pub resolved_revision: Option<InvocationRevision>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationResponse {
    pub receipt: InvocationReceipt,
    pub outcome: ActivationOutcome,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CancellationCommand {
    pub principal: InvocationPrincipal,
    pub activation_id: ActivationId,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusQuery {
    pub principal: InvocationPrincipal,
    pub activation_id: ActivationId,
}

/// Implementations reserve identity synchronously before returning the future.
/// That future owns cleanup, and status/cancellation authorize tenant scope in
/// the same operation that observes or mutates the activation.
pub trait InvocationRuntime: Send + Sync {
    fn invoke(
        &self,
        command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'_, Result<InvocationResponse, PlatformError>>;
    fn cancel(
        &self,
        command: CancellationCommand,
    ) -> BoxFuture<'_, Result<CancelDisposition, PlatformError>>;
    fn get_activation(
        &self,
        query: StatusQuery,
    ) -> BoxFuture<'_, Result<Option<ActivationStatus>, PlatformError>>;
}
