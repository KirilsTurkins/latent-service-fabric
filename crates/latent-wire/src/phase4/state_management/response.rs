use super::{
    c, capacity, contract, expired, Arc, Inner, Instant, NamespaceQuota, OwnedPhase4Response,
    PlatformError, StateManagementReservation,
};
use latent_capabilities::namespace::NamespaceControl;
use latent_policy::capability::OwnedPolicyDecision;
use latent_state::namespace::catalog::{NamespaceOperationReceipt, NamespaceRead};

struct Owner {
    inner: Arc<Inner>,
    permit: Arc<dyn StateManagementReservation>,
    decision: OwnedPolicyDecision,
    read: NamespaceRead,
    receipt: Option<NamespaceOperationReceipt>,
    deadline: Instant,
}
impl super::super::Phase4ResponseOwner for Owner {
    fn reserved_bytes(&self) -> usize {
        self.permit.reserved_response_bytes()
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        if self.inner.services.clock.monotonic_now() >= self.deadline {
            return Err(expired());
        }
        NamespaceControl::with_inspection_retained(
            &self.inner.services.policy,
            &self.decision,
            self.inner.services.namespaces.lifecycle(),
            &self.read,
            self.receipt.as_ref(),
            || self.permit.with_live(publish),
        )
    }
}
pub(super) fn owned(
    inner: Arc<Inner>,
    permit: Arc<dyn StateManagementReservation>,
    decision: OwnedPolicyDecision,
    read: NamespaceRead,
    receipt: Option<NamespaceOperationReceipt>,
    deadline: Instant,
    response: contract::Response,
) -> Result<OwnedPhase4Response, PlatformError> {
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|bytes| bytes.checked_add(16384))
        .ok_or_else(capacity)?;
    if needed > permit.reserved_response_bytes() {
        return Err(capacity());
    }
    let owner = Arc::new(Owner {
        inner,
        permit,
        decision,
        read,
        receipt,
        deadline,
    });
    super::super::Phase4ResponseOwner::with_current(owner.as_ref(), &mut || {})?;
    Ok(OwnedPhase4Response::new(response, owner))
}
pub(super) fn selector(
    record: &latent_state::namespace::NamespaceRecord,
) -> latent_rpc::transaction::v1::NamespaceSelector {
    latent_rpc::transaction::v1::NamespaceSelector {
        tenant: record.tenant.0.clone(),
        namespace: record.id.0.clone(),
        incarnation: record.version.incarnation.to_string(),
    }
}
pub(super) const fn status(value: latent_state::namespace::NamespaceStatus) -> c::NamespaceStatus {
    use latent_state::namespace::NamespaceStatus as S;
    match value {
        S::Active => c::NamespaceStatus::Active,
        S::Quiescing => c::NamespaceStatus::Quiescing,
        S::Retired => c::NamespaceStatus::Retired,
        S::Tombstone => c::NamespaceStatus::Tombstone,
    }
}
pub(super) fn quota(value: NamespaceQuota) -> c::NamespaceQuota {
    c::NamespaceQuota {
        state_keys: value.state_keys,
        state_bytes: value.state_bytes,
        result_rows: value.result_rows,
        result_bytes: value.result_bytes,
        effect_rows: value.effect_rows,
        effect_bytes: value.effect_bytes,
        payload_bytes: value.payload_bytes,
        recovery_bytes: value.recovery_bytes,
    }
}
pub(super) fn hex(bytes: &[u8]) -> String {
    format!("{:x}", latent_core::digest::HexDigest(bytes))
}
