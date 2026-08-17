//! Invocation admission, quota, overload, and feasibility interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BoxFuture, InvocationPrincipal, Metadata, PlatformError, ResourceBudget, TenantId,
};
use latent_routing::ResolvedRevision;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionRequest {
    pub activation_id: ActivationId,
    pub principal: InvocationPrincipal,
    pub revision: ResolvedRevision,
    pub requested_budget: ResourceBudget,
    pub payload_bytes: u64,
    pub priority: u8,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionPermit {
    pub activation_id: ActivationId,
    pub granted_budget: ResourceBudget,
    pub queue_class: String,
    pub trust_class: String,
    pub obligations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuotaSnapshot {
    pub tenant: TenantId,
    pub maximum_concurrent_activations: u32,
    pub active_activations: u32,
    pub remaining_cpu_fuel: u64,
    pub remaining_memory_bytes: u64,
    pub reset_at_unix_millis: Option<u64>,
}

pub trait AdmissionController: Send + Sync {
    fn admit<'a>(
        &'a self,
        request: AdmissionRequest,
    ) -> BoxFuture<'a, Result<AdmissionPermit, PlatformError>>;
}

pub trait QuotaProvider: Send + Sync {
    fn snapshot<'a>(
        &'a self,
        tenant: &'a TenantId,
    ) -> BoxFuture<'a, Result<QuotaSnapshot, PlatformError>>;
}
