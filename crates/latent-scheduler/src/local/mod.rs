//! One node's fair queue above the fixed cell-pool ownership seam.

mod assignment;
mod state;

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_admission::{AdmissionPermit, LocalQuotaProvider};
use latent_core::{
    ActivationId, BoxFuture, ErrorDetail, Metadata, NodeId, PlatformError, PlatformErrorCode,
};
use tokio::sync::oneshot;

use crate::{
    ActivationScheduler, CellClass, CellPool, ClusterPlacement, FixedCellPool, FixedCellPoolConfig,
    NodeCandidate, PlacementDecision, SchedulingRequest,
};
use assignment::PendingAssignment;
pub use assignment::ScheduledActivation;
use state::{ClassState, Entry, Inner, Registration, State, WaitRegistration};

/// Capability supplied by the activation lifecycle owner. Implementations must
/// observe and request cancellation in that owner's existing registry, with
/// durable wakeup semantics; the scheduler creates no cancellation registry.
pub trait SchedulingCancellation: Send + Sync {
    fn activation_id(&self) -> &ActivationId;
    fn is_cancelled(&self) -> bool;
    /// True only when this request first installs cancellation.
    fn request_cancellation(&self) -> bool;
    fn cancelled(&self) -> BoxFuture<'_, ()>;
}

/// Consumes exactly one admission reservation and its matching cancellation
/// capability. All scheduling policy is derived from the immutable permit.
pub struct AdmittedSchedulingRequest {
    pub permit: AdmissionPermit,
    pub cancellation: Arc<dyn SchedulingCancellation>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalSchedulerConfig {
    pub node: NodeId,
    /// Exact finite queue bounds. Each configured admission class must appear;
    /// zero denies scheduling in that class, including immediate dispatch.
    pub queue_capacity_per_class: BTreeMap<CellClass, u32>,
    /// Within a tenant's turn, requests older than this threshold run in FIFO
    /// order before newer high-priority requests. Must be positive.
    pub starvation_after: Duration,
}

/// Bounded observations of one fixed class; no service metadata is inspected.
/// Queue and pool values are individually coherent, not an atomic cross-layer
/// transaction. Counters saturate and retain no activation/tenant history.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SchedulerSnapshot {
    pub capacity: u32,
    pub available: u32,
    pub active_leases: u32,
    pub quarantined: u32,
    pub queue_depth: u32,
    pub queued_tenants: u32,
    pub rejected: u64,
    pub cancellations: u64,
    pub expired: u64,
    pub granted: u64,
    pub total_wait_micros: u64,
    pub max_wait_micros: u64,
    pub oldest_lease_age_micros: u64,
}

/// Shared node scheduler. Enqueue futures cooperatively dispatch work on their
/// caller's async runtime; no dispatcher task, thread, or service worker is
/// spawned. Every pool change uses a bounded coalescing watch notification.
#[derive(Clone)]
pub struct LocalScheduler {
    inner: Arc<Inner>,
}

impl LocalScheduler {
    /// Builds exactly the class capacities configured in the admission ledger.
    /// The legacy pool FIFO is disabled: this scheduler owns the only wait queue.
    pub fn new(
        config: LocalSchedulerConfig,
        quotas: LocalQuotaProvider,
    ) -> Result<Self, PlatformError> {
        validate_config(&config, &quotas)?;
        let pools = quotas
            .policy()
            .cell_classes
            .iter()
            .map(|(name, policy)| {
                let class = class_named(name).expect("validated admission class");
                let pool = FixedCellPool::new(FixedCellPoolConfig::new(
                    config.node.clone(),
                    class,
                    policy.parallelism,
                    0,
                ))?;
                Ok((class, Arc::new(pool) as Arc<dyn CellPool>))
            })
            .collect::<Result<_, PlatformError>>()?;
        Self::with_pools(config, quotas, pools)
    }

