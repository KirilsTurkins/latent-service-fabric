//! Bounded single-node admission, local quotas, and affine execution permits.
//!
//! Admission never allocates a cell, registers cancellation, fetches an artifact,
//! or spawns a worker. Every successful admission owns one quota reservation.
//! Keep that permit through scheduling, execution, and cleanup; dropping it on
//! any terminal path releases the reservation. All controllers on one node must
//! share the same [`LocalQuotaProvider`], including across route generations.

#![forbid(unsafe_code)]

mod controller;
mod permit;
mod policy;
mod quota;
#[cfg(test)]
mod tests;

pub use controller::{LocalAdmissionController, NodeLoadSnapshot, NodeLoadSource, NodeLoadState};
pub use permit::{AdmissionObligations, AdmissionPermit, ExecutionPermit};
pub use policy::{
    CellClassPolicy, DeadlinePolicy, NodeAdmissionPolicy, OverloadPolicy, QueueClassPolicy,
    QuotaLimits, TenantAdmissionPolicy, TrustClassPolicy,
};
pub use quota::{LocalQuotaProvider, QuotaUsage};

use latent_core::{
    ActivationId, BoxFuture, ErrorDetail, InvocationPrincipal, Metadata, PlatformError,
    PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_routing::ResolvedRevision;

/// Input from an authenticated local adapter. Claims/attributes cannot grant
/// privileges. The payload length must be measured by the adapter, not copied
/// from an untrusted declared content length.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionRequest {
    pub activation_id: ActivationId,
    pub principal: InvocationPrincipal,
    pub revision: ResolvedRevision,
    pub requested_budget: ResourceBudget,
    pub deadline_unix_millis: Option<u64>,
    pub payload_bytes: u64,
    pub priority: u8,
    pub attributes: Metadata,
}

/// Instantaneous reserved capacity, not a billing ledger or replenishing fuel bucket.
/// `active_activations` includes both queued and executing reservations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QuotaSnapshot {
    pub tenant: TenantId,
    pub maximum_concurrent_activations: u32,
    pub active_activations: u32,
    pub queued_activations: u32,
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

/// Trusted-local observation seam. An API adapter must authorize access to a
/// tenant's snapshot; admission rejection details never contain these counters.
pub trait QuotaProvider: Send + Sync {
    fn snapshot<'a>(
        &'a self,
        tenant: &'a TenantId,
    ) -> BoxFuture<'a, Result<QuotaSnapshot, PlatformError>>;
}

pub(crate) fn rejection(
    code: PlatformErrorCode,
    scope: &'static str,
    dimension: &'static str,
    reason: &'static str,
) -> PlatformError {
    PlatformError {
        code,
        message: "invocation does not satisfy local admission policy".to_owned(),
        retryable: matches!(
            code,
            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::Unavailable
        ) || reason == "queue-deadline-infeasible",
        details: vec![ErrorDetail {
            kind: "admission.limit".to_owned(),
            fields: Metadata::from([
                ("scope".to_owned(), scope.to_owned()),
                ("dimension".to_owned(), dimension.to_owned()),
                ("reason".to_owned(), reason.to_owned()),
            ]),
        }],
    }
}

pub(crate) fn valid_identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && !value.chars().any(|character| character.is_control() || character.is_whitespace())
}
