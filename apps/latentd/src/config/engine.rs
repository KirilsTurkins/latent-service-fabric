use serde::de::{value::MapAccessDeserializer, MapAccess, Visitor};
use serde::{Deserialize, Deserializer};

use super::model::{EngineAllocator, EngineConfig, EngineOptimization};

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
                }
                let fields = Fields::deserialize(MapAccessDeserializer::new(map))?;
                Ok(EngineConfig {
                    allocator: fields.allocator,
                    optimization: fields.optimization,
                })
            }
        }
        deserializer.deserialize_map(EngineVisitor)
    }
}
