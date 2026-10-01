//! Reviewed finite tenant ceilings are constraints, never permission grants.
use super::StateOperationConfig;
use latent_core::{PlatformError, TenantId};
use latent_state::tenant::{self, TenantQuota, TenantUsage};
use serde::Deserialize;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TenantQuotaConfig {
    pub tenant: String,
    pub limits: TenantLimitsConfig,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
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
impl TenantLimitsConfig {
    fn usage(&self) -> TenantUsage {
        TenantUsage {
            state_keys: self.state_keys,
            state_bytes: self.state_bytes,
            tombstone_keys: self.tombstone_keys,
            tombstone_bytes: self.tombstone_bytes,
            result_rows: self.result_rows,
            result_bytes: self.result_bytes,
            effect_rows: self.effect_rows,
            effect_bytes: self.effect_bytes,
            payload_bytes: self.payload_bytes,
            recovery_bytes: self.recovery_bytes,
            metadata_rows: self.metadata_rows,
            metadata_bytes: self.metadata_bytes,
        }
    }
}

pub(super) fn derive(
    inputs: &[TenantQuotaConfig],
    operations: &[StateOperationConfig],
) -> Result<Vec<TenantQuota>, PlatformError> {
    if inputs.is_empty() {
        return if operations.is_empty() {
            // The explicit bootstrap profile admits no installed operation.
            Ok(vec![])
        } else {
            Err(invalid())
        };
    }
    if inputs.len() > tenant::MAXIMUM_TENANTS {
        return Err(invalid());
    }
    let mut quotas = Vec::with_capacity(inputs.len());
    for input in inputs {
        let quota = TenantQuota {
            tenant: TenantId(input.tenant.clone()),
            limits: input.limits.usage(),
        };
        quota.validate().map_err(|_| invalid())?;
        let key = tenant::quota_key(&quota.tenant).map_err(|_| invalid())?;
        let minimum =
            tenant::row_charge(&key, &[0; tenant::RECORD_BYTES]).map_err(|_| invalid())?;
        if quota.limits.metadata_bytes < minimum {
            return Err(invalid());
        }
        quotas.push(quota);
    }
    tenant::configuration_digest(&quotas).map_err(|_| invalid())?;
    if operations.iter().any(|operation| {
        !quotas
            .iter()
            .any(|quota| quota.tenant.0 == operation.tenant)
    }) {
        return Err(invalid());
    }
    Ok(quotas)
}
fn invalid() -> PlatformError {
    super::super::invalid("state.tenantQuotas")
}

#[cfg(test)]
pub(super) mod tests {
    use super::*;

    pub(in crate::config::state) fn quota(tenant: &str) -> serde_json::Value {
        serde_json::json!({"tenant":tenant,"limits":{
            "stateKeys":256,"stateBytes":4194304,"tombstoneKeys":256,"tombstoneBytes":4194304,
            "resultRows":128,"resultBytes":16777216,"effectRows":128,"effectBytes":8388608,
            "payloadBytes":4194304,"recoveryBytes":16777216,"metadataRows":1024,"metadataBytes":1048576}})
    }
    #[test]
    fn installed_targets_require_explicit_tenant_limits_while_empty_bootstrap_is_separate() {
        let mut input = super::super::tests::input();
        let config: super::super::StateConfig = serde_json::from_value(input.clone()).unwrap();
        let selected = super::super::derive(&config).unwrap();
        assert_eq!(selected.tenant_quotas[0].tenant, TenantId("a".into()));
        assert_eq!(selected.tenant_quotas[0].limits.state_bytes, 4194304);
        input.as_object_mut().unwrap().remove("tenantQuotas");
        let config = serde_json::from_value(input.clone()).unwrap();
        assert!(super::super::derive(&config).is_err());
        input["operations"] = serde_json::json!([]);
        assert!(
            super::super::derive(&serde_json::from_value(input).unwrap())
                .unwrap()
                .tenant_quotas
                .is_empty()
        );
    }
    #[test]
    fn missing_duplicate_oversized_or_changed_tenant_declarations_refuse_configuration() {
        let mut input = super::super::tests::input();
        input["tenantQuotas"][0]["tenant"] = "another-tenant".into();
        assert!(super::super::derive(&serde_json::from_value(input).unwrap()).is_err());
        let mut input = super::super::tests::input();
        input["tenantQuotas"] = serde_json::json!([quota("a"), quota("a")]);
        assert!(super::super::derive(&serde_json::from_value(input).unwrap()).is_err());
        let mut input = super::super::tests::input();
        input["tenantQuotas"] = (0..=tenant::MAXIMUM_TENANTS)
            .map(|index| quota(&format!("tenant-{index}")))
            .collect::<Vec<_>>()
            .into();
        assert!(super::super::derive(&serde_json::from_value(input).unwrap()).is_err());
        for (name, value) in [
            ("stateKeys", 65537_u64),
            ("stateBytes", 1073741825),
            ("metadataBytes", tenant::RECORD_BYTES as u64),
            ("recoveryBytes", 16777217),
        ] {
            let mut input = super::super::tests::input();
            input["tenantQuotas"][0]["limits"][name] = value.into();
            assert!(super::super::derive(&serde_json::from_value(input).unwrap()).is_err());
        }
    }
    #[test]
    fn tenant_constraints_reject_grants_null_unknown_and_noninteger_limits() {
        for (name, value) in [("grant", true.into()), ("tenant", serde_json::Value::Null)] {
            let mut input = quota("a");
            input[name] = value;
            assert!(serde_json::from_value::<TenantQuotaConfig>(input).is_err());
        }
        for (name, value) in [
            ("grant", true.into()),
            ("stateBytes", true.into()),
            ("stateBytes", serde_json::json!(1.5)),
            ("stateBytes", serde_json::Value::Null),
        ] {
            let mut input = quota("a");
            input["limits"][name] = value;
            assert!(serde_json::from_value::<TenantQuotaConfig>(input).is_err());
        }
    }
}
