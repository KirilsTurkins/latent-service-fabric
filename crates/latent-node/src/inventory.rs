use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_artifacts::CacheEntryDescriptor;
use latent_core::{BoxFuture, Metadata, NodeId, PlatformError, PlatformErrorCode, RouteGeneration};
use latent_routing::RouteSnapshot;
use latent_scheduler::{CellClass, CellPool};

const MAX_CELL_CLASSES: usize = 5;
const MAX_HEALTH_REASONS: usize = 16;
const MAX_REASON_BYTES: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CellClassCapacity {
    pub class: String,
    pub total: u32,
    pub available: u32,
    pub active: u32,
    pub quarantined: u32,
    pub queue_depth: u32,
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
    pub reasons: Vec<String>,
    pub observed_at_unix_millis: u64,
}

impl Default for NodeHealthObservation {
    fn default() -> Self {
        Self {
            status: HealthStatus::Healthy,
            ready: true,
            healthy: true,
            reasons: Vec::new(),
            observed_at_unix_millis: now_unix_millis(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NodePressureObservation {
    pub memory_pressure_milli: u32,
    pub queue_pressure_milli: u32,
    pub cache_pressure_milli: u32,
    pub telemetry_pressure_milli: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeCacheSummary {
    pub entries: u64,
    pub resident_bytes: u64,
    pub maximum_entries: u64,
    pub maximum_bytes: u64,
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub descriptors: Vec<CacheEntryDescriptor>,
}

impl Default for NodeCacheSummary {
    fn default() -> Self {
        Self {
            entries: 0,
            resident_bytes: 0,
            maximum_entries: 0,
            maximum_bytes: 0,
            hits: 0,
            misses: 0,
            evictions: 0,
            descriptors: Vec::new(),
        }
    }
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
    pub active_count: u64,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NodeResourceTopology {
    pub entries: Vec<NodeTopologyEntry>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInventory {
    pub node: NodeDescriptor,
    pub cell_capacity: Vec<CellClassCapacity>,
    pub memory_pressure_milli: u32,
    pub queue_depth: u64,
    pub route_generation: RouteGeneration,
    pub cache_entries: Vec<CacheEntryDescriptor>,
    pub observed_at_unix_millis: u64,
    pub cache_summary: NodeCacheSummary,
    pub pressure: NodePressureObservation,
    pub health: NodeHealthObservation,
    pub topology: NodeResourceTopology,
}

impl NodeInventory {
    #[must_use]
    pub fn operator_summary(&self) -> Metadata {
        let total_cells = self
            .cell_capacity
            .iter()
            .map(|capacity| u64::from(capacity.total))
            .sum::<u64>();
        let available_cells = self
            .cell_capacity
            .iter()
            .map(|capacity| u64::from(capacity.available))
            .sum::<u64>();
        let fixed_helpers = self
            .topology
            .entries
            .iter()
            .filter(|entry| entry.ownership == ResourceOwnership::NodeFixed)
            .map(|entry| entry.active_count)
            .sum::<u64>();
        let service_resident = self
            .topology
            .entries
            .iter()
            .filter(|entry| entry.ownership == ResourceOwnership::ServiceResident)
            .map(|entry| entry.active_count)
            .sum::<u64>();
        Metadata::from([
            ("node".to_owned(), self.node.id.0.clone()),
            ("ready".to_owned(), self.health.ready.to_string()),
            ("healthy".to_owned(), self.health.healthy.to_string()),
            (
                "route_generation".to_owned(),
                self.route_generation.0.to_string(),
            ),
            ("cell_total".to_owned(), total_cells.to_string()),
            ("cell_available".to_owned(), available_cells.to_string()),
            ("queue_depth".to_owned(), self.queue_depth.to_string()),
            (
                "cache_entries".to_owned(),
                self.cache_summary.entries.to_string(),
            ),
            ("node_fixed_resources".to_owned(), fixed_helpers.to_string()),
            (
                "service_resident_resources".to_owned(),
                service_resident.to_string(),
            ),
        ])
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeHeartbeat {
    pub node: NodeId,
    pub generation: u64,
    pub observed_at_unix_millis: u64,
    pub healthy: bool,
    pub attributes: Metadata,
}

pub trait NodeRegistrar: Send + Sync {
    fn register<'a>(
        &'a self,
        descriptor: NodeDescriptor,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn heartbeat<'a>(
        &'a self,
        heartbeat: NodeHeartbeat,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn deregister<'a>(&'a self, node: &'a NodeId) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait InventoryReporter: Send + Sync {
    fn snapshot<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>>;
}

pub trait RouteWatcher: Send + Sync {
    fn current_generation(&self) -> RouteGeneration;

    fn next<'a>(
        &'a self,
        after: RouteGeneration,
    ) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>>;
}

pub trait NodeDirectory: Send + Sync {
    fn get<'a>(
        &'a self,
        node: &'a NodeId,
    ) -> BoxFuture<'a, Result<Option<NodeDescriptor>, PlatformError>>;

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<NodeDescriptor>, PlatformError>>;
}

pub trait RouteGenerationSource: Send + Sync {
    fn current_generation(&self) -> RouteGeneration;
}

pub trait CacheInventorySource: Send + Sync {
    /// Returns constant-time aggregate cache state and at most `maximum_descriptors`
    /// already-selected descriptors. Implementations must not enumerate a full
    /// release catalog to answer this call.
    fn snapshot(&self, maximum_descriptors: usize) -> NodeCacheSummary;
}

pub trait MemoryPressureSource: Send + Sync {
    fn pressure(&self) -> NodePressureObservation;
}

pub trait NodeHealthSource: Send + Sync {
    fn health(&self) -> NodeHealthObservation;
}

pub trait NodeTopologySource: Send + Sync {
    fn topology(&self) -> NodeResourceTopology;
}

#[derive(Debug, Default)]
pub struct EmptyCacheInventorySource;

impl CacheInventorySource for EmptyCacheInventorySource {
    fn snapshot(&self, _maximum_descriptors: usize) -> NodeCacheSummary {
        NodeCacheSummary::default()
    }
}

#[derive(Debug)]
pub struct StaticRouteGenerationSource {
    generation: AtomicU64,
}

impl StaticRouteGenerationSource {
    #[must_use]
    pub const fn new(generation: RouteGeneration) -> Self {
        Self {
            generation: AtomicU64::new(generation.0),
        }
    }

    pub fn set(&self, generation: RouteGeneration) {
        self.generation.store(generation.0, Ordering::Release);
    }
}

impl RouteGenerationSource for StaticRouteGenerationSource {
    fn current_generation(&self) -> RouteGeneration {
        RouteGeneration(self.generation.load(Ordering::Acquire))
    }
}

#[derive(Debug, Default)]
pub struct StaticMemoryPressureSource {
    memory: AtomicU32,
    queue: AtomicU32,
    cache: AtomicU32,
    telemetry: AtomicU32,
}

impl StaticMemoryPressureSource {
    #[must_use]
    pub fn new(observation: NodePressureObservation) -> Self {
        let source = Self::default();
        source.set(observation);
        source
    }

    pub fn set(&self, observation: NodePressureObservation) {
        self.memory.store(
            clamp_milli(observation.memory_pressure_milli),
            Ordering::Release,
        );
        self.queue.store(
            clamp_milli(observation.queue_pressure_milli),
            Ordering::Release,
        );
        self.cache.store(
            clamp_milli(observation.cache_pressure_milli),
            Ordering::Release,
        );
        self.telemetry.store(
            clamp_milli(observation.telemetry_pressure_milli),
            Ordering::Release,
        );
    }
}

impl MemoryPressureSource for StaticMemoryPressureSource {
    fn pressure(&self) -> NodePressureObservation {
        NodePressureObservation {
            memory_pressure_milli: self.memory.load(Ordering::Acquire),
            queue_pressure_milli: self.queue.load(Ordering::Acquire),
            cache_pressure_milli: self.cache.load(Ordering::Acquire),
            telemetry_pressure_milli: self.telemetry.load(Ordering::Acquire),
        }
    }
}

#[derive(Debug, Default)]
pub struct MutableNodeHealthSource {
    observation: Mutex<NodeHealthObservation>,
}

impl MutableNodeHealthSource {
    #[must_use]
    pub fn new(observation: NodeHealthObservation) -> Self {
        Self {
            observation: Mutex::new(normalize_health(observation)),
        }
    }

    pub fn set(&self, observation: NodeHealthObservation) {
        *self.lock_observation() = normalize_health(observation);
    }

    fn lock_observation(&self) -> MutexGuard<'_, NodeHealthObservation> {
        self.observation
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl NodeHealthSource for MutableNodeHealthSource {
    fn health(&self) -> NodeHealthObservation {
        self.lock_observation().clone()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StandaloneInventoryConfig {
    pub cell_classes: Vec<CellClass>,
    pub maximum_cache_descriptors: usize,
    pub maximum_topology_entries: usize,
}

impl Default for StandaloneInventoryConfig {
    fn default() -> Self {
        Self {
            cell_classes: vec![CellClass::Standard],
            maximum_cache_descriptors: 16,
            maximum_topology_entries: 64,
        }
    }
}

pub struct StandaloneInventoryReporter {
    config: StandaloneInventoryConfig,
    node: NodeDescriptor,
    cell_pool: Arc<dyn CellPool>,
    routes: Arc<dyn RouteGenerationSource>,
    cache: Arc<dyn CacheInventorySource>,
    pressure: Arc<dyn MemoryPressureSource>,
    health: Arc<dyn NodeHealthSource>,
    fixed_topology: NodeResourceTopology,
    dynamic_topology: Arc<dyn NodeTopologySource>,
}

impl std::fmt::Debug for StandaloneInventoryReporter {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("StandaloneInventoryReporter")
            .field("config", &self.config)
            .field("node", &self.node)
            .field("fixed_topology", &self.fixed_topology)
            .finish_non_exhaustive()
    }
}

impl StandaloneInventoryReporter {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        config: StandaloneInventoryConfig,
        node: NodeDescriptor,
        cell_pool: Arc<dyn CellPool>,
        routes: Arc<dyn RouteGenerationSource>,
        cache: Arc<dyn CacheInventorySource>,
        pressure: Arc<dyn MemoryPressureSource>,
        health: Arc<dyn NodeHealthSource>,
        fixed_topology: NodeResourceTopology,
        dynamic_topology: Arc<dyn NodeTopologySource>,
    ) -> Result<Self, PlatformError> {
        validate_config(&config)?;
        Ok(Self {
            config,
            node,
            cell_pool,
            routes,
            cache,
            pressure,
            health,
            fixed_topology,
            dynamic_topology,
        })
    }

    fn collect(&self) -> Result<NodeInventory, PlatformError> {
        let observed_at = now_unix_millis();
        let mut capacities = Vec::with_capacity(self.config.cell_classes.len());
        let mut queue_depth = 0_u64;
        for class in &self.config.cell_classes {
            let snapshot = self.cell_pool.observations(*class);
            queue_depth = queue_depth.saturating_add(u64::from(snapshot.queue_depth));
            capacities.push(CellClassCapacity {
                class: cell_class_name(*class).to_owned(),
                total: snapshot.capacity,
                available: snapshot.available,
                active: snapshot.active_leases,
                quarantined: snapshot.quarantined,
                queue_depth: snapshot.queue_depth,
            });
        }
        let mut cache_summary = self.cache.snapshot(self.config.maximum_cache_descriptors);
        cache_summary
            .descriptors
            .truncate(self.config.maximum_cache_descriptors);
        let pressure = normalize_pressure(self.pressure.pressure());
        let health = normalize_health(self.health.health());
        let mut topology = self.fixed_topology.clone();
        topology
            .entries
            .extend(self.dynamic_topology.topology().entries);
        topology
            .entries
            .truncate(self.config.maximum_topology_entries);
        normalize_topology(&mut topology);
        Ok(NodeInventory {
            node: self.node.clone(),
            cell_capacity: capacities,
            memory_pressure_milli: pressure.memory_pressure_milli,
            queue_depth,
            route_generation: self.routes.current_generation(),
            cache_entries: cache_summary.descriptors.clone(),
            observed_at_unix_millis: observed_at,
            cache_summary,
            pressure,
            health,
            topology,
        })
    }
}

impl InventoryReporter for StandaloneInventoryReporter {
    fn snapshot<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>> {
        Box::pin(async move { self.collect() })
    }
}

#[derive(Debug, Default)]
pub struct EmptyNodeTopologySource;

impl NodeTopologySource for EmptyNodeTopologySource {
    fn topology(&self) -> NodeResourceTopology {
        NodeResourceTopology::default()
    }
}

fn validate_config(config: &StandaloneInventoryConfig) -> Result<(), PlatformError> {
    if config.cell_classes.is_empty()
        || config.cell_classes.len() > MAX_CELL_CLASSES
        || config.maximum_cache_descriptors == 0
        || config.maximum_topology_entries == 0
    {
        return Err(inventory_error(
            PlatformErrorCode::InvalidArgument,
            "standalone inventory bounds and configured cell classes are invalid",
        ));
    }
    let mut classes = config.cell_classes.clone();
    classes.sort_unstable();
    classes.dedup();
    if classes.len() != config.cell_classes.len() {
        return Err(inventory_error(
            PlatformErrorCode::InvalidArgument,
            "standalone inventory cell classes must be unique",
        ));
    }
    Ok(())
}

fn normalize_pressure(observation: NodePressureObservation) -> NodePressureObservation {
    NodePressureObservation {
        memory_pressure_milli: clamp_milli(observation.memory_pressure_milli),
        queue_pressure_milli: clamp_milli(observation.queue_pressure_milli),
        cache_pressure_milli: clamp_milli(observation.cache_pressure_milli),
        telemetry_pressure_milli: clamp_milli(observation.telemetry_pressure_milli),
    }
}

fn normalize_health(mut observation: NodeHealthObservation) -> NodeHealthObservation {
    observation.reasons.truncate(MAX_HEALTH_REASONS);
    for reason in &mut observation.reasons {
        *reason = bounded(reason, MAX_REASON_BYTES);
    }
    if !observation.healthy {
        observation.status = HealthStatus::Unhealthy;
        observation.ready = false;
    } else if !observation.ready && observation.status == HealthStatus::Healthy {
        observation.status = HealthStatus::Degraded;
    }
    observation
}

fn normalize_topology(topology: &mut NodeResourceTopology) {
    for entry in &mut topology.entries {
        entry.name = bounded(&entry.name, 128);
        entry.kind = bounded(&entry.kind, 64);
        entry.attributes = entry
            .attributes
            .iter()
            .take(16)
            .map(|(name, value)| (bounded(name, 64), bounded(value, 256)))
            .collect();
    }
}

fn clamp_milli(value: u32) -> u32 {
    value.min(1_000)
}

fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn bounded(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    value[..end].to_owned()
}

fn inventory_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_and_pressure_are_bounded() {
        let pressure = normalize_pressure(NodePressureObservation {
            memory_pressure_milli: 4_000,
            queue_pressure_milli: 2_000,
            cache_pressure_milli: 1_001,
            telemetry_pressure_milli: 1_000,
        });
        assert_eq!(pressure.memory_pressure_milli, 1_000);
        let health = normalize_health(NodeHealthObservation {
            status: HealthStatus::Healthy,
            ready: true,
            healthy: false,
            reasons: vec!["x".repeat(1_024); 128],
            observed_at_unix_millis: 1,
        });
        assert_eq!(health.status, HealthStatus::Unhealthy);
        assert!(!health.ready);
        assert_eq!(health.reasons.len(), MAX_HEALTH_REASONS);
        assert!(health
            .reasons
            .iter()
            .all(|reason| reason.len() <= MAX_REASON_BYTES));
    }
}
