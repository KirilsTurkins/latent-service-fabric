use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_admission::LocalQuotaProvider;
use latent_core::{ActivationId, PlatformError, PlatformErrorCode, TenantId};
use tokio::sync::oneshot;

use super::assignment::{ActiveRegistration, PendingAssignment};
use super::{
    error, micros, now, AdmittedSchedulingRequest, CellClass, CellPool, LocalSchedulerConfig,
    SchedulerSnapshot, SchedulingCancellation,
};

pub(super) struct Inner {
    pub config: LocalSchedulerConfig,
    pub quotas: LocalQuotaProvider,
    pub pools: BTreeMap<CellClass, Arc<dyn CellPool>>,
    pub state: Mutex<State>,
    pub dispatch: Mutex<()>,
}

pub(super) struct State {
    pub classes: BTreeMap<CellClass, ClassState>,
    pub live: BTreeMap<ActivationId, Registration>,
    pub next_sequence: u64,
    pub shutdown: bool,
}

pub(super) struct Registration {
    pub sequence: u64,
    pub class: CellClass,
    pub cancellation: Arc<dyn SchedulingCancellation>,
    pub assigned_at: Option<Instant>,
    pub cancellation_counted: bool,
    pub failure_counted: bool,
}

pub(super) struct Entry {
    pub sequence: u64,
    pub request: AdmittedSchedulingRequest,
    pub enqueued_at: Instant,
    pub sender: oneshot::Sender<Result<PendingAssignment, PlatformError>>,
}

struct TenantQueue {
    tenant: TenantId,
    entries: Vec<Entry>,
}

#[derive(Default)]
pub(super) struct ClassState {
    tenants: VecDeque<TenantQueue>,
    pub depth: u32,
    pub counters: SchedulerSnapshot,
    pub active_since: BTreeSet<(Instant, u64)>,
}

impl ClassState {
    pub fn push(&mut self, entry: Entry) {
        self.depth += 1;
        let tenant = entry.request.permit.tenant();
        if let Some(queue) = self
            .tenants
            .iter_mut()
            .find(|queue| &queue.tenant == tenant)
        {
            queue.entries.push(entry);
        } else {
            self.tenants.push_back(TenantQueue {
                tenant: tenant.clone(),
                entries: vec![entry],
            });
        }
    }

    fn select(&mut self, now: Instant, starvation_after: std::time::Duration) -> Option<Entry> {
        let tenant = self.tenants.front_mut()?;
        let index = tenant
            .entries
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| {
                let a_old = now.saturating_duration_since(a.enqueued_at) >= starvation_after;
                let b_old = now.saturating_duration_since(b.enqueued_at) >= starvation_after;
                match (a_old, b_old) {
                    (true, true) => a.sequence.cmp(&b.sequence),
                    (true, false) => Ordering::Less,
                    (false, true) => Ordering::Greater,
                    (false, false) => b
                        .request
                        .permit
                        .obligations()
                        .priority
                        .cmp(&a.request.permit.obligations().priority)
                        .then_with(|| deadline_order(a, b))
                        .then_with(|| a.sequence.cmp(&b.sequence)),
                }
            })
            .map(|(index, _)| index)
            .expect("tenant queues are nonempty");
        let entry = tenant.entries.remove(index);
        // This slot remains reserved while the open pool seam is called. A
        // concurrent enqueue must not consume it before a failed try restores it.
        if tenant.entries.is_empty() {
            self.tenants.pop_front();
        }
        Some(entry)
    }

    fn rotate_after_grant(&mut self, tenant: &TenantId) {
        if let Some(index) = self
            .tenants
            .iter()
            .position(|queue| &queue.tenant == tenant)
        {
            let queue = self.tenants.remove(index).expect("located tenant");
            self.tenants.push_back(queue);
        }
    }

    fn restore(&mut self, entry: Entry) {
        let tenant = entry.request.permit.tenant().clone();
        self.depth -= 1; // restore the already-reserved slot
        self.push(entry);
        if let Some(index) = self.tenants.iter().position(|queue| queue.tenant == tenant) {
            let queue = self.tenants.remove(index).expect("located tenant");
            self.tenants.push_front(queue);
        }
    }

    fn remove(&mut self, sequence: u64) -> Option<Entry> {
        let (tenant_index, entry_index) =
            self.tenants
                .iter()
                .enumerate()
                .find_map(|(index, tenant)| {
                    tenant
                        .entries
                        .iter()
                        .position(|entry| entry.sequence == sequence)
                        .map(|entry| (index, entry))
                })?;
        let tenant = &mut self.tenants[tenant_index];
        let entry = tenant.entries.remove(entry_index);
        self.depth -= 1;
        if tenant.entries.is_empty() {
            self.tenants.remove(tenant_index);
        }
        Some(entry)
    }

    fn count_error(&mut self, code: PlatformErrorCode, cancellation_counted: bool) {
        self.counters.rejected = self.counters.rejected.saturating_add(1);
        if code == PlatformErrorCode::Cancelled && !cancellation_counted {
            self.counters.cancellations = self.counters.cancellations.saturating_add(1);
        }
        if code == PlatformErrorCode::DeadlineExceeded {
            self.counters.expired = self.counters.expired.saturating_add(1);
        }
    }
}

