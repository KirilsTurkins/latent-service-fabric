//! Fair activation scheduling, cell leasing, and placement interfaces.

#![forbid(unsafe_code)]

mod fixed_pool;

pub use fixed_pool::{
    FixedCellPool, FixedCellPoolConfig, FixedCellPoolTestTransition,
    FixedCellPoolTestTransitionKind,
};

use latent_activation::ActivationEnvelope;
use latent_core::{
    ActivationId, BoxFuture, CellId, ErrorDetail, Metadata, NodeId, PlatformError,
    PlatformErrorCode, ReleaseDigest, ResourceBudget, TenantId,
};
use std::sync::Arc;

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

/// Issuer-owned lifecycle capability for one affine cell lease.
///
/// A pool implementation retains the same `Arc` while the lease is active and
/// gives a clone to [`CellLease::new`]. This lets implementations outside this
/// crate observe abandoned and unaccepted leases without depending on
/// `FixedCellPool` internals.
pub trait CellLeaseLifecycle: Send + Sync {
    /// Handles an accepted lease dropped without release or quarantine.
    fn on_abandoned(&self);

    /// Handles a reserved lease delivered to an acquisition that never accepts it.
    ///
    /// The conservative default treats the unaccepted handoff as abandoned.
    fn on_unaccepted(&self) {
        self.on_abandoned();
    }
}

pub(crate) enum CellLeaseControl {
    Fixed(fixed_pool::LeaseControl),
    External(Arc<dyn CellLeaseLifecycle>),
}

/// One active, pool-managed cell assignment.
///
/// The lease is intentionally not cloneable. Consuming it through
/// [`CellPool::release`] or [`CellPool::quarantine`] establishes the only
/// reusable disposition. Dropping a live lease delegates to its issuer-owned
/// lifecycle capability, which should conservatively quarantine the slot.
#[must_use = "a cell lease must be released or quarantined"]
pub struct CellLease {
    pub id: CellId,
    pub activation_id: ActivationId,
    pub node: NodeId,
    pub class: CellClass,
    pub granted_budget: ResourceBudget,
    pub expires_at_unix_millis: u64,
    pub(crate) control: Option<CellLeaseControl>,
}

impl CellLease {
    /// Mints an affine lease for a `CellPool` implementation outside this crate.
    ///
    /// The issuer must retain the same lifecycle `Arc`. After atomically recording
    /// a successful release or quarantine, it disarms the lease with
    /// [`CellLease::disarm_lifecycle`].
    #[must_use]
    pub fn new(
        id: CellId,
        activation_id: ActivationId,
        node: NodeId,
        class: CellClass,
        granted_budget: ResourceBudget,
        expires_at_unix_millis: u64,
        lifecycle: Arc<dyn CellLeaseLifecycle>,
    ) -> Self {
        Self {
            id,
            activation_id,
            node,
            class,
            granted_budget,
            expires_at_unix_millis,
            control: Some(CellLeaseControl::External(lifecycle)),
        }
    }

    /// Disarms an externally minted lease with its exact issuer capability.
    ///
    /// A mismatched capability cannot disarm the lease. Implementations should
    /// call this only after recording the terminal disposition in their own state.
    #[must_use]
    pub fn disarm_lifecycle(&mut self, lifecycle: &Arc<dyn CellLeaseLifecycle>) -> bool {
        let matches = matches!(
            self.control.as_ref(),
            Some(CellLeaseControl::External(current)) if Arc::ptr_eq(current, lifecycle)
        );
        if matches {
            self.control = None;
        }
        matches
    }
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

/// Open execution-cell pool seam.
///
/// The original acquire, release, capacity, and availability methods remain the
/// required implementation surface. Phase 0 cancellation, quarantine, and rich
/// observations have conservative defaults so independent implementations remain
/// source-compatible at the trait boundary.
pub trait CellPool: Send + Sync {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>>;

    /// Acquires a cell using the already-resolved invocation deadline.
    ///
    /// New implementations that queue work must override this method so a
    /// caller's absolute deadline is observed while waiting.  The default
    /// preserves the original seam for independent Phase 0 implementations;
    /// the activation runner still checks the deadline before and after that
    /// call, but such an implementation cannot provide precise queued expiry.
    fn acquire_with_deadline<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
        _deadline_unix_millis: Option<u64>,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        self.acquire(activation_id, tenant, class, budget)
    }

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn capacity(&self, class: CellClass) -> u32;

    fn available(&self, class: CellClass) -> u32;

    fn cancel_waiting<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        let error = unsupported_pool_operation("cancel-waiting", Some(activation_id), None);
        Box::pin(async move { Err(error) })
    }

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        let error =
            unsupported_pool_operation("quarantine", Some(&lease.activation_id), Some(&reason));
        Box::pin(async move {
            drop(lease);
            Err(error)
        })
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        let capacity = self.capacity(class);
        let available = self.available(class);
        CellPoolSnapshot {
            class,
            capacity,
            available,
            queue_depth: 0,
            active_leases: capacity.saturating_sub(available),
            quarantined: 0,
        }
    }
}

fn unsupported_pool_operation(
    operation: &str,
    activation_id: Option<&ActivationId>,
    reason: Option<&str>,
) -> PlatformError {
    let mut fields = Metadata::new();
    fields.insert("operation".to_owned(), operation.to_owned());
    if let Some(activation_id) = activation_id {
        fields.insert("activation_id".to_owned(), activation_id.0.clone());
    }
    if let Some(reason) = reason {
        fields.insert("reason".to_owned(), reason.to_owned());
    }
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: format!("cell-pool implementation does not support {operation}"),
        retryable: false,
        details: vec![ErrorDetail {
            kind: "cell-pool.unsupported-operation".to_owned(),
            fields,
        }],
    }
}

pub trait ClusterPlacement: Send + Sync {
    fn place<'a>(
        &'a self,
        request: &'a SchedulingRequest,
        candidates: &'a [NodeCandidate],
    ) -> BoxFuture<'a, Result<PlacementDecision, PlatformError>>;
}
