//! Interface-only Rust SDK for LSF clients and guest-facing abstractions.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, ContractId, FunctionId, IdempotencyKey,
    InvocationPrincipal, Metadata, Payload, PlatformError, ReleaseDigest, ResourceBudget,
    RevisionId, RouteGeneration, ServiceId, TenantId, TraceId,
};

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
    ) -> BoxFuture<'a, Result<InvokeResponse, PlatformError>>;

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait GuestContext: Send + Sync {
    fn current(&self) -> Result<GuestInvocationContext, PlatformError>;
}

pub trait ContractCodec<T>: Send + Sync {
    fn media_type(&self) -> &str;
    fn encode(&self, value: &T) -> Result<Vec<u8>, PlatformError>;
    fn decode(&self, bytes: &[u8]) -> Result<T, PlatformError>;
}
