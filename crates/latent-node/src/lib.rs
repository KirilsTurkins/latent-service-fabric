//! Node identity, inventory, route watching, registration, health, and activation orchestration.

#![forbid(unsafe_code)]

mod activation_runner;
mod budgeted_activation;
mod cancellation;

use latent_artifacts::CacheEntryDescriptor;
use latent_core::{BoxFuture, Metadata, NodeId, PlatformError, RouteGeneration};
use latent_routing::RouteSnapshot;

pub use activation_runner::{
    ActivationRunnerSnapshot, Phase0ActivationRunner, Phase0ActivationRunnerConfig,
};
pub use budgeted_activation::{
    ActivationBudgetPolicy, ActivationBudgetRegistry, ActivationBudgetRegistrySnapshot,
    ActivationClock, BudgetedActivationManager, SystemActivationClock,
};
pub use cancellation::{
    ActivationCancellationRegistry, CancellationHandle, CancellationRegistration,
    CancellationRegistrySnapshot, CancellationToken,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CellClassCapacity {
    pub class: String,
    pub total: u32,
    pub available: u32,
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInventory {
    pub node: NodeDescriptor,
    pub cell_capacity: Vec<CellClassCapacity>,
    pub memory_pressure_milli: u32,
    pub queue_depth: u64,
    pub route_generation: RouteGeneration,
    pub cache_entries: Vec<CacheEntryDescriptor>,
    pub observed_at_unix_millis: u64,
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
