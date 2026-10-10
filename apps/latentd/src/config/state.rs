//! Installed immutable transaction targets are constraints, never grants.
use latent_core::{
    transaction_contract::identity, PlatformError, PublicationId, ReleaseDigest, TenantId,
};
use serde::Deserialize;
use std::path::{Path, PathBuf};
use std::time::Duration;

// The coherent logical registry owns bounded 2 MiB pages, point decoders and
// the fixed 32-tenant census. This same declared native Work is prepaid before
// any initializer allocation; it is not a guest-memory allowance.
pub(crate) const STARTUP_VALIDATOR_BYTES: u64 = 8 * 1024 * 1024;
// Exact quota/identity/path captures and the early empty authority shell are
// prepaid before the initializer can reserve its separate native buffers.
pub(crate) const STARTUP_APPLICATION_BYTES: u64 = 64 * 1024;
// Existing fixed authority rule ceiling; its actual resident map is charged
// separately from the application shell, before either owner allocates.
pub(crate) const EFFECT_AUTHORITY_MAXIMUM_RULES: usize = 128;

// Operator objects retain streaming duplicate/unknown-field rejection and
// refuse Serde's positional struct-array representation at every owner layer.
macro_rules! configuration_object {
    ($(#[$meta:meta])* $visibility:vis struct $name:ident { $( $(#[$field_meta:meta])* $field_visibility:vis $field:ident: $kind:ty, )* }) => {
        $(#[$meta])* $visibility struct $name { $( $field_visibility $field: $kind, )* }
        impl<'de> serde::Deserialize<'de> for $name {
            fn deserialize<D: serde::Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
                struct ObjectVisitor;
                impl<'de> serde::de::Visitor<'de> for ObjectVisitor {
                    type Value = $name;
                    fn expecting(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                        output.write_str("a state configuration object")
                    }
                    fn visit_map<M: serde::de::MapAccess<'de>>(self, map: M) -> Result<Self::Value, M::Error> {
                        #[derive(serde::Deserialize)]
                        #[serde(rename_all = "camelCase", deny_unknown_fields)]
                        struct Fields { $( $(#[$field_meta])* $field: $kind, )* }
                        let fields: Fields = serde::Deserialize::deserialize(serde::de::value::MapAccessDeserializer::new(map))?;
                        Ok($name { $( $field: fields.$field, )* })
                    }
                }
                decoder.deserialize_map(ObjectVisitor)
            }
        }
    };
}
mod effects;
pub use effects::DeferredHttpConfig;
mod owners;
pub use owners::{
    DispatcherLimitsConfig, NativeLimitsConfig, NativePartitionConfig, StorageLimitsConfig,
    StorageRecoveryConfig, StorageWorkerConfig,
};
mod tenant;
pub use tenant::{TenantLimitsConfig, TenantQuotaConfig};

configuration_object! {
#[derive(Clone)]
pub struct StateConfig {
    pub format_version: u32,
    #[serde(default)]
    pub create_if_missing: bool,
    pub configuration_epoch: u64,
    pub store_identity: String,
    pub checkpoint_root: PathBuf,
    pub startup_timeout_millis: u64,
    pub store: StorageLimitsConfig,
    pub native: NativeLimitsConfig,
    pub dispatcher: DispatcherLimitsConfig,
    pub operations: Vec<StateOperationConfig>,
    #[serde(default)]
    pub tenant_quotas: Vec<TenantQuotaConfig>,
}
}

configuration_object! {
#[derive(Clone)]
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
    #[serde(default, deserialize_with = "effects::present")]
    pub deferred_http: Option<DeferredHttpConfig>,
}
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
    pub store_identity: latent_state::store_identity::StoreIdentity,
    pub store: latent_state::protected_store::ProtectedStoreConfig,
    pub native: latent_core::native_capacity::NativeCapacityLimits,
    pub dispatcher: latent_effects::runtime::DispatcherConfig,
    pub checkpoint_root: PathBuf,
    pub startup_timeout: Duration,
    pub startup_work_bytes: u64,
    pub operations: Vec<OperationSettings>,
    pub tenant_quotas: Vec<TenantQuotaConfig>,
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
    pub deferred_http: Option<DeferredHttpConfig>,
}

pub(super) fn derive_optional(
    config: &super::NodeConfig,
) -> Result<Option<StateSettings>, PlatformError> {
    if (config.budget_profile.profile() == latent_core::BudgetProfile::Phase4)
        != config.state.is_some()
    {
        return Err(super::invalid("state.accountingProfile"));
    }
    if config.state.is_some()
        && (!matches!(
            config.supply_chain,
            super::SupplyChainConfig::Enforced { .. }
        ) || config.audit.is_none()
            || config.capability_policies.is_none())
    {
        return Err(super::invalid("state.authorityOwners"));
    }
    if config.state.as_ref().is_some_and(|state| {
        state.native.maximum_lifetime_millis < config.execution.maximum_wall_time_millis
    }) {
        return Err(super::invalid("state.native.maximumLifetimeMillis"));
    }
    config
        .state
        .as_ref()
        .map(|value| derive(value, &config.data_directory))
        .transpose()
}

pub(crate) fn derive(value: &StateConfig, data: &Path) -> Result<StateSettings, PlatformError> {
    let business_root = data.join("state");
    if value.format_version != 2
        || value.configuration_epoch == 0
        || value.operations.len() > 128
        || !(1_000..=60_000).contains(&value.startup_timeout_millis)
        || !data.is_absolute()
        || !value.checkpoint_root.is_absolute()
        || value.checkpoint_root.as_os_str().len() > 4096
        || value.checkpoint_root.capacity() > 4096
        || value.checkpoint_root.components().any(|part| {
            matches!(
                part,
                std::path::Component::ParentDir | std::path::Component::CurDir
            )
        })
        || value.checkpoint_root.starts_with(&business_root)
        || business_root.starts_with(&value.checkpoint_root)
    {
        return Err(super::invalid("state"));
    }
    let store_identity =
        latent_state::store_identity::StoreIdentity::new(value.store_identity.clone())
            .map_err(|_| super::invalid("state.storeIdentity"))?;
    let store = value.store.derive(business_root, value.create_if_missing)?;
    let native = value
        .native
        .derive(Duration::from_millis(value.startup_timeout_millis))?;
    let startup_work_bytes = owners::startup_footprint(&store, native)?;
    let dispatcher = value.dispatcher.derive()?;
    let tenant_quotas = tenant::derive(&value.tenant_quotas, &value.operations)?;
    let operations = derive_operations(&value.operations)?;
    Ok(StateSettings {
        create_if_missing: value.create_if_missing,
        configuration_epoch: value.configuration_epoch,
        store_identity,
        store,
        native,
        dispatcher,
        checkpoint_root: value.checkpoint_root.clone(),
        startup_timeout: Duration::from_millis(value.startup_timeout_millis),
        startup_work_bytes,
        operations,
        tenant_quotas,
    })
}

fn derive_operations(
    inputs: &[StateOperationConfig],
) -> Result<Vec<OperationSettings>, PlatformError> {
    let mut operations = Vec::with_capacity(inputs.len());
    for input in inputs {
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
        if let Some(effect) = &input.deferred_http {
            effect.validate()?;
        }
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
            deferred_http: input.deferred_http.clone(),
        });
    }
    Ok(operations)
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
pub(crate) mod tests;
