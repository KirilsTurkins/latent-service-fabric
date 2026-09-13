use crate::rollouts::{
    capacity, codec, corrupt, Result, RolloutAction, RolloutId, RolloutLimits,
    RolloutOperationReceipt, RolloutReason, RolloutState, RolloutStatus, MAX_RECEIPT_BYTES,
    MAX_REQUEST_BYTES, MAX_ROW_BYTES,
};
use latent_core::{ArtifactBlobDigest, RouteGeneration, TenantId};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    __serde_json as json, DeploymentManifest, JsonManifestCodec, ManifestCodec,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

pub(in crate::deployments) struct MetadataBudget {
    pub maximum: usize,
    used: AtomicUsize,
}
impl MetadataBudget {
    pub fn new(maximum: usize) -> Arc<Self> {
        Arc::new(Self {
            maximum,
            used: AtomicUsize::new(0),
        })
    }
    pub fn reserve(self: &Arc<Self>, bytes: usize) -> Result<Charge> {
        self.used
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_add(bytes).filter(|n| *n <= self.maximum)
            })
            .map_err(|_| capacity())?;
        Ok(Charge {
            budget: Arc::clone(self),
            bytes,
        })
    }
}
pub(in crate::deployments) struct Charge {
    budget: Arc<MetadataBudget>,
    bytes: usize,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.budget.used.fetch_sub(self.bytes, Ordering::AcqRel);
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub(in crate::deployments) struct CohortMember {
    pub id: String,
    pub generation: u64,
    pub manifest_digest: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub(in crate::deployments) struct StoredRollout {
    pub status: RolloutStatus,
    pub base_manifest: String,
    pub candidate_manifest: String,
    pub cohort: Vec<CohortMember>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub(in crate::deployments) struct StoredReceipt {
    pub sequence: u64,
    pub receipt: RolloutOperationReceipt,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub(in crate::deployments) struct TableData {
    pub format_version: u32,
    pub receipt_slots: usize,
    pub operation_sequence: u64,
    pub rows: Vec<StoredRollout>,
    pub receipts: Vec<StoredReceipt>,
}
pub(in crate::deployments) struct RolloutTable {
    pub data: TableData,
    pub enabled: bool,
    pub retained_bytes: usize,
    _charge: Charge,
}
impl RolloutTable {
    pub fn empty(budget: &Arc<MetadataBudget>, limits: RolloutLimits) -> Result<Arc<Self>> {
        let data = TableData {
            format_version: 1,
            receipt_slots: limits.maximum_receipts,
            operation_sequence: 0,
            rows: Vec::new(),
            receipts: Vec::new(),
        };
        Self::new(data, false, budget, limits)
    }
    pub fn new(
        data: TableData,
        enabled: bool,
        budget: &Arc<MetadataBudget>,
        limits: RolloutLimits,
    ) -> Result<Arc<Self>> {
        validate(&data, limits)?;
        let bytes = retained_bytes(&data);
        let charge = budget.reserve(bytes)?;
        Ok(Arc::new(Self {
            data,
            enabled,
            retained_bytes: bytes,
            _charge: charge,
        }))
    }
    pub fn reserve_next(&self, budget: &Arc<MetadataBudget>) -> Result<Charge> {
        budget.reserve(
            self.retained_bytes
                .saturating_add(2 * MAX_ROW_BYTES)
                .saturating_add(2 * MAX_RECEIPT_BYTES)
                .saturating_add(8192),
        )
    }
    pub fn from_reserved(
        data: TableData,
        reservation: Charge,
        limits: RolloutLimits,
    ) -> Result<Arc<Self>> {
        validate(&data, limits)?;
        let bytes = retained_bytes(&data);
        if bytes > reservation.bytes {
            return Err(capacity());
        }
        let mut charge = reservation;
        charge
            .budget
            .used
            .fetch_sub(charge.bytes - bytes, Ordering::AcqRel);
        charge.bytes = bytes;
        Ok(Arc::new(Self {
            data,
            enabled: true,
            retained_bytes: bytes,
            _charge: charge,
        }))
    }
    pub fn row(&self, tenant: &TenantId, id: &RolloutId) -> Option<&StoredRollout> {
        self.data
            .rows
            .iter()
            .find(|r| r.status.tenant == *tenant && r.status.id == *id)
    }
    pub fn receipt(
        &self,
        tenant: &TenantId,
        id: &RolloutId,
        operation: &str,
    ) -> Option<&RolloutOperationReceipt> {
        self.data
            .receipts
            .iter()
            .find(|r| {
                r.receipt.tenant == *tenant
                    && r.receipt.rollout_id == *id
                    && r.receipt.operation_id == operation
            })
            .map(|r| &r.receipt)
    }
    pub fn floor(&self) -> u64 {
        self.data
            .receipts
            .first()
            .map_or(self.data.operation_sequence.saturating_add(1), |r| {
                r.sequence
            })
    }
    pub fn validate_catalog(&self, transaction: u64, generation: RouteGeneration) -> Result<()> {
        if self.enabled && (self.data.rows.is_empty() || self.data.operation_sequence == 0) {
            return Err(corrupt());
        }
        if self.data.rows.iter().any(|row| {
            row.status.state_version > transaction || row.status.route_generation > generation
        }) || self.data.receipts.iter().any(|stored| {
            stored.receipt.state_version > transaction
                || stored.receipt.route_generation > generation
        }) {
            return Err(corrupt());
        }
        Ok(())
    }
}
pub(in crate::deployments) fn manifest(value: &DeploymentManifest) -> Result<String> {
    let bytes = JsonManifestCodec::default()
        .encode_deployment(value)
        .map_err(|_| corrupt())?;
    if bytes.len() > MAX_REQUEST_BYTES {
        return Err(capacity());
    }
    String::from_utf8(bytes).map_err(|_| corrupt())
}
pub(in crate::deployments) fn decode_manifest(value: &str) -> Result<DeploymentManifest> {
    if value.len() > MAX_REQUEST_BYTES {
        return Err(capacity());
    }
    JsonManifestCodec::default()
        .decode_deployment(value.as_bytes())
        .map_err(|_| corrupt())
}
pub(in crate::deployments) fn retained_bytes(data: &TableData) -> usize {
    // Fixed node/allocator margin plus canonical bytes upper-bounds each closed
    // normalized row/receipt's string allocations and collection slots.
    let mut n = 4096usize
        .saturating_add(
            data.rows
                .capacity()
                .saturating_mul(std::mem::size_of::<StoredRollout>()),
        )
        .saturating_add(
            data.receipts
                .capacity()
                .saturating_mul(std::mem::size_of::<StoredReceipt>()),
        );
    for row in &data.rows {
        n = n
            .saturating_add(
                codec::encode(row, MAX_ROW_BYTES).map_or(usize::MAX, |b| b.len().saturating_mul(2)),
            )
            .saturating_add(2048);
    }
    for receipt in &data.receipts {
        n = n
            .saturating_add(
                receipt
                    .receipt
                    .canonical_bytes()
                    .map_or(usize::MAX, |b| b.len().saturating_mul(2)),
            )
            .saturating_add(512);
    }
    n
}
pub(in crate::deployments) fn receipt_hash(
    receipt: &RolloutOperationReceipt,
) -> Result<ArtifactBlobDigest> {
    let mut value = json::to_value(receipt).map_err(|_| corrupt())?;
    value
        .as_object_mut()
        .ok_or_else(corrupt)?
        .remove("receiptDigest");
    Ok(codec::hash(&codec::encode(&value, MAX_RECEIPT_BYTES)?))
}
pub(in crate::deployments) fn plan_hash(row: &StoredRollout) -> Result<ArtifactBlobDigest> {
    let s = &row.status;
    let mut value = json::json!({
        "version":1,"tenant":s.tenant.0,"rollout":s.id.0,
        "base":row.base_manifest,"candidate":row.candidate_manifest,
        "weights":s.candidate_weights,"basePackage":s.base.package.as_ref().map(latent_core::PackageDigest::as_str),
        "candidatePackage":s.candidate.package.as_ref().map(latent_core::PackageDigest::as_str)
    });
    if let Some(policy) = s.canary_policy {
        value["canaryPolicy"] = json::to_value(policy).map_err(|_| corrupt())?;
    }
    if let Some(target) = &s.rollback_target {
        value["rollbackTarget"] = json::to_value(target).map_err(|_| corrupt())?;
    }
    Ok(codec::hash(&codec::encode(&value, MAX_ROW_BYTES)?))
}
#[expect(
    clippy::too_many_lines,
    reason = "one bounded durable table validation checks row, receipt-ring, and cross-record associations together"
)]
fn validate(data: &TableData, limits: RolloutLimits) -> Result<()> {
    if data.format_version != 1
        || data.receipt_slots == 0
        || data.receipt_slots > limits.maximum_receipts
        || data.rows.len() > limits.maximum_rows
        || data.receipts.len() > data.receipt_slots
    {
        return Err(corrupt());
    }
    let mut ids = std::collections::BTreeSet::new();
    let mut active = std::collections::BTreeSet::new();
    let mut previous_row = None;
    for row in &data.rows {
        let s = &row.status;
        crate::rollouts::validation::token(&s.id.0, 128)?;
        crate::rollouts::validation::token(&s.tenant.0, 256)?;
        crate::rollouts::validation::token(&s.service.0, 256)?;
        crate::rollouts::validation::weights(&s.candidate_weights, limits.maximum_stages)?;
        if let Some(policy) = s.canary_policy {
            policy.validate().map_err(|_| corrupt())?;
            if s.candidate_weights.len() < 2 {
                return Err(corrupt());
            }
        }
        if s.revision == 0
            || s.state_version == 0
            || s.current_step as usize >= s.candidate_weights.len()
            || s.base.component == s.candidate.component
            || !ids.insert((s.tenant.clone(), s.id.clone()))
            || row.cohort.is_empty()
            || row.cohort.len() > 2
            || s.objects.len() > 2
            || s.previous_route_generation > s.route_generation
            || s.route_generation.0 > s.state_version
            || s.revision > data.operation_sequence
            || s.created_at_unix_millis > s.updated_at_unix_millis
            || s.base.deployment_id == s.candidate.deployment_id
            || s.state == RolloutState::Conflicted
            || previous_row.is_some_and(|key| key >= (&s.tenant, &s.id))
        {
            return Err(corrupt());
        }
        previous_row = Some((&s.tenant, &s.id));
        let at_end = s.candidate_weights[s.current_step as usize] == 10000;
        if (s.state != RolloutState::RolledBack && (s.state == RolloutState::Completed) != at_end)
            || !match s.state {
                RolloutState::Running => s.reason == RolloutReason::StageApplied,
                RolloutState::Completed => s.reason == RolloutReason::Completed,
                RolloutState::RolledBack => s.reason == RolloutReason::RollbackApplied,
                RolloutState::Paused | RolloutState::Aborted => {
                    s.reason == RolloutReason::OperatorRequested
                }
                RolloutState::Conflicted => false,
            }
        {
            return Err(corrupt());
        }
        if let Some(target) = &s.rollback_target {
            target.validate().map_err(|_| corrupt())?;
            if target.historical_route_generation >= s.route_generation
                || target.manifest_digest != codec::hash(row.base_manifest.as_bytes())
            {
                return Err(corrupt());
            }
        }
        if s.state == RolloutState::RolledBack {
            let target = s.rollback_target.as_ref().ok_or_else(corrupt)?;
            if row.cohort.len() != 1
                || row.cohort[0].id != s.base.deployment_id.0
                || row.cohort[0].manifest_digest != target.manifest_digest.as_str()
                || row.cohort[0].generation != s.route_generation.0
                || s.objects.len() != 1
                || s.objects[0].deployment_id != s.base.deployment_id
                || s.objects[0].generation != s.route_generation.0
            {
                return Err(corrupt());
            }
        }
        let mut last = None;
        for member in &row.cohort {
            if member.generation == 0
                || member.generation > s.route_generation.0
                || last.is_some_and(|id| id >= &member.id)
                || (member.id != s.base.deployment_id.0 && member.id != s.candidate.deployment_id.0)
                || member
                    .manifest_digest
                    .parse::<ArtifactBlobDigest>()
                    .is_err()
            {
                return Err(corrupt());
            }
            last = Some(&member.id);
        }
        let mut object_ids = std::collections::BTreeSet::new();
        for object in &s.objects {
            if object.generation == 0
                || object.generation > s.route_generation.0
                || (object.deployment_id != s.base.deployment_id
                    && object.deployment_id != s.candidate.deployment_id)
                || !object_ids.insert(&object.deployment_id)
            {
                return Err(corrupt());
            }
        }
        if matches!(
            s.state,
            RolloutState::Running | RolloutState::Paused | RolloutState::Conflicted
        ) && !active.insert((s.tenant.clone(), s.service.clone()))
        {
            return Err(corrupt());
        }
        let base = decode_manifest(&row.base_manifest)?;
        let candidate = decode_manifest(&row.candidate_manifest)?;
        if base.id != s.base.deployment_id
            || base.release != s.base.component
            || candidate.id != s.candidate.deployment_id
            || candidate.release != s.candidate.component
            || base.metadata.tenant.as_ref() != Some(&s.tenant)
            || candidate.metadata.tenant.as_ref() != Some(&s.tenant)
            || base.service != s.service
            || candidate.service != s.service
            || base.metadata.namespace != candidate.metadata.namespace
            || candidate.route_weight != s.candidate_weights[0]
            || plan_hash(row)? != s.plan_digest
        {
            return Err(corrupt());
        }
        codec::encode(row, MAX_ROW_BYTES)?;
    }
    if active.len() > limits.maximum_active {
        return Err(capacity());
    }
    let first_sequence = data
        .operation_sequence
        .checked_sub(data.receipts.len() as u64)
        .ok_or_else(corrupt)?
        .checked_add(1)
        .ok_or_else(corrupt)?;
    let mut previous = 0;
    let mut previous_transaction = 0;
    let mut operations = std::collections::BTreeSet::new();
    for (index, stored) in data.receipts.iter().enumerate() {
        let r = &stored.receipt;
        if stored.sequence <= previous
            || stored.sequence > data.operation_sequence
            || r.revision != r.expected_revision.checked_add(1).ok_or_else(corrupt)?
            || r.receipt_digest != receipt_hash(r)?
            || !ids.contains(&(r.tenant.clone(), r.rollout_id.clone()))
            || !operations.insert((
                r.tenant.clone(),
                r.rollout_id.clone(),
                r.operation_id.clone(),
            ))
            || stored.sequence != first_sequence + index as u64
            || r.state_version <= previous_transaction
            || r.route_generation.0 > r.state_version
        {
            return Err(corrupt());
        }
        previous = stored.sequence;
        previous_transaction = r.state_version;
        let row = data
            .rows
            .iter()
            .find(|row| row.status.tenant == r.tenant && row.status.id == r.rollout_id)
            .ok_or_else(corrupt)?;
        if r.revision > row.status.revision
            || r.state_version > row.status.state_version
            || r.plan_digest != row.status.plan_digest
            || r.step as usize >= row.status.candidate_weights.len()
            || !match r.action {
                RolloutAction::Start => {
                    r.expected_revision == 0
                        && r.step == 0
                        && matches!(r.state, RolloutState::Running | RolloutState::Completed)
                }
                RolloutAction::Advance | RolloutAction::Promote => {
                    r.expected_revision > 0
                        && r.step > 0
                        && matches!(r.state, RolloutState::Running | RolloutState::Completed)
                }
                RolloutAction::Pause => r.expected_revision > 0 && r.state == RolloutState::Paused,
                RolloutAction::Resume => {
                    r.expected_revision > 0 && r.state == RolloutState::Running
                }
                RolloutAction::Abort => r.expected_revision > 0 && r.state == RolloutState::Aborted,
                RolloutAction::Rollback => {
                    r.expected_revision > 0
                        && r.state == RolloutState::RolledBack
                        && r.reason == RolloutReason::RollbackApplied
                        && row.status.state == RolloutState::RolledBack
                        && r.revision == row.status.revision
                        && r.step == row.status.current_step
                }
            }
        {
            return Err(corrupt());
        }
        match (
            r.action,
            row.status.canary_policy.as_ref(),
            r.canary_decision.as_ref(),
        ) {
            (RolloutAction::Promote, Some(policy), Some(decision)) => decision.validate(policy)?,
            (RolloutAction::Promote, _, _) | (RolloutAction::Advance, Some(_), _) => {
                return Err(corrupt())
            }
            (_, _, Some(_)) => return Err(corrupt()),
            (_, _, None) => {}
        }
        match (
            r.action,
            r.rollback_target.as_ref(),
            row.status.rollback_target.as_ref(),
        ) {
            (RolloutAction::Rollback, Some(actual), Some(expected)) if actual == expected => {}
            (RolloutAction::Rollback, _, _) | (_, Some(_), _) => return Err(corrupt()),
            (RolloutAction::Start, None, Some(target)) => {
                if target.historical_route_generation.0.checked_add(1) != Some(r.route_generation.0)
                {
                    return Err(corrupt());
                }
            }
            (_, None, _) => {}
        }
        r.actor.validate()?;
        crate::rollouts::validation::token(&r.operation_id, 128)?;
        r.canonical_bytes()?;
    }
    if data
        .receipts
        .last()
        .is_some_and(|r| r.sequence != data.operation_sequence)
        || data.receipts.is_empty() && data.operation_sequence != 0
    {
        return Err(corrupt());
    }
    Ok(())
}
