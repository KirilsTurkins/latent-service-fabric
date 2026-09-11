//! Node identity, inventory, route watching, registration, health, and activation orchestration.

#![forbid(unsafe_code)]

mod activation_manager;
mod activation_runner;
mod budgeted_activation;
mod budgeted_execution;
mod cancellation;
mod inventory;
mod journal;

use latent_core::{BoxFuture, Metadata, NodeId, PlatformError, RouteGeneration};
use latent_routing::RouteSnapshot;

pub use activation_manager::{
    ActivationHandle, ActivationObservationSnapshot, ActivationReceipt,
    ActivationTransportInterruption, LocalActivationDependencies, LocalActivationManager,
    LocalActivationManagerConfig, LocalActivationServices,
};
pub use activation_runner::{
    ActivationRunnerSnapshot, Phase0ActivationRunner, Phase0ActivationRunnerConfig,
};
pub use budgeted_activation::{
    ActivationBudgetPolicy, ActivationBudgetRegistry, ActivationBudgetRegistrySnapshot,
    ActivationClock, BudgetedActivationManager, SystemActivationClock,
};
pub use budgeted_execution::BudgetedExecutionBackend;
pub use cancellation::{
    ActivationCancellationRegistry, CancellationHandle, CancellationRegistration,
    CancellationRegistrySnapshot, CancellationToken,
};
pub use journal::{
    ActivationJournalSnapshot, LocalActivationJournal, LocalActivationJournalConfig,
};

pub use inventory::{
    CacheInventorySource, CacheInventoryWriter, CellClassCapacity, EmptyCacheInventorySource,
    EmptyNodeTopologySource, HealthStatus, InventoryReporter, NodeCacheSummary, NodeDescriptor,
    NodeHealthObservation, NodeInventory, NodePressureObservation, NodeQuotaSummary,
    NodeResourceTopology, NodeTopologyEntry, NodeTopologySource, NodeTopologyWriter,
    ResourceOwnership, SchedulerInventorySnapshot, SchedulerInventorySource,
    StandaloneInventoryConfig, StandaloneInventoryReporter, StandaloneInventorySources,
};

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