fn deadline_order(a: &Entry, b: &Entry) -> Ordering {
    match (
        a.request.permit.deadline().monotonic(),
        b.request.permit.deadline().monotonic(),
    ) {
        (Some(a), Some(b)) => a.cmp(&b),
        (None, Some(_)) => Ordering::Greater,
        (Some(_), None) => Ordering::Less,
        (None, None) => Ordering::Equal,
    }
}

impl Inner {
    pub fn lock(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn observations(&self, class: CellClass) -> SchedulerSnapshot {
        let mut snapshot = {
            let state = self.lock();
            let Some(queue) = state.classes.get(&class) else {
                return SchedulerSnapshot::default();
            };
            let mut snapshot = queue.counters;
            snapshot.queue_depth = queue.depth;
            snapshot.queued_tenants = u32::try_from(queue.tenants.len()).unwrap_or(u32::MAX);
            snapshot.oldest_lease_age_micros =
                queue.active_since.first().map_or(0, |(started, _)| {
                    micros(now().saturating_duration_since(*started))
                });
            snapshot
        };
        if let Some(pool) = self.pools.get(&class) {
            let pool = pool.observations(class);
            snapshot.capacity = pool.capacity;
            snapshot.available = pool.available;
            snapshot.active_leases = pool.active_leases;
            snapshot.quarantined = pool.quarantined;
        }
        snapshot
    }

    pub fn record_error(&self, class: CellClass, error: &PlatformError) {
        if let Some(queue) = self.lock().classes.get_mut(&class) {
            queue.count_error(error.code, false);
        }
    }

    pub fn record_cancellation(&self, id: &ActivationId, sequence: u64) {
        let mut state = self.lock();
        let Some(registration) = state.live.get_mut(id) else {
            return;
        };
        if registration.sequence != sequence || registration.cancellation_counted {
            return;
        }
        registration.cancellation_counted = true;
        let class = registration.class;
        let queue = state.classes.get_mut(&class).expect("registered class");
        queue.counters.cancellations = queue.counters.cancellations.saturating_add(1);
    }

    pub fn record_failure(&self, id: &ActivationId, sequence: u64, code: PlatformErrorCode) {
        let mut state = self.lock();
        let Some(registration) = state.live.get_mut(id) else {
            return;
        };
        if registration.sequence != sequence || registration.failure_counted {
            return;
        }
        registration.failure_counted = true;
        let counted = registration.cancellation_counted;
        registration.cancellation_counted |= code == PlatformErrorCode::Cancelled;
        let class = registration.class;
        state
            .classes
            .get_mut(&class)
            .expect("registered class")
            .count_error(code, counted);
    }

    pub fn remove_queued(&self, id: &ActivationId, sequence: u64, code: PlatformErrorCode) {
        self.record_failure(id, sequence, code);
        let removed = {
            let mut state = self.lock();
            if !state
                .live
                .get(id)
                .is_some_and(|entry| entry.sequence == sequence && entry.assigned_at.is_none())
            {
                return;
            }
            let registration = state.live.remove(id).expect("matched registration");
            let queue = state
                .classes
                .get_mut(&registration.class)
                .expect("registered class");
            let removed = queue.remove(sequence);
            if removed.is_none() {
                queue.depth -= 1; // currently selected by the synchronous pump
            }
            removed
        };
        // Permit destruction takes the quota mutex: never do it under our state lock.
        drop(removed);
    }

    pub fn finish_active(&self, id: &ActivationId, sequence: u64) {
        let mut state = self.lock();
        if state
            .live
            .get(id)
            .is_none_or(|entry| entry.sequence != sequence)
        {
            return;
        }
        let entry = state.live.remove(id).expect("matched registration");
        if let Some(started) = entry.assigned_at {
            state
                .classes
                .get_mut(&entry.class)
                .expect("registered class")
                .active_since
                .remove(&(started, sequence));
        }
    }

    pub fn pump(self: &Arc<Self>, class: CellClass) -> bool {
        // Only one synchronous pump runs at a time. Reentrant callers simply
        // leave work to it; this mutex is never awaited or acquired blocking.
        let Ok(_dispatch) = self.dispatch.try_lock() else {
            return false;
        };
        let Some(pool) = self.pools.get(&class) else {
            return true;
        };
        for _ in 0..64 {
            let snapshot = pool.observations(class);
            if snapshot.available == 0 && snapshot.quarantined != snapshot.capacity {
                return true;
            }
            let entry = {
                let mut state = self.lock();
                if state.shutdown {
                    return true;
                }
                state
                    .classes
                    .get_mut(&class)
                    .expect("configured class")
                    .select(now(), self.config.starvation_after)
            };
            let Some(entry) = entry else {
                return true;
            };
            if entry.sender.is_closed() || entry.request.cancellation.is_cancelled() {
                self.finish_error(entry, error(PlatformErrorCode::Cancelled, "cancelled"));
                continue;
            }
            if let Err(error) = entry.request.permit.ensure_schedulable_at(now()) {
                self.finish_error(entry, error);
                continue;
            }
            if snapshot.quarantined == snapshot.capacity {
                self.finish_error(
                    entry,
                    error(PlatformErrorCode::Unavailable, "all-cells-quarantined"),
                );
                continue;
            }
            // No state lock is held across the open pool/cancellation seams.
            let acquired = pool.try_acquire_now(
                entry.request.permit.activation_id(),
                entry.request.permit.tenant(),
                class,
                entry.request.permit.granted_budget(),
                None,
            );
            let lease = match acquired {
                Ok(Some(lease)) => lease,
                Ok(None) => {
                    let mut state = self.lock();
                    let live = state
                        .live
                        .get(entry.request.permit.activation_id())
                        .is_some_and(|registration| registration.sequence == entry.sequence);
                    if live && !state.shutdown {
                        state
                            .classes
                            .get_mut(&class)
                            .expect("configured class")
                            .restore(entry);
                        return true;
                    }
                    let shutting_down = state.shutdown;
                    drop(state);
                    self.finish_error(
                        entry,
                        if shutting_down {
                            error(PlatformErrorCode::Unavailable, "shutdown")
                        } else {
                            error(PlatformErrorCode::Cancelled, "cancelled")
                        },
                    );
                    continue;
                }
                Err(error) => {
                    self.finish_error(entry, error);
                    continue;
                }
            };
            self.deliver_assignment(class, entry, lease);
        }
        false // bounded pass exhausted; caller yields with cancellation enabled
    }

    fn deliver_assignment(
        self: &Arc<Self>,
        class: CellClass,
        entry: Entry,
        lease: crate::CellLease,
    ) {
        let id = entry.request.permit.activation_id().clone();
        if lease.activation_id != id
            || lease.class != class
            || lease.node != self.config.node
            || &lease.granted_budget != entry.request.permit.granted_budget()
        {
            // A malformed issuer response is never marked reusable.
            drop(lease);
            self.finish_error(
                entry,
                error(PlatformErrorCode::Internal, "pool-lease-mismatch"),
            );
            return;
        }
        let assigned = now();
        let (registered, shutting_down) = {
            let mut state = self.lock();
            let live = !state.shutdown
                && state
                    .live
                    .get(&id)
                    .is_some_and(|registration| registration.sequence == entry.sequence);
            if live {
                state
                    .live
                    .get_mut(&id)
                    .expect("matched registration")
                    .assigned_at = Some(assigned);
                let queue = state.classes.get_mut(&class).expect("configured class");
                queue.depth -= 1;
                queue.active_since.insert((assigned, entry.sequence));
                queue.rotate_after_grant(entry.request.permit.tenant());
            }
            (live, state.shutdown)
        };
        let pending = PendingAssignment::new(
            lease,
            entry.request.permit,
            entry.request.cancellation,
            ActiveRegistration::new(Arc::clone(self), id, class, entry.sequence),
            entry.enqueued_at,
        );
        if !registered {
            drop(pending);
            let _ = entry.sender.send(Err(if shutting_down {
                error(PlatformErrorCode::Unavailable, "shutdown")
            } else {
                error(PlatformErrorCode::Cancelled, "cancelled")
            }));
            return;
        }
        // A receiver which disappears now drops the unaccepted capability,
        // synchronously returning the untouched cell and quota reservation.
        let _ = entry.sender.send(Ok(pending));
    }

    fn finish_error(&self, entry: Entry, error: PlatformError) {
        {
            let mut state = self.lock();
            let id = entry.request.permit.activation_id();
            if state
                .live
                .get(id)
                .is_some_and(|registration| registration.sequence == entry.sequence)
            {
                let registration = state.live.remove(id).expect("matched registration");
                let queue = state
                    .classes
                    .get_mut(&registration.class)
                    .expect("registered class");
                queue.depth -= 1;
                if !registration.failure_counted {
                    queue.count_error(error.code, registration.cancellation_counted);
                }
            }
        }
        drop(entry.request);
        let _ = entry.sender.send(Err(error));
    }

    pub fn record_grant(&self, class: CellClass, enqueued: Instant) {
        let wait = micros(now().saturating_duration_since(enqueued));
        let mut state = self.lock();
        let counters = &mut state
            .classes
            .get_mut(&class)
            .expect("configured class")
            .counters;
        counters.granted = counters.granted.saturating_add(1);
        counters.total_wait_micros = counters.total_wait_micros.saturating_add(wait);
        counters.max_wait_micros = counters.max_wait_micros.max(wait);
    }

    pub fn shutdown(&self) {
        let entries = {
            let mut state = self.lock();
            state.shutdown = true;
            let mut entries = Vec::new();
            for queue in state.classes.values_mut() {
                for tenant in queue.tenants.drain(..) {
                    entries.extend(tenant.entries);
                }
                queue.depth = 0;
            }
            let queued: Vec<_> = state
                .live
                .iter()
                .filter(|(_, entry)| entry.assigned_at.is_none())
                .map(|(id, _)| id.clone())
                .collect();
            for id in queued {
                let entry = state.live.remove(&id).expect("collected registration");
                if !entry.failure_counted {
                    state
                        .classes
                        .get_mut(&entry.class)
                        .expect("registered class")
                        .count_error(PlatformErrorCode::Unavailable, entry.cancellation_counted);
                }
            }
            entries
        };
        for entry in entries {
            self.finish_error(entry, error(PlatformErrorCode::Unavailable, "shutdown"));
        }
    }
}

pub(super) struct WaitRegistration {
    owner: Arc<Inner>,
    id: ActivationId,
    sequence: u64,
    armed: bool,
}

impl WaitRegistration {
    pub fn new(owner: Arc<Inner>, id: ActivationId, sequence: u64) -> Self {
        Self {
            owner,
            id,
            sequence,
            armed: true,
        }
    }
    pub fn disarm(&mut self) {
        self.armed = false;
    }
    pub fn remove(&mut self, code: PlatformErrorCode) {
        self.owner.remove_queued(&self.id, self.sequence, code);
        self.armed = false;
    }
}

impl Drop for WaitRegistration {
    fn drop(&mut self) {
        if self.armed {
            self.owner
                .remove_queued(&self.id, self.sequence, PlatformErrorCode::Cancelled);
        }
    }
}
