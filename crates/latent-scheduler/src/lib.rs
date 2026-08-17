//! Fair activation scheduling, cell leasing, and placement interfaces.

#![forbid(unsafe_code)]

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CellLease {
    pub id: CellId,
    pub activation_id: ActivationId,
    pub node: NodeId,
    pub class: CellClass,
    pub granted_budget: ResourceBudget,
    pub expires_at_unix_millis: u64,
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

    fn capacity(&self, class: CellClass) -> u32;
    fn available(&self, class: CellClass) -> u32;
}

pub trait ClusterPlacement: Send + Sync {
    fn place<'a>(
        &'a self,
        request: &'a SchedulingRequest,
        candidates: &'a [NodeCandidate],
    ) -> BoxFuture<'a, Result<PlacementDecision, PlatformError>>;
}
