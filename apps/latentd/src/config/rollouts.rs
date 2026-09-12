//! Optional manual rollout control. Derivation opens no storage or worker.
use latent_control_store::rollouts::RolloutLimits;
use latent_core::PlatformError;
use latent_rollout::CoordinatorLimits;
use serde::{Deserialize, Deserializer};

#[derive(Clone, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum RolloutConfig {
    Manual {
        #[serde(default = "active")]
        active: usize,
        #[serde(default = "retained")]
        retained: usize,
        #[serde(default = "stages")]
        stages: usize,
        #[serde(default = "receipts")]
        receipts: usize,
        #[serde(rename = "metadataBytes", default = "metadata_bytes")]
        metadata_bytes: usize,
        #[serde(rename = "queuedOperations", default = "queued_operations")]
        queued_operations: usize,
        #[serde(rename = "queuedBytes", default = "queued_bytes")]
        queued_bytes: usize,
        #[serde(rename = "queryOwners", default = "query_owners")]
        query_owners: usize,
    },
}

#[derive(Clone, Copy)]
pub(crate) struct RolloutSettings {
    pub store: RolloutLimits,
    pub coordinator: CoordinatorLimits,
}

const fn active() -> usize {
    16
}
const fn retained() -> usize {
    256
}
const fn stages() -> usize {
    16
}
const fn receipts() -> usize {
    256
}
const fn metadata_bytes() -> usize {
    8 * 1024 * 1024
}
const fn queued_operations() -> usize {
    8
}
const fn queued_bytes() -> usize {
    512 * 1024
}
const fn query_owners() -> usize {
    4
}

pub(super) fn present<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Option<RolloutConfig>, D::Error> {
    RolloutConfig::deserialize(decoder).map(Some)
}

pub(super) fn derive(
    config: Option<&RolloutConfig>,
    audit_enabled: bool,
) -> Result<Option<RolloutSettings>, PlatformError> {
    let Some(RolloutConfig::Manual {
        active,
        retained,
        stages,
        receipts,
        metadata_bytes,
        queued_operations,
        queued_bytes,
        query_owners,
    }) = config
    else {
        return Ok(None);
    };
    if !audit_enabled || !(1..=16).contains(query_owners) {
        return Err(super::invalid(
            "rollouts require durable audit and bounded owners",
        ));
    }
    let store = RolloutLimits {
        maximum_active: *active,
        maximum_rows: *retained,
        maximum_stages: *stages,
        maximum_receipts: *receipts,
        maximum_metadata_bytes: *metadata_bytes,
    }
    .validate()
    .map_err(|_| super::invalid("rollouts"))?;
    let coordinator = CoordinatorLimits {
        maximum_queued_commands: *queued_operations,
        maximum_queued_bytes: *queued_bytes,
        maximum_query_owners: *query_owners,
        maximum_total_page_bytes: query_owners * 256 * 1024,
        ..CoordinatorLimits::default()
    }
    .validate()
    .map_err(|_| super::invalid("rollouts"))?;
    Ok(Some(RolloutSettings { store, coordinator }))
}

#[cfg(test)]
mod tests;
