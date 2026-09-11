//! Fixed-size optional observation values; never a catalog or artifact owner.

use latent_manifest::__serde::Serialize;

use super::CatalogWorkOperation;

/// The owning catalog operation's terminal observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(crate = "latent_manifest::__serde", rename_all = "kebab-case")]
pub enum CatalogWorkOutcome {
    ReturnedOk,
    ReturnedError,
    OwnerDropped,
}

/// Local work counts. Encode/serialization fields count attempts at their actual sites.
/// Buffer byte fields sum observed lengths, including partially serialized failures;
/// capacities are maxima for individual buffers, not simultaneous heap usage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(crate = "latent_manifest::__serde")]
pub struct CatalogWorkCounts {
    pub normalization_deployment_encodes: u64,
    pub compiler_calls: u64,
    pub compiler_completed: u64,
    pub compiler_failed: u64,
    pub compiler_deployment_encodes: u64,
    pub revision_identity_encodes: u64,
    pub contract_schema_encodes: u64,
    pub record_derivations: u64,
    pub record_payload_reuses: u64,
    pub record_derivation_reuses: u64,
    pub scopes_staged: u64,
    pub scope_content_reuses: u64,
    pub route_memberships_staged: u64,
    pub route_memberships_remapped: u64,
    pub encoder_calls: u64,
    pub encoder_completed: u64,
    pub encoder_failed: u64,
    pub persistence_deployment_encodes: u64,
    pub payload_serializations: u64,
    pub envelope_serializations: u64,
    pub load_payload_serializations: u64,
    pub payload_buffer_bytes: u64,
    pub payload_capacity_max: u64,
    pub encoded_buffer_bytes: u64,
    pub encoded_capacity_max: u64,
    pub load_payload_buffer_bytes: u64,
    pub load_payload_capacity_max: u64,
    pub stage_calls: u64,
    pub stage_requested_bytes: u64,
    pub stage_write_failures: u64,
    pub stage_completed: u64,
    pub stage_synced_bytes: u64,
    pub stage_sync_failures: u64,
    /// None once a `write_all` failure makes the partial staged byte count unknown.
    pub stage_written_bytes: Option<u64>,
}

impl Default for CatalogWorkCounts {
    fn default() -> Self {
        Self {
            normalization_deployment_encodes: 0,
            compiler_calls: 0,
            compiler_completed: 0,
            compiler_failed: 0,
            compiler_deployment_encodes: 0,
            revision_identity_encodes: 0,
            contract_schema_encodes: 0,
            record_derivations: 0,
            record_payload_reuses: 0,
            record_derivation_reuses: 0,
            scopes_staged: 0,
            scope_content_reuses: 0,
            route_memberships_staged: 0,
            route_memberships_remapped: 0,
            encoder_calls: 0,
            encoder_completed: 0,
            encoder_failed: 0,
            persistence_deployment_encodes: 0,
            payload_serializations: 0,
            envelope_serializations: 0,
            load_payload_serializations: 0,
            payload_buffer_bytes: 0,
            payload_capacity_max: 0,
            encoded_buffer_bytes: 0,
            encoded_capacity_max: 0,
            load_payload_buffer_bytes: 0,
            load_payload_capacity_max: 0,
            stage_calls: 0,
            stage_requested_bytes: 0,
            stage_write_failures: 0,
            stage_completed: 0,
            stage_synced_bytes: 0,
            stage_sync_failures: 0,
            stage_written_bytes: Some(0),
        }
    }
}

/// One finished operation; last-writer receipt only, with no unbounded history.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(crate = "latent_manifest::__serde")]
pub struct CatalogWorkReceipt {
    pub sequence: u64,
    pub operation: CatalogWorkOperation,
    pub outcome: CatalogWorkOutcome,
    pub compiled_generation: Option<u64>,
    pub overflowed: bool,
    pub counts: CatalogWorkCounts,
}

/// The collector must observe one started/finished operation and no overlap to
/// associate the last receipt with its own call. Snapshot does not reset counters.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(crate = "latent_manifest::__serde")]
pub struct CatalogWorkSnapshot {
    pub started: u64,
    pub finished: u64,
    pub active: u64,
    pub maximum_active: u64,
    pub overflowed: bool,
    pub poisoned: bool,
    pub last: Option<CatalogWorkReceipt>,
}
