use serde::de::{MapAccess, Visitor, value::MapAccessDeserializer};
use serde::{Deserialize, Deserializer};

use super::model::{
    EngineActivationStackAccounting, EngineAllocator, EngineConfig, EngineOptimization,
    EngineThreadingProfile,
};

// Struct derives also accept positional JSON arrays. The operator engine input
// is an object; preserve streaming duplicate-field rejection while requiring it.
impl<'de> Deserialize<'de> for EngineConfig {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct EngineVisitor;
        impl<'de> Visitor<'de> for EngineVisitor {
            type Value = EngineConfig;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("an engine configuration object")
            }

            fn visit_map<M: MapAccess<'de>>(self, map: M) -> Result<Self::Value, M::Error> {
                #[derive(Default, Deserialize)]
                #[serde(rename_all = "camelCase", deny_unknown_fields, default)]
                struct Fields {
                    allocator: EngineAllocator,
                    optimization: EngineOptimization,
                    java_guest: bool,
                    threading_profile: EngineThreadingProfile,
                    activation_stack_accounting: EngineActivationStackAccounting,
                }
                let fields = Fields::deserialize(MapAccessDeserializer::new(map))?;
                Ok(EngineConfig {
                    allocator: fields.allocator,
                    optimization: fields.optimization,
                    java_guest: fields.java_guest,
                    threading_profile: fields.threading_profile,
                    activation_stack_accounting: fields.activation_stack_accounting,
                })
            }
        }
        deserializer.deserialize_map(EngineVisitor)
    }
}
