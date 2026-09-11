//! Bounded observations of node-owned resources. Collection never enumerates a
//! deployment, release, tenant, or activation catalog and creates no worker.

mod bounds;
mod health;
mod metrics;
mod reporter;
mod sources;
#[cfg(test)]
mod tests;

use std::sync::Arc;
use std::time::Duration;

use latent_admission::{LocalQuotaProvider, NodeLoadSource, QuotaLimits, QuotaUsage};
use latent_artifacts::CacheEntryDescriptor;
use latent_core::{ActivationClock, BoxFuture, Metadata, NodeId, PlatformError, RouteGeneration};
use latent_routing::RouteResolver;
use latent_scheduler::CellClass;

pub use reporter::StandaloneInventoryReporter;
pub use sources::{
    CacheInventorySource, CacheInventoryWriter, EmptyCacheInventorySource, EmptyNodeTopologySource,
    NodeTopologySource, NodeTopologyWriter, SchedulerInventorySnapshot, SchedulerInventorySource,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CellClassCapacity {
    pub class: String,
    pub observation_available: bool,
    pub accepting: bool,
    pub total: u32,
    pub available: u32,
    pub active: u32,
    pub quarantined: u32,
    pub queue_depth: u32,
    pub queue_capacity: u32,
    pub queued_tenants: u32,
    pub rejected: u64,
    pub cancellations: u64,
    pub expired: u64,
    pub granted: u64,
    pub total_wait_micros: u64,
    pub max_wait_micros: u64,
    pub oldest_lease_age_micros: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeDescriptor {
    pub id: NodeId,
    pub architecture: String,
    pub operating_system: String,
    pub cpu_features: Vec<String>,
    pub trust_classes: Vec<String>,
    pub region: Option<String>,
    pub zone: Option<String>,
    pub endpoint: String,
    pub identity: String,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealthStatus {
    Healthy,
    Degraded,
    Unhealthy,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeHealthObservation {
    pub status: HealthStatus,
    pub ready: bool,
    pub healthy: bool,
    /// Fixed diagnostic reasons; caller metadata is never included.
    pub reasons: Vec<String>,
    pub observed_at_unix_millis: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NodePressureObservation {
    /// False means no trustworthy current load sample; zero is not a reading.
    pub load_available: bool,
    pub load_sample_age_millis: Option<u64>,
    pub cpu_pressure_milli: u32,
    pub memory_pressure_milli: u32,
    pub queue_pressure_milli: u32,
    pub cache_pressure_milli: u32,
}

/// Backend-neutral prepared-cache accounting. These are charged cache costs,
/// not process RSS; evicted values pinned by invocations and compiler scratch
/// memory are outside the resident entry totals. No guest store is cached.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NodeCacheSummary {
    pub available: bool,
    pub entries: u64,
    pub maximum_entries: u64,
    pub source_bytes: u64,
    pub maximum_source_bytes: u64,
    pub metadata_bytes: u64,
    pub maximum_metadata_bytes: u64,
    pub compiled_image_bytes: u64,
    pub maximum_compiled_image_bytes: u64,
    pub preparing: u64,
    pub maximum_concurrent_preparations: u64,
    pub preparing_source_bytes: u64,
    pub preparing_metadata_bytes: u64,
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    /// Explicit matching-entry invalidation, separate from capacity eviction.
    pub invalidations: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResourceOwnership {
    NodeFixed,
    ActivationScoped,
    ServiceResident,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeTopologyEntry {
    pub name: String,
    pub kind: String,
    pub ownership: ResourceOwnership,
    pub configured_count: u64,
    /// None explicitly distinguishes unmeasured resources from observed zero.
    pub active_count: Option<u64>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NodeResourceTopology {
    pub entries: Vec<NodeTopologyEntry>,
    pub available: bool,
    /// False when a source reports that the bounded selection omitted rows.
    pub complete: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NodeQuotaSummary {
    /// Includes queued and executing reservations, not consumed guest resources.
    pub usage: QuotaUsage,
    pub limits: QuotaLimits,
    pub retained_tenants: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInventory {
    pub node: NodeDescriptor,
    pub cell_capacity: Vec<CellClassCapacity>,
    /// Read with `pressure.load_available`; never inferred from cache occupancy.
    pub memory_pressure_milli: u32,
    pub queue_depth: u64,
    pub route_generation: RouteGeneration,
    pub cache_entries: Vec<CacheEntryDescriptor>,
    pub observed_at_unix_millis: u64,
    pub cache_summary: NodeCacheSummary,
    pub pressure: NodePressureObservation,
    pub health: NodeHealthObservation,
    pub topology: NodeResourceTopology,
    pub quotas: Option<NodeQuotaSummary>,
    /// Conservative allocation cost of this returned snapshot, including
    /// collection bookkeeping and spare capacity. Does not include source state.
    pub retained_bytes: usize,
}

pub trait InventoryReporter: Send + Sync {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StandaloneInventoryConfig {
    /// A fixed node configuration, never discovered by scanning deployments.
    pub cell_classes: Vec<CellClass>,
    pub maximum_cache_descriptors: usize,
    pub maximum_topology_entries: usize,
    pub maximum_snapshot_bytes: usize,
    pub maximum_string_bytes: usize,
    pub maximum_load_age: Duration,
}

impl Default for StandaloneInventoryConfig {
    fn default() -> Self {
        Self {
            cell_classes: vec![
                CellClass::Tiny,
                CellClass::Small,
                CellClass::Standard,
                CellClass::Large,
                CellClass::ExtraLarge,
            ],
            maximum_cache_descriptors: 16,
            maximum_topology_entries: 32,
            maximum_snapshot_bytes: 256 * 1024,
            maximum_string_bytes: 512,
            maximum_load_age: Duration::from_secs(5),
        }
    }
}

#[derive(Clone)]
pub struct StandaloneInventorySources {
    pub scheduler: Arc<dyn SchedulerInventorySource>,
    /// Only `generation()` is called; no catalog view or service list is retained.
    pub routes: Arc<dyn RouteResolver>,
    pub quotas: LocalQuotaProvider,
    pub load: Arc<dyn NodeLoadSource>,
    pub cache: Arc<dyn CacheInventorySource>,
    pub topology: Arc<dyn NodeTopologySource>,
    pub clock: Arc<dyn ActivationClock>,
}

fn class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}

fn invalid(message: &str) -> PlatformError {
    PlatformError {
        code: latent_core::PlatformErrorCode::InvalidArgument,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn exhausted() -> PlatformError {
    PlatformError {
        code: latent_core::PlatformErrorCode::ResourceExhausted,
        message: "inventory-snapshot-capacity".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
