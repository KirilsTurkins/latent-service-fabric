//! Explicit restored-effect abandonment. Never provider acknowledgement or retry.
use crate::{
    authority::EffectTime,
    dispatch::{Disposition, EffectRecord},
    dispatch_store::{effect_row_key, storage_error, DispatchCatalog, DueRecord},
    effect_identity,
};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    recovery::{resume::NamespaceRecoveryView, RecoveryGuard, RecoveryStatus},
    tenant::{prepare_update, row_charge, TenantDelta, TenantUsage},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

mod model;
mod preparation;
pub use preparation::prepare;

pub const RECEIPT_PREFIX: &[u8] = b"effect-recovery-close-v1\0";
pub const FORMAT: &str = "lsf.effect-recovery-close.v1";
pub const PLAN_BYTES: usize = 12_288;
pub const EFFECTS: usize = 16;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CloseScope {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CloseSelection {
    pub effect_id: String,
    pub original_digest: [u8; 32],
    pub payload_digest: [u8; 32],
    pub history_digest: [u8; 32],
    pub original_disposition: Disposition,
    pub original_clock_millis: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClosePlan {
    pub schema_version: String,
    pub operator_id: String,
    pub operation_id: String,
    pub scope: CloseScope,
    pub expected_view: Vec<u8>,
    pub expected_guard: Vec<u8>,
    pub loss_window_digest: [u8; 32],
    pub reason: String,
    pub effects: Vec<CloseSelection>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CloseReceipt {
    pub schema_version: String,
    pub outcome: String,
    pub plan: ClosePlan,
    pub acknowledgement: [u8; 32],
    pub observed_at_millis: u64,
}
pub struct PreparedClose {
    pub batch: AtomicBatch,
    pub receipt: CloseReceipt,
    pub replay: bool,
}
fn eligible(disposition: Disposition) -> bool {
    matches!(
        disposition,
        Disposition::Pending
            | Disposition::Uncertain
            | Disposition::KnownFailed
            | Disposition::RetryScheduled
            | Disposition::PolicyBlocked
    )
}
fn identity(value: &str) -> Result<(), StoreError> {
    latent_core::transaction_contract::identity(value).map_err(|_| StoreError::Invalid)?;
    if value.chars().any(char::is_control) {
        return Err(StoreError::Invalid);
    }
    Ok(())
}
fn receipt_key(digest: [u8; 32]) -> RowKey {
    let mut key = RECEIPT_PREFIX.to_vec();
    key.extend_from_slice(&digest);
    RowKey {
        family: Family::Maintenance,
        key,
    }
}
/// Read the actual paused restored view and original records. No write/provider
/// operation is performed, and plan bytes themselves grant no authority.
pub fn inspect(
    view: &ReadView,
    scope: CloseScope,
    operator_id: String,
    operation_id: String,
    mut effect_ids: Vec<String>,
    reason: String,
) -> Result<ClosePlan, StoreError> {
    scope.validate()?;
    let observed = NamespaceRecoveryView::capture(
        view,
        &TenantId(scope.tenant.clone()),
        &StateNamespaceId(scope.namespace.clone()),
    )?;
    if observed.namespace.version.incarnation != scope.incarnation {
        return Err(StoreError::Conflict);
    }
    if observed.namespace.status != latent_state::namespace::NamespaceStatus::Quiescing
        || observed.history.status
            != latent_state::namespace::history::HistoryStatus::ReconciliationRequired
    {
        return Err(StoreError::Unavailable);
    }
    let guard = observed.guard.clone().ok_or(StoreError::Unavailable)?;
    if guard.status() != RecoveryStatus::ReconciliationRequired {
        return Err(StoreError::Unavailable);
    }
    if effect_ids.is_empty() || effect_ids.len() > EFFECTS {
        return Err(StoreError::Capacity);
    }
    effect_ids.sort();
    let mut effects = Vec::with_capacity(effect_ids.len());
    for effect_id in effect_ids {
        let raw = view
            .get(&effect_row_key(&effect_id)?)?
            .ok_or(StoreError::Conflict)?;
        let record = EffectRecord::decode(&raw).map_err(storage_error)?;
        scope.accepts(&record)?;
        if !eligible(record.disposition()) {
            return Err(StoreError::Unavailable);
        }
        // Reuse the complete selected payload/history/due/owner closure proof.
        DispatchCatalog::retention_rows(view, &effect_id)?;
        let (payload_digest, history_digest) = retained_digests(view, &effect_id)?;
        effects.push(CloseSelection {
            effect_id,
            original_digest: Sha256::digest(raw).into(),
            payload_digest,
            history_digest,
            original_disposition: record.disposition(),
            original_clock_millis: record.clock_floor(),
        });
    }
    let plan = ClosePlan {
        schema_version: FORMAT.into(),
        operator_id,
        operation_id,
        scope,
        expected_view: observed.view_token()?,
        expected_guard: guard.encode()?,
        loss_window_digest: guard.window_digest(),
        reason,
        effects,
    };
    plan.validate()?;
    Ok(plan)
}
pub fn validate_record_link(view: &ReadView, record: &EffectRecord) -> Result<(), StoreError> {
    let Some(digest) = record.recovery_close_digest() else {
        return Ok(());
    };
    let key = receipt_key(digest);
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    let receipt = CloseReceipt::validate_row(&key, &bytes)?;
    let authority = record.authority().map_err(storage_error)?;
    let selected = receipt
        .plan
        .effects
        .iter()
        .find(|row| row.effect_id == authority.link().effect)
        .ok_or(StoreError::Corrupt)?;
    receipt.plan.scope.accepts(record)?;
    let (payload_digest, history_digest) = retained_digests(view, &selected.effect_id)?;
    if record.disposition() != Disposition::DeadLettered
        || payload_digest != selected.payload_digest
        || history_digest != selected.history_digest
        || record.clock_floor() != receipt.observed_at_millis
        || record
            .recovery_original_digest(
                selected.original_disposition,
                selected.original_clock_millis,
            )
            .map_err(storage_error)?
            != selected.original_digest
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
fn retained_digests(view: &ReadView, effect: &str) -> Result<([u8; 32], [u8; 32]), StoreError> {
    let payload = view
        .get(&crate::dispatch_store::effect_payload_key(effect)?)?
        .ok_or(StoreError::Corrupt)?;
    let history = DispatchCatalog::history_page(view, effect, None, 128, 1024 * 1024)?;
    if history.resume.is_some() || history.pending_slots != 0 {
        return Err(StoreError::Capacity);
    }
    let mut digest = Sha256::new();
    digest.update(b"lsf.effect.recovery-close-history.v1\0");
    for row in history.rows {
        let key = row.key()?;
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        digest.update((key.key.len() as u64).to_le_bytes());
        digest.update(&key.key);
        digest.update((bytes.len() as u64).to_le_bytes());
        digest.update(bytes);
    }
    Ok((Sha256::digest(payload).into(), digest.finalize().into()))
}
pub fn validate_receipt_links(view: &ReadView, receipt: &CloseReceipt) -> Result<(), StoreError> {
    for selected in &receipt.plan.effects {
        let bytes = view
            .get(&effect_row_key(&selected.effect_id)?)?
            .ok_or(StoreError::Corrupt)?;
        let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
        if record.recovery_close_digest() != Some(receipt.plan.receipt_digest()?) {
            return Err(StoreError::Corrupt);
        }
        validate_record_link(view, &record)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
