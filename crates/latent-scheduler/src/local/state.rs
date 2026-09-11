use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_admission::LocalQuotaProvider;
use latent_core::{ActivationId, PlatformError, PlatformErrorCode, TenantId};
use tokio::sync::oneshot;

use super::assignment::{ActiveRegistration, PendingAssignment};
use super::queue::{EntrySlot, Queue};
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
    pub queued_at: Option<EntrySlot>,
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

pub(super) struct ClassState {
    queue: Queue,
    #[cfg(test)]
    pub work: super::work::Work,
    pub depth: u32,
    pub counters: SchedulerSnapshot,
    pub active_since: BTreeSet<(Instant, u64)>,
}

impl ClassState {
    pub fn new(capacity: u32) -> Self {
        Self {
            queue: Queue::new(capacity),
            #[cfg(test)]
            work: super::work::Work::default(),
            depth: 0,
            counters: SchedulerSnapshot::default(),
            active_since: BTreeSet::new(),
        }
    }

    pub fn push(&mut self, entry: Entry) -> EntrySlot {
        self.depth += 1;
        self.queue.push(
            entry,
            #[cfg(test)]
            &mut self.work,
        )
    }

    fn select(
        &mut self,
        now: Instant,
        starvation_after: std::time::Duration,
    ) -> Option<(EntrySlot, Entry)> {
        let (slot, _) = self.queue.front_entries().min_by(|(_, a), (_, b)| {
            #[cfg(test)]
            self.work.compare_winners();
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
        })?;
        let entry = self.queue.unlink(
            slot,
            #[cfg(test)]
            &mut self.work,
        );
        // The physical slot is reusable; logical depth is still reserved while
        // the pump owns this selected entry across the open pool call.
        Some((slot, entry))
    }

    fn rotate_after_grant(&mut self, tenant: &TenantId) {
        self.queue.rotate_after_grant(
            tenant,
            #[cfg(test)]
            &mut self.work,
        );
    }

    fn restore(&mut self, entry: Entry) -> EntrySlot {
        // Selection retained this reservation. Restore leaves depth unchanged.
        self.queue.restore(
            entry,
            #[cfg(test)]
            &mut self.work,
        )
    }

    fn remove(&mut self, slot: EntrySlot, sequence: u64) -> Option<Entry> {
        let entry = self.queue.remove(
            slot,
            sequence,
            #[cfg(test)]
            &mut self.work,
        )?;
        self.depth -= 1;
        Some(entry)
    }

    fn tenant_count(&self) -> usize {
        self.queue.tenant_count()
    }

    fn drain_into(&mut self, entries: &mut Vec<Entry>) {
        self.queue.drain_into(
            entries,
            #[cfg(test)]
            &mut self.work,
        );
        self.depth = 0;
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
            snapshot.accepting = !state.shutdown
                && self
                    .config
                    .queue_capacity_per_class
                    .get(&class)
                    .is_some_and(|capacity| *capacity > 0);
            snapshot.queue_depth = queue.depth;
            snapshot.queued_tenants = u32::try_from(queue.tenant_count()).unwrap_or(u32::MAX);
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
        let (registration, removed) = {
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
            let removed = if let Some(slot) = registration.queued_at {
                Some(
                    queue
                        .remove(slot, sequence)
                        .expect("matched queued location"),
                )
            } else {
                queue.depth -= 1; // currently selected by the synchronous pump
                None
            };
            (registration, removed)
        };
        // Permit destruction takes the quota mutex: never do it under our state lock.
        drop(removed);
        // The final cancellation owner may run arbitrary code in its destructor.
        drop(registration);
    }

    pub fn finish_active(&self, id: &ActivationId, sequence: u64) {
        let retired = {
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
            entry
        };
        drop(retired);
    }

    fn select_queued(&self, class: CellClass) -> Option<Entry> {
        let mut state = self.lock();
        if state.shutdown {
            return None;
        }
        let (slot, entry) = state
            .classes
            .get_mut(&class)
            .expect("configured class")
            .select(now(), self.config.starvation_after)?;
        let registration = state
            .live
            .get_mut(entry.request.permit.activation_id())
            .expect("queued registration");
        debug_assert_eq!(registration.sequence, entry.sequence);
        debug_assert_eq!(registration.queued_at, Some(slot));
        debug_assert!(registration.assigned_at.is_none());
        // Retire the physical location before the selected owner leaves this
        // lock; logical depth remains reserved across the open pool call.
        registration.queued_at = None;
        Some(entry)
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
            let Some(entry) = self.select_queued(class) else {
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
                    if !state.shutdown {
                        let State { live, classes, .. } = &mut *state;
                        if let Some(registration) = live
                            .get_mut(entry.request.permit.activation_id())
                            .filter(|registration| registration.sequence == entry.sequence)
                        {
                            debug_assert!(registration.queued_at.is_none());
                            debug_assert!(registration.assigned_at.is_none());
                            registration.queued_at = Some(
                                classes
                                    .get_mut(&class)
                                    .expect("configured class")
                                    .restore(entry),
                            );
                            return true;
                        }
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
                let registration = state.live.get_mut(&id).expect("matched registration");
                debug_assert!(registration.queued_at.is_none());
                registration.assigned_at = Some(assigned);
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
        let retired = {
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
                Some(registration)
            } else {
                None
            }
        };
        drop(entry.request);
        drop(retired);
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
        let (entries, retired) = {
            let mut state = self.lock();
            state.shutdown = true;
            let mut entries = Vec::new();
            for queue in state.classes.values_mut() {
                queue.drain_into(&mut entries);
            }
            let queued: Vec<_> = state
                .live
                .iter()
                .filter(|(_, entry)| entry.assigned_at.is_none())
                .map(|(id, _)| id.clone())
                .collect();
            let mut retired = Vec::with_capacity(queued.len());
            for id in queued {
                let entry = state.live.remove(&id).expect("collected registration");
                if !entry.failure_counted {
                    state
                        .classes
                        .get_mut(&entry.class)
                        .expect("registered class")
                        .count_error(PlatformErrorCode::Unavailable, entry.cancellation_counted);
                }
                retired.push(entry);
            }
            (entries, retired)
        };
        for entry in entries {
            self.finish_error(entry, error(PlatformErrorCode::Unavailable, "shutdown"));
        }
        drop(retired);
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

#[cfg(test)]
mod tests;
