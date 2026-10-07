//! Finite eligibility limits for the one installed state runtime.
use latent_state::entity_lanes::EntityLaneLimits;
use serde::{Deserialize, Deserializer};
use std::time::Duration;

#[derive(Clone)]
pub struct EntityLaneConfig {
    limits: EntityLaneLimits,
}

impl Default for EntityLaneConfig {
    fn default() -> Self {
        Self {
            limits: latent_node::transaction_runtime::default_entity_limits(),
        }
    }
}

impl EntityLaneConfig {
    pub(super) fn derive(&self) -> Result<EntityLaneLimits, latent_core::PlatformError> {
        latent_node::transaction_runtime::EntityCommandLanes::validate_limits(&self.limits)?;
        Ok(self.limits.clone())
    }
}

impl<'de> Deserialize<'de> for EntityLaneConfig {
    fn deserialize<D: Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        struct Object;
        impl<'de> serde::de::Visitor<'de> for Object {
            type Value = EntityLaneConfig;
            fn expecting(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                output.write_str("a finite entity lane configuration object")
            }
            fn visit_map<M: serde::de::MapAccess<'de>>(
                self,
                map: M,
            ) -> Result<Self::Value, M::Error> {
                #[derive(Deserialize)]
                #[serde(rename_all = "camelCase", deny_unknown_fields)]
                struct Fields {
                    global_queued: usize,
                    tenant_queued: usize,
                    entity_queued: usize,
                    global_keys: usize,
                    tenant_keys: usize,
                    global_active: usize,
                    tenant_active: usize,
                    global_bytes: u64,
                    tenant_bytes: u64,
                    entity_bytes: u64,
                    scope_bytes: usize,
                    command_identity_bytes: usize,
                    maximum_wait_millis: u64,
                }
                let fields =
                    Fields::deserialize(serde::de::value::MapAccessDeserializer::new(map))?;
                let limits = EntityLaneLimits {
                    global_queued: fields.global_queued,
                    tenant_queued: fields.tenant_queued,
                    entity_queued: fields.entity_queued,
                    global_keys: fields.global_keys,
                    tenant_keys: fields.tenant_keys,
                    global_active: fields.global_active,
                    tenant_active: fields.tenant_active,
                    global_bytes: fields.global_bytes,
                    tenant_bytes: fields.tenant_bytes,
                    entity_bytes: fields.entity_bytes,
                    scope_bytes: fields.scope_bytes,
                    command_identity_bytes: fields.command_identity_bytes,
                    maximum_wait_age: Duration::from_millis(fields.maximum_wait_millis),
                };
                latent_node::transaction_runtime::EntityCommandLanes::validate_limits(&limits)
                    .map_err(|_| serde::de::Error::custom("invalid finite entity lane limits"))?;
                Ok(EntityLaneConfig { limits })
            }
        }
        decoder.deserialize_map(Object)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn document() -> serde_json::Value {
        serde_json::json!({
            "globalQueued":16,"tenantQueued":8,"entityQueued":2,
            "globalKeys":16,"tenantKeys":8,"globalActive":8,"tenantActive":4,
            "globalBytes":67_108_864,"tenantBytes":33_554_432,"entityBytes":16_777_216,
            "scopeBytes":1024,"commandIdentityBytes":128,"maximumWaitMillis":5000
        })
    }

    #[test]
    fn entity_configuration_requires_complete_object_and_refuses_null_arrays_unknown_and_duplicate_fields(
    ) {
        assert!(serde_json::from_value::<EntityLaneConfig>(document()).is_ok());
        for value in [
            serde_json::Value::Null,
            serde_json::json!([]),
            serde_json::json!({}),
        ] {
            assert!(serde_json::from_value::<EntityLaneConfig>(value).is_err());
        }
        let mut unknown = document();
        unknown["unlimited"] = true.into();
        assert!(serde_json::from_value::<EntityLaneConfig>(unknown).is_err());
        let raw = serde_json::to_string(&document()).unwrap();
        let duplicate = raw.replacen("{", "{\"globalQueued\":16,", 1);
        assert!(serde_json::from_str::<EntityLaneConfig>(&duplicate).is_err());
    }

    #[test]
    fn entity_configuration_refuses_nonfinite_inverted_counts_bytes_and_wait_age_before_runtime_open(
    ) {
        for (field, value) in [
            ("globalQueued", 0),
            ("tenantQueued", 17),
            ("entityQueued", 9),
            ("globalKeys", 4097),
            ("tenantKeys", 17),
            ("tenantActive", 9),
            ("globalBytes", 1_073_741_825),
            ("entityBytes", 33_554_433),
            ("maximumWaitMillis", 0),
            ("maximumWaitMillis", 30001),
        ] {
            let mut invalid = document();
            invalid[field] = serde_json::json!(value);
            assert!(
                serde_json::from_value::<EntityLaneConfig>(invalid).is_err(),
                "{field}"
            );
        }
    }

    #[test]
    fn entity_configuration_default_and_selected_caps_remain_finite_without_changing_main_config_limit(
    ) {
        let selected = serde_json::from_value::<EntityLaneConfig>(document())
            .unwrap()
            .derive()
            .unwrap();
        assert_eq!(selected.entity_queued, 2);
        assert_eq!(selected.maximum_wait_age, Duration::from_secs(5));
        let default = EntityLaneConfig::default().derive().unwrap();
        assert_eq!(default.global_queued, 64);
        assert_eq!(default.entity_queued, 8);
        assert_eq!(default.maximum_wait_age, Duration::from_secs(30));
    }
}
