//! Installed immutable transaction targets are constraints, never grants.
use latent_core::{
    transaction_contract::identity, PlatformError, PublicationId, ReleaseDigest, TenantId,
};
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StateConfig {
    pub format_version: u32,
    #[serde(default)]
    pub create_if_missing: bool,
    pub configuration_epoch: u64,
    pub clock_checkpoint: PathBuf,
    pub operations: Vec<StateOperationConfig>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StateOperationConfig {
    pub tenant: String,
    pub component_digest: String,
    pub publication: String,
    pub contract: String,
    pub function: String,
    pub deployment: String,
    #[serde(default, deserialize_with = "present_entity")]
    pub route: Option<String>,
    pub binding: String,
    pub companion_digest: String,
    pub incarnation: u64,
    pub result_policy: String,
    pub state_policies: Vec<String>,
    #[serde(default, deserialize_with = "present_entity")]
    pub entity: Option<String>,
}

fn present_entity<'de, D: serde::Deserializer<'de>>(source: D) -> Result<Option<String>, D::Error> {
    String::deserialize(source).map(Some)
}
pub(super) fn present<'de, D: serde::Deserializer<'de>>(
    source: D,
) -> Result<Option<StateConfig>, D::Error> {
    StateConfig::deserialize(source).map(Some)
}

#[derive(Clone)]
pub(crate) struct StateSettings {
    pub create_if_missing: bool,
    pub configuration_epoch: u64,
    pub clock_checkpoint: PathBuf,
    pub operations: Vec<OperationSettings>,
}

#[derive(Clone)]
pub(crate) struct OperationSettings {
    pub tenant: TenantId,
    pub component: ReleaseDigest,
    pub publication: PublicationId,
    pub contract: String,
    pub function: String,
    pub deployment: String,
    pub route: Option<String>,
    pub binding: String,
    pub companion_digest: String,
    pub incarnation: u64,
    pub result_policy: String,
    pub policies: Vec<String>,
    pub entity: Option<String>,
}

pub(crate) fn derive(value: &StateConfig) -> Result<StateSettings, PlatformError> {
    if value.format_version != 1
        || value.configuration_epoch == 0
        || value.operations.len() > 128
        || !value.clock_checkpoint.is_absolute()
        || value.clock_checkpoint.as_os_str().len() > 4096
    {
        return Err(super::invalid("state"));
    }
    let mut operations = Vec::with_capacity(value.operations.len());
    for input in &value.operations {
        for text in [
            &input.tenant,
            &input.contract,
            &input.function,
            &input.deployment,
            &input.binding,
            &input.result_policy,
        ]
        .into_iter()
        .chain(input.entity.iter())
        .chain(input.route.iter())
        {
            checked_identity(text)?;
        }
        checked_digest(&input.component_digest)?;
        checked_digest(&input.companion_digest)?;
        if input.incarnation == 0
            || input.state_policies.is_empty()
            || input.state_policies.len() > 8
        {
            return Err(super::invalid("state.operations"));
        }
        for (index, policy) in input.state_policies.iter().enumerate() {
            checked_identity(policy)?;
            if input.state_policies[..index].contains(policy) {
                return Err(super::invalid("state.policies"));
            }
        }
        let publication = input
            .publication
            .parse()
            .map_err(|_| super::invalid("state.publication"))?;
        if operations.iter().any(|other: &OperationSettings| {
            other.tenant.0 == input.tenant
                && other.publication == publication
                && other.contract == input.contract
                && other.function == input.function
        }) {
            return Err(super::invalid("state.duplicate-operation"));
        }
        operations.push(OperationSettings {
            tenant: TenantId(input.tenant.clone()),
            component: ReleaseDigest(input.component_digest.clone()),
            publication,
            contract: input.contract.clone(),
            function: input.function.clone(),
            deployment: input.deployment.clone(),
            route: input.route.clone(),
            binding: input.binding.clone(),
            companion_digest: input.companion_digest.clone(),
            incarnation: input.incarnation,
            result_policy: input.result_policy.clone(),
            policies: input.state_policies.clone(),
            entity: input.entity.clone(),
        });
    }
    Ok(StateSettings {
        create_if_missing: value.create_if_missing,
        configuration_epoch: value.configuration_epoch,
        clock_checkpoint: value.clock_checkpoint.clone(),
        operations,
    })
}

fn checked_identity(text: &str) -> Result<(), PlatformError> {
    identity(text).map_err(|_| super::invalid("state.identity"))?;
    if text.chars().any(char::is_control) {
        return Err(super::invalid("state.identity"));
    }
    Ok(())
}
fn checked_digest(text: &str) -> Result<(), PlatformError> {
    if text.len() != 71
        || !text.starts_with("sha256:")
        || !text[7..]
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    {
        return Err(super::invalid("state.digest"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn input() -> serde_json::Value {
        serde_json::json!({"formatVersion":1,"configurationEpoch":1,"clockCheckpoint":std::env::temp_dir().join("state-clock.json"),"operations":[{
            "tenant":"a","componentDigest":format!("sha256:{}","a".repeat(64)),
            "publication":format!("publication:sha256:{}","b".repeat(64)),"contract":"test:state/api@1.0.0",
            "function":"save","deployment":"state","binding":"state","companionDigest":format!("sha256:{}","c".repeat(64)),
            "incarnation":1,"resultPolicy":"owner","statePolicies":["state"]}]})
    }
    #[test]
    fn installed_constraints_preserve_exact_unsigned_incarnation_and_do_not_contain_grants() {
        let mut value = input();
        value["operations"][0]["incarnation"] = u64::MAX.into();
        let config: StateConfig = serde_json::from_value(value).unwrap();
        let settings = derive(&config).unwrap();
        assert_eq!(settings.operations[0].incarnation, u64::MAX);
        assert!(!settings.create_if_missing);
        assert_eq!(settings.operations[0].policies, ["state"]);
    }
    #[test]
    fn unsafe_present_values_duplicate_targets_and_permission_fields_refuse() {
        for (name, value) in [
            ("entity", serde_json::Value::Null),
            ("grant", true.into()),
            ("continuityProven", true.into()),
        ] {
            let mut wire = input();
            wire["operations"][0][name] = value;
            assert!(serde_json::from_value::<StateConfig>(wire).is_err());
        }
        let mut wire = input();
        wire["operations"][0]["incarnation"] = 0.into();
        assert!(derive(&serde_json::from_value(wire).unwrap()).is_err());
        let mut config: StateConfig = serde_json::from_value(input()).unwrap();
        config.operations.push(config.operations[0].clone());
        assert!(derive(&config).is_err());
        config.operations.pop();
        config.operations[0].state_policies.push("state".into());
        assert!(derive(&config).is_err());
    }
}