    /// Supplies node-owned pools implementing the nonqueueing/change seam.
    /// Pools must exclusively serve this scheduler, match the configured node
    /// and capabilities, and preserve affine issuer-owned cleanup semantics.
    pub fn with_pools(
        config: LocalSchedulerConfig,
        quotas: LocalQuotaProvider,
        pools: BTreeMap<CellClass, Arc<dyn CellPool>>,
    ) -> Result<Self, PlatformError> {
        validate_config(&config, &quotas)?;
        if pools.len() != config.queue_capacity_per_class.len() {
            return Err(error(PlatformErrorCode::InvalidArgument, "pool-topology"));
        }
        for (name, policy) in &quotas.policy().cell_classes {
            let class = class_named(name).expect("validated admission class");
            let pool = pools
                .get(&class)
                .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "pool-topology"))?;
            let snapshot = pool.observations(class);
            if snapshot.class != class
                || snapshot.capacity != policy.parallelism
                || snapshot.available != snapshot.capacity
                || snapshot.active_leases != 0
                || snapshot.queue_depth != 0
                || snapshot.quarantined != 0
                || pool.subscribe_changes().is_none()
            {
                return Err(error(PlatformErrorCode::InvalidArgument, "pool-topology"));
            }
        }
        let classes = config
            .queue_capacity_per_class
            .keys()
            .copied()
            .map(|class| (class, ClassState::default()))
            .collect();
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                quotas,
                pools,
                dispatch: Mutex::new(()),
                state: Mutex::new(State {
                    classes,
                    live: BTreeMap::new(),
                    next_sequence: 1,
                    shutdown: false,
                }),
            }),
        })
    }

    #[must_use]
    pub fn observations(&self, class: CellClass) -> SchedulerSnapshot {
        self.inner.observations(class)
    }

    /// Settles all queued waiters and refunds their permits. Execution-owned
    /// assignments retain their cell and quotas until cleanup/disposition.
    pub fn shutdown(&self) {
        self.inner.shutdown();
    }

    async fn enqueue_owned(
        &self,
        request: AdmittedSchedulingRequest,
    ) -> Result<ScheduledActivation, PlatformError> {
        let class = class_named(&request.permit.obligations().cell_class)
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "cell-class"))?;
        if let Err(error) = self.validate_request(&request) {
            self.inner.record_error(class, &error);
            return Err(error);
        }
        let pool = self
            .inner
            .pools
            .get(&class)
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "cell-class"))?;
        // Subscribe BEFORE registration/dispatch to close the release/observe race.
        let mut changes = pool
            .subscribe_changes()
            .ok_or_else(|| error(PlatformErrorCode::Unavailable, "pool-changes-closed"))?;
        let id = request.permit.activation_id().clone();
        let cancellation = Arc::clone(&request.cancellation);
        let deadline = request.permit.deadline().monotonic();
        let (sender, mut receiver) = oneshot::channel();
        let sequence = self.register_request(class, request, sender)?;
        let mut registration = WaitRegistration::new(Arc::clone(&self.inner), id, sequence);
        let timeout = async move {
            if let Some(deadline) = deadline {
                tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)).await;
            } else {
                std::future::pending::<()>().await;
            }
        };
        tokio::pin!(timeout);
        loop {
            let dispatched = self.inner.pump(class);
            tokio::select! {
                biased;
                () = cancellation.cancelled() => {
                    registration.remove(PlatformErrorCode::Cancelled);
                    return Err(error(PlatformErrorCode::Cancelled, "cancelled"));
                }
                () = &mut timeout => {
                    registration.remove(PlatformErrorCode::DeadlineExceeded);
                    return Err(error(PlatformErrorCode::DeadlineExceeded, "deadline-exceeded"));
                }
                outcome = &mut receiver => {
                    registration.disarm();
                    return match outcome {
                        Ok(Ok(pending)) => pending.accept(),
                        Ok(Err(error)) => Err(error),
                        Err(_) => Err(error(PlatformErrorCode::Unavailable, "handoff-closed")),
                    };
                }
                // A contended or exhausted dispatch pass retries cooperatively,
                // while cancellation and deadlines retain select priority.
                () = tokio::task::yield_now(), if !dispatched => {}
                notification = changes.changed() => {
                    if notification.is_err() {
                        return Err(error(PlatformErrorCode::Unavailable, "pool-changes-closed"));
                    }
                }
            }
        }
    }

    fn validate_request(&self, request: &AdmittedSchedulingRequest) -> Result<(), PlatformError> {
        if !request.permit.is_reserved_by(&self.inner.quotas) {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "foreign-admission",
            ));
        }
        if request.cancellation.activation_id() != request.permit.activation_id() {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "cancellation-identity",
            ));
        }
        if request.cancellation.is_cancelled() {
            return Err(error(PlatformErrorCode::Cancelled, "cancelled"));
        }
        request.permit.ensure_schedulable_at(now())
    }

    /// Atomically admits the waiter into the bounded class queue. The caller
    /// must subscribe to pool changes before registering any work.
    fn register_request(
        &self,
        class: CellClass,
        request: AdmittedSchedulingRequest,
        sender: oneshot::Sender<Result<PendingAssignment, PlatformError>>,
    ) -> Result<u64, PlatformError> {
        let mut state = self.inner.lock();
        if state.shutdown {
            return Err(error(PlatformErrorCode::Unavailable, "shutdown"));
        }
        let id = request.permit.activation_id();
        if state.live.contains_key(id) {
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "duplicate-activation",
            ));
        }
        let queue = state.classes.get_mut(&class).expect("configured class");
        if queue.depth >= self.inner.config.queue_capacity_per_class[&class] {
            queue.counters.rejected = queue.counters.rejected.saturating_add(1);
            return Err(error(PlatformErrorCode::ResourceExhausted, "queue-full"));
        }
        let sequence = state.next_sequence;
        state.next_sequence = sequence
            .checked_add(1)
            .ok_or_else(|| error(PlatformErrorCode::Unavailable, "sequence-exhausted"))?;
        state.live.insert(
            id.clone(),
            Registration {
                sequence,
                class,
                cancellation: Arc::clone(&request.cancellation),
                assigned_at: None,
                cancellation_counted: false,
                failure_counted: false,
            },
        );
        state
            .classes
            .get_mut(&class)
            .expect("configured class")
            .push(Entry {
                sequence,
                request,
                enqueued_at: now(),
                sender,
            });
        Ok(sequence)
    }
}

