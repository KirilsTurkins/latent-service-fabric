//! Exact reviewed tenant declarations. The runtime converts these constraints
//! into the installed lower-store accounting profile; they confer no grant.
use super::StateOperationConfig;
use latent_core::PlatformError;

configuration_object! {
#[derive(Clone)]
pub struct TenantQuotaConfig {
    pub tenant: String,
    pub limits: TenantLimitsConfig,
}
}

configuration_object! {
#[derive(Clone)]
pub struct TenantLimitsConfig {
    pub state_keys: u64,
    pub state_bytes: u64,
    pub tombstone_keys: u64,
    pub tombstone_bytes: u64,
    pub result_rows: u64,
    pub result_bytes: u64,
    pub effect_rows: u64,
    pub effect_bytes: u64,
    pub payload_bytes: u64,
    pub recovery_bytes: u64,
    pub metadata_rows: u64,
    pub metadata_bytes: u64,
}
}

impl TenantLimitsConfig {
    fn validate(&self, tenant_bytes: usize) -> Result<(), PlatformError> {
        for value in [
            self.state_keys,
            self.tombstone_keys,
            self.result_rows,
            self.effect_rows,
            self.metadata_rows,
        ] {
            if value > 65_536 {
                return Err(invalid());
            }
        }
        for value in [
            self.state_bytes,
            self.tombstone_bytes,
            self.result_bytes,
            self.effect_bytes,
            self.payload_bytes,
            self.recovery_bytes,
            self.metadata_bytes,
        ] {
            if value > 1024 * 1024 * 1024 {
                return Err(invalid());
            }
        }
        // Closed tenant-quota-v1 row: canonical tenant u16 framing, 1024-byte
        // value, family byte and the lower profile's 64-byte index allowance.
        let minimum = b"tenant-quota-v1\0".len() + 2 + tenant_bytes + 1024 + 65;
        if self.metadata_rows == 0
            || self.metadata_bytes < minimum as u64
            || self.recovery_bytes > self.result_bytes
        {
            return Err(invalid());
        }
        Ok(())
    }
}

pub(super) fn derive(
    inputs: &[TenantQuotaConfig],
    operations: &[StateOperationConfig],
) -> Result<Vec<TenantQuotaConfig>, PlatformError> {
    if inputs.len() > 32 || (inputs.is_empty() && !operations.is_empty()) {
        return Err(invalid());
    }
    for (index, input) in inputs.iter().enumerate() {
        super::checked_identity(&input.tenant)?;
        if input.tenant.capacity() > 256
            || inputs[..index]
                .iter()
                .any(|other| other.tenant == input.tenant)
        {
            return Err(invalid());
        }
        input.limits.validate(input.tenant.len())?;
    }
    if operations
        .iter()
        .any(|operation| !inputs.iter().any(|quota| quota.tenant == operation.tenant))
    {
        return Err(invalid());
    }
    Ok(inputs.to_vec())
}

fn invalid() -> PlatformError {
    super::super::invalid("state.tenantQuotas")
}

#[cfg(test)]
pub(super) mod tests;
