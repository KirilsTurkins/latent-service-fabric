//! Node composition, inventory, activation orchestration, and shared observability adapters.

#![forbid(unsafe_code)]

mod activation_runner;
mod inventory;
mod observability;

pub use activation_runner::{
    ActivationRunnerSnapshot, Phase0ActivationRunner, Phase0ActivationRunnerConfig,
};
pub use inventory::{
    CacheInventorySource, CellClassCapacity, EmptyCacheInventorySource, EmptyNodeTopologySource,
    HealthStatus, InventoryReporter, MemoryPressureSource, MutableNodeHealthSource,
    NodeCacheSummary, NodeDescriptor, NodeDirectory, NodeHealthObservation, NodeHealthSource,
    NodeHeartbeat, NodeInventory, NodePressureObservation, NodeRegistrar, NodeResourceTopology,
    NodeTopologyEntry, NodeTopologySource, ResourceOwnership, RouteGenerationSource, RouteWatcher,
    StandaloneInventoryConfig, StandaloneInventoryReporter, StaticMemoryPressureSource,
    StaticRouteGenerationSource,
};
pub use observability::{
    GuestLogSource, ObservedActivationManager, ObservedCellPool, ObservedExecutionBackend,
};
