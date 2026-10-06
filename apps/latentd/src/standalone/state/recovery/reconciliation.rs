//! Actual current operator authority is independent from the inspected plan.
use super::{assets, codecs::Codecs, request::Action};
use latent_effects::{
    recovery_close::{self, ClosePlan, CloseReceipt, CloseScope},
    runtime::EffectTimeSource,
};
use latent_state::{
    embedded::{ReadView, StoreError},
    recovery::offline::{
        OfflineRecoveryError, OfflineRecoverySource, PreparedRetainedReconciliation,
        RecoveryCodecs, RetainedReconciliationRequest,
    },
};

fn scope(codecs: &Codecs) -> CloseScope {
    let operation = &codecs.catalog.primary().operation;
    CloseScope {
        tenant: operation.target().tenant.0.clone(),
        namespace: operation.namespace().into(),
        incarnation: operation.incarnation(),
    }
}
fn require_actor(
    codecs: &Codecs,
    request: &RetainedReconciliationRequest,
) -> Result<(), StoreError> {
    if request.operator_id != codecs.authority.actor {
        return Err(StoreError::Unavailable);
    }
    codecs.authority.check("namespace-review-recovery")?;
    codecs.catalog.current()
}
pub(super) fn inspect(
    codecs: &Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<Vec<u8>, StoreError> {
    require_actor(codecs, request)?;
    let Action::InspectCloseEffects {
        operation_id,
        effect_ids,
        reason,
    } = &codecs.action
    else {
        return Err(StoreError::Invalid);
    };
    if operation_id != &request.operation_id || request.payload != b"inspect-effect-close-v1" {
        return Err(StoreError::Invalid);
    }
    codecs.validate_view(view)?;
    recovery_close::inspect(
        view,
        scope(codecs),
        request.operator_id.clone(),
        operation_id.clone(),
        effect_ids.clone(),
        reason.clone(),
    )?
    .encode()
}
pub(super) fn prepare(
    codecs: &Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<PreparedRetainedReconciliation, StoreError> {
    require_actor(codecs, request)?;
    let Action::CloseEffects {
        operation_id,
        plan,
        acknowledgement,
    } = &codecs.action
    else {
        return Err(StoreError::Invalid);
    };
    if operation_id != &request.operation_id || plan.encode()? != request.payload {
        return Err(StoreError::Invalid);
    }
    let acknowledgement = assets::digest_bytes(acknowledgement).map_err(|_| StoreError::Invalid)?;
    let prepared = recovery_close::prepare(
        view,
        plan,
        &scope(codecs),
        &request.operator_id,
        operation_id,
        acknowledgement,
        codecs.authority.clock.observe(),
    )?;
    Ok(PreparedRetainedReconciliation {
        batch: prepared.batch,
        receipt: prepared.receipt.encode()?,
        replay: prepared.replay,
    })
}
pub(super) fn accept(
    codecs: &Codecs,
    request: &RetainedReconciliationRequest,
) -> Result<(), StoreError> {
    require_actor(codecs, request)?;
    let Action::CloseEffects { operation_id, .. } = &codecs.action else {
        return Err(StoreError::Invalid);
    };
    if operation_id != &request.operation_id {
        return Err(StoreError::Invalid);
    }
    Ok(())
}
pub(super) async fn execute(
    source: &OfflineRecoverySource,
    codecs: &Codecs,
) -> Result<serde_json::Value, OfflineRecoveryError> {
    let actor = codecs.authority.actor.clone();
    match &codecs.action {
        Action::InspectCloseEffects { operation_id, .. } => {
            let bytes = source
                .inspect_retained_reconciliation(
                    RetainedReconciliationRequest {
                        operator_id: actor,
                        operation_id: operation_id.clone(),
                        payload: b"inspect-effect-close-v1".to_vec(),
                    },
                    codecs.authority.deadline,
                )?
                .await?;
            let plan = ClosePlan::decode(&bytes).map_err(OfflineRecoveryError::Input)?;
            let digest = plan.digest().map_err(OfflineRecoveryError::Input)?;
            Ok(
                serde_json::json!({"action":"inspect-close-effects","plan":plan,
                "planDigest":format!("sha256:{:x}",latent_core::digest::HexDigest(digest)),
                "proposedOutcome":"closed-without-redrive","recoveryRemainsPaused":true}),
            )
        }
        Action::CloseEffects {
            operation_id, plan, ..
        } => {
            let bytes = source
                .reconcile_retained(
                    RetainedReconciliationRequest {
                        operator_id: actor,
                        operation_id: operation_id.clone(),
                        payload: plan.encode().map_err(OfflineRecoveryError::Input)?,
                    },
                    codecs.authority.deadline,
                )?
                .await?;
            let receipt = CloseReceipt::decode(&bytes).map_err(OfflineRecoveryError::Target)?;
            Ok(
                serde_json::json!({"action":"close-effects","receipt":receipt,
                "recoveryRemainsPaused":true,"providerAcknowledgementInferred":false}),
            )
        }
        _ => Err(OfflineRecoveryError::InvalidConfiguration),
    }
}
