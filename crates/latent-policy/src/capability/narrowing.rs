use super::{invalid, operation, unique, CapabilityCeiling, ResourceConstraint, ResourceTarget};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

/// Additional restriction, never an independent allow rule. Omitted resources
/// or ceiling and an empty operation list inherit the required policy scope.
/// Explicit null is rejected, so absence has one meaning across all adapters.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GrantRestriction {
    pub operations: Vec<String>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    pub resources: Option<ResourceConstraint>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    pub ceiling: Option<CapabilityCeiling>,
}

fn present<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    decoder: D,
) -> Result<Option<T>, D::Error> {
    T::deserialize(decoder).map(Some)
}

impl GrantRestriction {
    pub fn canonical_bytes(&self, capability: &str) -> Result<Vec<u8>, PlatformError> {
        self.validate(capability)?;
        serde_json::to_vec(self).map_err(|_| invalid())
    }
    pub fn parse(bytes: &[u8], capability: &str) -> Result<Self, PlatformError> {
        super::preflight(bytes)?;
        let value: Self = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        value.validate(capability)?;
        Ok(value)
    }
    pub fn validate(&self, capability: &str) -> Result<(), PlatformError> {
        if latent_core::PHASE3_HOST_ABI_V3
            .interface(capability)
            .is_none()
            || !unique(&self.operations, |value| operation(capability, value))
        {
            return Err(invalid());
        }
        if let Some(resources) = &self.resources {
            resources.validate()?;
            if !resources.compatible(capability) {
                return Err(invalid());
            }
        }
        if let Some(ceiling) = self.ceiling {
            ceiling.validate()?;
        }
        Ok(())
    }
    pub(super) fn narrow(
        &self,
        operation: &str,
        target: &ResourceTarget<'_>,
        ceiling: CapabilityCeiling,
    ) -> Option<CapabilityCeiling> {
        if (!self.operations.is_empty() && !self.operations.iter().any(|value| value == operation))
            || self
                .resources
                .as_ref()
                .is_some_and(|value| !value.covers(target))
        {
            return None;
        }
        Some(
            self.ceiling
                .map_or(ceiling, |value| ceiling.intersect(value)),
        )
    }
}
