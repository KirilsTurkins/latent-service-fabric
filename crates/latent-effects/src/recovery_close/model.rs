use super::{
    effect_identity, eligible, identity, receipt_key, storage_error, ClosePlan, CloseReceipt,
    CloseScope, EffectRecord, RecoveryGuard, RecoveryStatus, RowKey, StoreError, EFFECTS, FORMAT,
    PLAN_BYTES,
};
use sha2::{Digest, Sha256};

impl CloseScope {
    pub(super) fn validate(&self) -> Result<(), StoreError> {
        identity(&self.tenant)?;
        identity(&self.namespace)?;
        if self.incarnation == 0 {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
    pub(super) fn accepts(&self, record: &EffectRecord) -> Result<(), StoreError> {
        let authority = record.authority().map_err(storage_error)?;
        let scope = authority.scope();
        if scope.tenant != self.tenant
            || scope.namespace != self.namespace
            || scope.incarnation != self.incarnation
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
}
impl ClosePlan {
    pub(super) fn validate(&self) -> Result<(), StoreError> {
        self.scope.validate()?;
        identity(&self.operator_id)?;
        identity(&self.operation_id)?;
        let guard = RecoveryGuard::decode(&self.expected_guard)?;
        if self.schema_version != FORMAT
            || guard.status() != RecoveryStatus::ReconciliationRequired
            || guard.window_digest() != self.loss_window_digest
            || self.expected_view.len() != 67
            || !self.expected_view.starts_with(b"NV\x02")
            || self.reason.is_empty()
            || self.reason.len() > 128
            || self.reason.chars().any(char::is_control)
            || self.effects.is_empty()
            || self.effects.len() > EFFECTS
        {
            return Err(StoreError::Invalid);
        }
        for (index, selected) in self.effects.iter().enumerate() {
            effect_identity::parse(&selected.effect_id).map_err(|_| StoreError::Invalid)?;
            if selected.original_digest == [0; 32]
                || selected.payload_digest == [0; 32]
                || selected.history_digest == [0; 32]
                || !eligible(selected.original_disposition)
                || selected.original_clock_millis == 0
                || (index > 0 && self.effects[index - 1].effect_id >= selected.effect_id)
            {
                return Err(StoreError::Invalid);
            }
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > PLAN_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.is_empty() || bytes.len() > PLAN_BYTES {
            return Err(StoreError::Capacity);
        }
        let plan: Self = serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt)?;
        if plan.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(plan)
    }
    pub fn digest(&self) -> Result<[u8; 32], StoreError> {
        let mut hash = Sha256::new();
        hash.update(b"lsf.effect.recovery-close-plan.v1\0");
        hash.update(self.encode()?);
        Ok(hash.finalize().into())
    }
    pub(super) fn receipt_digest(&self) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"lsf.effect.recovery-close-operation.v1\0");
        for field in [
            &self.scope.tenant,
            &self.scope.namespace,
            &self.operator_id,
            &self.operation_id,
        ] {
            hash.update((field.len() as u64).to_le_bytes());
            hash.update(field.as_bytes());
        }
        hash.update(self.scope.incarnation.to_le_bytes());
        Ok(hash.finalize().into())
    }
    pub fn receipt_key(&self) -> Result<RowKey, StoreError> {
        Ok(receipt_key(self.receipt_digest()?))
    }
}
impl CloseReceipt {
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.plan.validate()?;
        if self.schema_version != FORMAT
            || self.outcome != "closed-without-redrive"
            || self.acknowledgement != self.plan.digest()?
            || self.observed_at_millis == 0
            || self
                .plan
                .effects
                .iter()
                .any(|row| row.original_clock_millis > self.observed_at_millis)
        {
            return Err(StoreError::Invalid);
        }
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > 16_384 {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.is_empty() || bytes.len() > 16_384 {
            return Err(StoreError::Capacity);
        }
        let receipt: Self = serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt)?;
        if receipt.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(receipt)
    }
    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<Self, StoreError> {
        let receipt = Self::decode(bytes)?;
        if *key != receipt.plan.receipt_key()? {
            return Err(StoreError::Corrupt);
        }
        Ok(receipt)
    }
}
