use latent_core::BoxFuture;

use super::{ProviderReconciliationOutcome, ProviderReconciliationRequest};
use crate::authority::{AuthorityError, DispatchGrant, DispatchProfile, EffectTime};
use crate::dispatch::{AttemptIdentity, AttemptReceipt, RetryProof};
use crate::payload::PayloadRecord;

pub struct AdapterOutcome {
    pub receipt: AttemptReceipt,
    /// A concrete reviewed adapter supplies affirmative nonexecution or its
    /// exact qualified dedup/reconciliation evidence; no generic timeout proof.
    pub retry: Option<(RetryProof, u64)>,
}

/// Installed exact retained decoder/provider profile. This is a trusted host
/// port, never a guest-provided adapter or generic idempotency grant.
pub trait DeferredEffectAdapter: Send + Sync {
    fn profile(&self) -> &DispatchProfile;

    /// Short synchronous admission under the current effect fence. No I/O or
    /// credential lookup here. Accepted work owns all bounded request/response
    /// buffers and provider permits. Its first poll starts I/O only after the
    /// dispatcher persists a send marker. Before first poll, dropping the owned
    /// future proves this operation never sent and releases its admission.
    /// Once polled, the fixed worker drives it through actual physical cleanup;
    /// deadline/cancellation cannot make early future completion safe.
    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError>;

    /// Admit a positive-receipt status lookup through the same protected
    /// provider, current profile and original sealed grant. First poll performs
    /// lookup only, never another send. The fixed owner drives accepted work
    /// through actual physical cleanup even after its management waiter drops.
    fn accept_reconciliation(
        &self,
        _grant: DispatchGrant,
        _request: ProviderReconciliationRequest,
    ) -> Result<BoxFuture<'static, ProviderReconciliationOutcome>, AuthorityError> {
        Err(AuthorityError::UnsupportedFormat)
    }

    /// Trusted concrete qualification for a manual redrive of the exact original
    /// payload/profile. This short callback performs no I/O. Unknown status,
    /// administrator text or an idempotency key cannot manufacture this proof.
    fn qualify_redrive(
        &self,
        _request: &ProviderReconciliationRequest,
        _time: EffectTime,
    ) -> Result<RetryProof, AuthorityError> {
        Err(AuthorityError::PolicyBlocked)
    }
}

/// Supplied by the protected node clock/checkpoint owner. A wall clock alone
/// cannot manufacture continuity or approve an older restored database.
pub trait EffectTimeSource: Send + Sync {
    fn observe(&self) -> EffectTime;
}

impl<F: Fn() -> EffectTime + Send + Sync> EffectTimeSource for F {
    fn observe(&self) -> EffectTime {
        self()
    }
}
