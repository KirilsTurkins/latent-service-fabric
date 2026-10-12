//! Explicit abandonment uses the installed offline worker and the original TLS
//! recipient. The old approved-deduplication restore test remains independent.
use super::*;
use latent_effects::recovery_close::{self, ClosePlan, CloseScope};
use latent_state::{
    embedded::ReadView,
    recovery::v1::offline::{PreparedRetainedReconciliation, RetainedReconciliationRequest},
};

fn scope(codecs: &codecs::Codecs) -> CloseScope {
    let original = codecs.authority.scope();
    CloseScope {
        tenant: original.tenant.clone(),
        namespace: original.namespace.clone(),
        incarnation: original.incarnation,
    }
}
pub(super) fn inspect(
    codecs: &codecs::Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<Vec<u8>, StoreError> {
    codecs.check_operator(&request.operator_id)?;
    if request.payload != b"inspect-close" {
        return Err(StoreError::Invalid);
    }
    codecs.validate_view(view)?;
    recovery_close::inspect(
        view,
        scope(codecs),
        request.operator_id.clone(),
        request.operation_id.clone(),
        vec![codecs.authority.link().effect.clone()],
        "abandon restored work after independently observed remote application".into(),
    )?
    .encode()
}
pub(super) fn prepare(
    codecs: &codecs::Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<PreparedRetainedReconciliation, StoreError> {
    accept(codecs, request)?;
    let plan = ClosePlan::decode(&request.payload)?;
    let acknowledgement = codecs
        .close_approval
        .lock()
        .map_err(|_| StoreError::Unavailable)?
        .ok_or(StoreError::Unavailable)?;
    let prepared = recovery_close::prepare(
        view,
        &plan,
        &scope(codecs),
        &request.operator_id,
        &request.operation_id,
        acknowledgement,
        codecs.clock.observe(),
    )?;
    Ok(PreparedRetainedReconciliation {
        batch: prepared.batch,
        receipt: prepared.receipt.encode()?,
        replay: prepared.replay,
    })
}
pub(super) fn accept(
    codecs: &codecs::Codecs,
    request: &RetainedReconciliationRequest,
) -> Result<(), StoreError> {
    let plan = ClosePlan::decode(&request.payload)?;
    let acknowledgement = codecs
        .close_approval
        .lock()
        .map_err(|_| StoreError::Unavailable)?
        .ok_or(StoreError::Unavailable)?;
    if plan.scope != scope(codecs) || plan.operation_id != request.operation_id {
        return Err(StoreError::Conflict);
    }
    codecs.check_review(&request.operator_id, plan.digest()?, acknowledgement)
}
