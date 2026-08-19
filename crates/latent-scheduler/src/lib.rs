//! Fair activation scheduling, cell leasing, and placement interfaces.

#![forbid(unsafe_code)]

mod fixed_pool;

pub use fixed_pool::{FixedCellPool, FixedCellPoolConfig};

use latent_activation::ActivationEnvelope;
use latent_core::{
    ActivationId, BoxFuture, CellId, Metadata, NodeId, PlatformError, ReleaseDigest, ResourceBudget,
    TenantId,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CellClass {
    Tiny,
    Small,
    Standard,
    Large,
    ExtraLarge,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchedulingRequest {
    pub envelope: ActivationEnvelope,
    pub trust_class: String,
    pub cell_class: CellClass,
    pub artifact_locality: Option<ReleaseDigest>,
    pub state_affinity_key: Option<String>,
    pub required_features: Vec<String>,
}

/// One active, pool-managed cell assignment.
///
/// The lease is intentionally not cloneable. Consuming it through `CellPool::release`
/// or `CellPool::quarantine` establishes the only reusable disposition. Dropping a
/// live lease without either operation conservatively quarantines its generic slot.
#[must_use = "a cell lease must be released or quarantined"]
pub struct CellLease {
    pub id: CellId,
    pub activation_id: ActivationId,
    pub node: NodeId,
    pub class: CellClass,
    pub granted_budget: ResourceBudget,
    pub expires_at_unix_millis: u64,
    control: Option<fixed_pool::LeaseControl>,
}

/// Constant-time observations exported by a cell pool to the spike harness.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CellPoolSnapshot {
    pub class: CellClass,
    pub capacity: u32,
    pub available: u32,
    pub queue_depth: u32,
    pub active_leases: u32,
    pub quarantined: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeCandidate {
    pub node: NodeId,
    pub queue_delay_micros: u64,
    pub artifact_cached: bool,
    pub state_affinity: bool,
    pub available_cells: u32,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlacementDecision {
    pub selected_node: NodeId,
    pub considered: Vec<NodeCandidate>,
    pub policy_digest: String,
}

pub trait ActivationScheduler: Send + Sync {
    fn enqueue<'a>(
        &'a self,
        request: SchedulingRequest,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>>;

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait CellPool: Send + Sync {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>>;

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn cancel_waiting<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn observations(&self, class: CellClass) -> CellPoolSnapshot;

    fn capacity(&self, class: CellClass) -> u32 {
        self.observations(class).capacity
    }

    fn available(&self, class: CellClass) -> u32 {
        self.observations(class).available
    }
}

pub trait ClusterPlacement: Send + Sync {
    fn place<'a>(
        &'a self,
        request: &'a SchedulingRequest,
        candidates: &'a [NodeCandidate],
    ) -> BoxFuture<'a, Result<PlacementDecision, PlatformError>>;
}
