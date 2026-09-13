use crate::deployment_operations::{
    budget::{Budget, Charge},
    codec, corrupt, DeploymentOperationAction, DeploymentOperationLimits,
    DeploymentOperationReceipt, Result, MAX_RECEIPT_BYTES,
};
use latent_core::{ArtifactBlobDigest, TenantId};
use latent_manifest::__serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(in crate::deployments) struct StoredReceipt {
    pub sequence: u64,
    pub receipt: DeploymentOperationReceipt,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(in crate::deployments) struct TableData {
    pub format_version: u32,
    pub receipt_slots: usize,
    pub operation_sequence: u64,
    pub receipts: Vec<StoredReceipt>,
}
pub(in crate::deployments) struct OperationTable {
    pub data: TableData,
    pub enabled: bool,
    pub retained_bytes: usize,
    _charge: Charge,
}
impl OperationTable {
    pub fn empty(budget: &Arc<Budget>) -> Result<Arc<Self>> {
        let data = TableData {
            format_version: 1,
            receipt_slots: budget.limits.maximum_receipts,
            operation_sequence: 0,
            receipts: Vec::new(),
        };
        Self::new(data, false, budget)
    }
    pub fn new(data: TableData, enabled: bool, budget: &Arc<Budget>) -> Result<Arc<Self>> {
        validate(&data, enabled, budget.limits)?;
        let retained_bytes = retained(&data)?;
        let charge = budget.reserve(retained_bytes)?;
        Ok(Arc::new(Self {
            data,
            enabled,
            retained_bytes,
            _charge: charge,
        }))
    }
    pub fn reserve_next(&self, budget: &Arc<Budget>) -> Result<Charge> {
        budget.reserve(
            self.retained_bytes
                .saturating_add(
                    self.data
                        .receipt_slots
                        .saturating_mul(std::mem::size_of::<StoredReceipt>()),
                )
                .saturating_add(2 * MAX_RECEIPT_BYTES + 4096),
        )
    }
    pub fn from_reserved(
        data: TableData,
        mut charge: Charge,
        limits: DeploymentOperationLimits,
    ) -> Result<Arc<Self>> {
        validate(&data, true, limits)?;
        let retained_bytes = retained(&data)?;
        charge.shrink(retained_bytes)?;
        Ok(Arc::new(Self {
            data,
            enabled: true,
            retained_bytes,
            _charge: charge,
        }))
    }
    pub fn find(&self, tenant: &TenantId, id: &str) -> Option<&DeploymentOperationReceipt> {
        self.data
            .receipts
            .iter()
            .find(|r| r.receipt.tenant == *tenant && r.receipt.operation_id == id)
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
    pub fn validate_catalog(&self, state: u64, route: u64) -> Result<()> {
        if self
            .data
            .receipts
            .iter()
            .any(|r| r.receipt.state_version > state || r.receipt.route_generation.0 > route)
        {
            return Err(corrupt());
        }
        Ok(())
    }
}
fn retained(data: &TableData) -> Result<usize> {
    let mut n = 1024usize.saturating_add(
        data.receipts
            .capacity()
            .saturating_mul(std::mem::size_of::<StoredReceipt>()),
    );
    for value in &data.receipts {
        n = n
            .saturating_add(value.receipt.canonical_bytes()?.len().saturating_mul(2))
            .saturating_add(512);
    }
    Ok(n)
}
fn validate(data: &TableData, enabled: bool, limits: DeploymentOperationLimits) -> Result<()> {
    if data.format_version != 1
        || data.receipt_slots == 0
        || data.receipt_slots > limits.maximum_receipts
        || data.receipts.len() as u64 != data.operation_sequence.min(data.receipt_slots as u64)
        || enabled != (data.operation_sequence > 0)
        || data.receipts.is_empty() != (data.operation_sequence == 0)
    {
        return Err(corrupt());
    }
    let floor = data
        .operation_sequence
        .checked_sub(data.receipts.len() as u64)
        .and_then(|v| v.checked_add(1))
        .ok_or_else(corrupt)?;
    let mut ids = std::collections::BTreeSet::new();
    let mut previous_state = 0;
    for (i, stored) in data.receipts.iter().enumerate() {
        let r = &stored.receipt;
        if stored.sequence != floor + i as u64
            || r.format_version != 1
            || r.state_version <= previous_state
            || stored.sequence > r.state_version
            || r.expected_state_version.checked_add(1) != Some(r.state_version)
            || r.route_generation.0 == 0
            || r.route_generation.0 > r.state_version
            || !ids.insert((&r.tenant.0, &r.operation_id))
            || codec::receipt_hash(r)? != r.receipt_digest
            || r.component.0.parse::<ArtifactBlobDigest>().is_err()
        {
            return Err(corrupt());
        }
        previous_state = r.state_version;
        crate::deployment_operations::validation::token(&r.tenant.0, 1024)
            .map_err(|_| corrupt())?;
        crate::deployment_operations::validation::token(&r.deployment_id.0, 1024)
            .map_err(|_| corrupt())?;
        crate::deployment_operations::validation::token(&r.operation_id, 128)
            .map_err(|_| corrupt())?;
        r.actor.validate().map_err(|_| corrupt())?;
        match r.action {
            DeploymentOperationAction::Apply
                if r.object_generation == r.route_generation.0
                    && r.expected_generation < r.object_generation => {}
            DeploymentOperationAction::Delete
                if r.expected_generation > 0
                    && r.object_generation == r.expected_generation
                    && r.object_generation < r.route_generation.0 => {}
            _ => return Err(corrupt()),
        }
        r.canonical_bytes().map_err(|_| corrupt())?;
    }
    Ok(())
}
