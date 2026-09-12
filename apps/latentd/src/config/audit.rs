//! Optional durable administrative history, separate from telemetry retention.
use latent_audit::AuditLimits;
use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Deserializer};

use super::invalid;

#[derive(Clone, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum AuditConfig {
    Durable {
        #[serde(default = "records")]
        records: usize,
        #[serde(rename = "diskBytes", default = "disk_bytes")]
        disk_bytes: usize,
        #[serde(rename = "queuedOperations", default = "queued_operations")]
        queued_operations: usize,
        #[serde(rename = "queryOwners", default = "query_owners")]
        query_owners: usize,
    },
}

const fn records() -> usize {
    4096
}
const fn disk_bytes() -> usize {
    64 * 1024 * 1024
}
const fn queued_operations() -> usize {
    64
}
const fn query_owners() -> usize {
    4
}

pub(super) fn present<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Option<AuditConfig>, D::Error> {
    AuditConfig::deserialize(decoder).map(Some)
}

pub(super) fn derive(config: Option<&AuditConfig>) -> Result<Option<AuditLimits>, PlatformError> {
    let Some(AuditConfig::Durable {
        records,
        disk_bytes,
        queued_operations,
        query_owners,
    }) = config
    else {
        return Ok(None);
    };
    if !cfg!(target_os = "linux") {
        return Err(PlatformError {
            code: PlatformErrorCode::IncompatibleContract,
            message: "durable-audit-node-platform-unsupported".into(),
            retryable: false,
            details: Vec::new(),
        });
    }
    if !(2..=16_384).contains(records)
        || !(32 * 1024..=256 * 1024 * 1024).contains(disk_bytes)
        || !(1..=256).contains(queued_operations)
        || !(1..=16).contains(query_owners)
    {
        return Err(invalid("audit"));
    }
    let limits = AuditLimits {
        maximum_records: *records,
        maximum_disk_bytes: *disk_bytes,
        maximum_queued_operations: *queued_operations,
        maximum_query_owners: *query_owners,
        maximum_metadata_bytes: (records * 2048).max(128 * 1024 + records * 1536),
        maximum_queued_bytes: (queued_operations * 4096).max(16 * 1024),
        // A wire query reserves up to 64 KiB plus the owner's bounded decode/
        // conversion allowance. Four such allowances fund each admitted page.
        maximum_total_page_bytes: query_owners * 256 * 1024,
        maximum_query_events: (*records).min(128),
        maximum_scan_entries: (*records).min(1024),
        ..AuditLimits::default()
    };
    limits.validate().map(Some).map_err(|_| invalid("audit"))
}

#[cfg(test)]
mod tests;
