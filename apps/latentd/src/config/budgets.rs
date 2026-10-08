//! Explicit accounting profile. Enabling counters does not install providers or grants.
use latent_core::{BudgetProfile, DelegationLimits, PlatformError, ResourceBudget};
use serde::Deserialize;

#[derive(Clone, Copy, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum BudgetConfig {
    Phase1 {},
    /// Explicit shared transaction accounting; providers and namespace grants
    /// still require their independently installed current owners.
    Phase4 {
        #[serde(rename = "maximumStateReadBytes", default)]
        maximum_state_read_bytes: u64,
        #[serde(rename = "maximumStateWriteBytes", default)]
        maximum_state_write_bytes: u64,
        #[serde(rename = "maximumEffects", default)]
        maximum_effects: u32,
    },
    Phase3 {
        #[serde(rename = "maximumChildCalls", default)]
        maximum_child_calls: u32,
        #[serde(rename = "maximumOutboundRequests", default)]
        maximum_outbound_requests: u32,
        #[serde(rename = "maximumBlobReadBytes", default)]
        maximum_blob_read_bytes: u64,
        #[serde(rename = "maximumBlobWriteBytes", default)]
        maximum_blob_write_bytes: u64,
        #[serde(rename = "maximumDepth", default = "depth")]
        maximum_depth: u8,
        #[serde(rename = "maximumLiveDescendants", default = "descendants")]
        maximum_live_descendants: u16,
        #[serde(rename = "maximumLiveChildren", default = "children")]
        maximum_live_children: u16,
    },
}
impl Default for BudgetConfig {
    fn default() -> Self {
        Self::Phase1 {}
    }
}
const fn depth() -> u8 {
    8
}
const fn descendants() -> u16 {
    64
}
const fn children() -> u16 {
    8
}

impl BudgetConfig {
    pub(super) const fn profile(self) -> BudgetProfile {
        match self {
            Self::Phase1 {} => BudgetProfile::Phase1,
            Self::Phase4 { .. } => BudgetProfile::Phase4,
            Self::Phase3 { .. } => BudgetProfile::Phase3,
        }
    }
    pub(super) fn limits(self) -> Result<DelegationLimits, PlatformError> {
        let limits = match self {
            Self::Phase1 {} => DelegationLimits::default(),
            Self::Phase4 {
                maximum_state_read_bytes,
                maximum_state_write_bytes,
                maximum_effects,
            } => {
                if maximum_state_read_bytes > 4 * 1024 * 1024
                    || maximum_state_write_bytes > 8 * 1024 * 1024
                    || maximum_effects > 128
                {
                    return Err(super::invalid("budgetProfile"));
                }
                DelegationLimits::default()
            }
            Self::Phase3 {
                maximum_depth,
                maximum_live_descendants,
                maximum_live_children,
                ..
            } => DelegationLimits {
                maximum_depth,
                maximum_live_descendants,
                maximum_live_children,
            },
        };
        limits
            .validate()
            .map_err(|_| super::invalid("budgetProfile"))?;
        Ok(limits)
    }
    pub(super) const fn apply(self, budget: &mut ResourceBudget) {
        if let Self::Phase4 {
            maximum_state_read_bytes,
            maximum_state_write_bytes,
            maximum_effects,
        } = self
        {
            budget.state_read_bytes = maximum_state_read_bytes;
            budget.state_write_bytes = maximum_state_write_bytes;
            budget.effect_count = maximum_effects;
        }
        if let Self::Phase3 {
            maximum_child_calls,
            maximum_outbound_requests,
            maximum_blob_read_bytes,
            maximum_blob_write_bytes,
            ..
        } = self
        {
            budget.child_calls = maximum_child_calls;
            budget.outbound_requests = maximum_outbound_requests;
            budget.blob_read_bytes = maximum_blob_read_bytes;
            budget.blob_write_bytes = maximum_blob_write_bytes;
        }
    }
}
