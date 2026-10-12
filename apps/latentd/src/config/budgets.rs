//! Explicit accounting profile. Enabling counters does not install providers or grants.
use latent_core::{BudgetProfile, DelegationLimits, PlatformError, ResourceBudget};
use serde::Deserialize;

#[derive(Clone, Copy, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum BudgetConfig {
    Phase1 {},
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
    Phase4 {
        #[serde(rename = "maximumStateReadBytes")]
        maximum_state_read_bytes: u64,
        #[serde(rename = "maximumStateWriteBytes")]
        maximum_state_write_bytes: u64,
        #[serde(rename = "maximumEffectCount")]
        maximum_effect_count: u32,
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
            Self::Phase3 { .. } => BudgetProfile::Phase3,
            Self::Phase4 { .. } => BudgetProfile::Phase4,
        }
    }
    pub(super) fn limits(self) -> Result<DelegationLimits, PlatformError> {
        if let Self::Phase4 {
            maximum_state_read_bytes,
            maximum_state_write_bytes,
            maximum_effect_count,
            ..
        } = self
        {
            if maximum_state_read_bytes > 1024 * 1024 * 1024
                || maximum_state_write_bytes > 1024 * 1024 * 1024
                || maximum_effect_count > 128
            {
                return Err(super::invalid("budgetProfile.phase4Ceilings"));
            }
        }
        let limits = match self {
            Self::Phase1 {} => DelegationLimits::default(),
            Self::Phase3 {
                maximum_depth,
                maximum_live_descendants,
                maximum_live_children,
                ..
            }
            | Self::Phase4 {
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
        if let Self::Phase3 {
            maximum_child_calls,
            maximum_outbound_requests,
            maximum_blob_read_bytes,
            maximum_blob_write_bytes,
            ..
        }
        | Self::Phase4 {
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
        if let Self::Phase4 {
            maximum_state_read_bytes,
            maximum_state_write_bytes,
            maximum_effect_count,
            ..
        } = self
        {
            budget.state_read_bytes = maximum_state_read_bytes;
            budget.state_write_bytes = maximum_state_write_bytes;
            budget.effect_count = maximum_effect_count;
        }
    }
}