impl ActivationScheduler for LocalScheduler {
    fn enqueue(
        &self,
        request: AdmittedSchedulingRequest,
    ) -> BoxFuture<'_, Result<ScheduledActivation, PlatformError>> {
        Box::pin(self.enqueue_owned(request))
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let (cancellation, sequence) = {
                let state = self.inner.lock();
                let entry = state
                    .live
                    .get(activation_id)
                    .ok_or_else(|| error(PlatformErrorCode::NotFound, "activation-not-found"))?;
                (Arc::clone(&entry.cancellation), entry.sequence)
            };
            // Delegate to the upstream owner, never free a running lease here.
            if cancellation.request_cancellation() {
                self.inner.record_cancellation(activation_id, sequence);
            }
            Ok(())
        })
    }
}

fn validate_config(
    config: &LocalSchedulerConfig,
    quotas: &LocalQuotaProvider,
) -> Result<(), PlatformError> {
    if config.node.0.is_empty()
        || config.node.0.len() > quotas.policy().maximum_identifier_bytes
        || config
            .node
            .0
            .chars()
            .any(|c| c.is_whitespace() || c.is_control())
        || config.starvation_after.is_zero()
        || config.queue_capacity_per_class.len() != quotas.policy().cell_classes.len()
        || quotas.policy().cell_classes.keys().any(|name| {
            !class_named(name)
                .is_some_and(|class| config.queue_capacity_per_class.contains_key(&class))
        })
    {
        return Err(error(PlatformErrorCode::InvalidArgument, "configuration"));
    }
    Ok(())
}

fn class_named(name: &str) -> Option<CellClass> {
    match name {
        "tiny" => Some(CellClass::Tiny),
        "small" => Some(CellClass::Small),
        "standard" => Some(CellClass::Standard),
        "large" => Some(CellClass::Large),
        "extra-large" => Some(CellClass::ExtraLarge),
        _ => None,
    }
}

fn now() -> Instant {
    tokio::time::Instant::now().into_std()
}

fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: "local scheduling could not proceed".to_owned(),
        retryable: matches!(
            code,
            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::Unavailable
        ),
        details: vec![ErrorDetail {
            kind: "scheduler.limit".to_owned(),
            fields: Metadata::from([("reason".to_owned(), reason.to_owned())]),
        }],
    }
}

/// Phase 1 placement selects only the configured local node. The existing seam
/// remains open for future cluster placement; candidate metadata grants no policy.
#[derive(Debug, Clone)]
pub struct LocalNodePlacement {
    node: NodeId,
}

impl LocalNodePlacement {
    #[must_use]
    pub const fn new(node: NodeId) -> Self {
        Self { node }
    }
}

impl ClusterPlacement for LocalNodePlacement {
    fn place<'a>(
        &'a self,
        _request: &'a SchedulingRequest,
        candidates: &'a [NodeCandidate],
    ) -> BoxFuture<'a, Result<PlacementDecision, PlatformError>> {
        Box::pin(async move {
            let local = candidates
                .iter()
                .find(|candidate| candidate.node == self.node)
                .ok_or_else(|| error(PlatformErrorCode::Unavailable, "local-node-unavailable"))?;
            Ok(PlacementDecision {
                selected_node: self.node.clone(),
                considered: vec![local.clone()],
                policy_digest: "local-node-v1".to_owned(),
            })
        })
    }
}
