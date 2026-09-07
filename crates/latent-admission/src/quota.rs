use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};

use latent_core::{
    ActivationId, BoxFuture, EffectiveActivationBudget, PlatformError, PlatformErrorCode,
    ResourceBudget, TenantId,
};

use crate::{rejection, NodeAdmissionPolicy, QuotaLimits, QuotaProvider, QuotaSnapshot};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct QuotaUsage {
    pub active_activations: u32,
    pub queued_activations: u32,
    pub reserved_cpu_fuel: u64,
    pub reserved_memory_bytes: u64,
}

impl QuotaUsage {
    fn reserve(
        self,
        budget: &ResourceBudget,
        limits: QuotaLimits,
        scope: &'static str,
    ) -> Result<Self, PlatformError> {
        let exhausted = |dimension| {
            rejection(
                PlatformErrorCode::ResourceExhausted,
                scope,
                dimension,
                "capacity-exhausted",
            )
        };
        let next = Self {
            active_activations: self
                .active_activations
                .checked_add(1)
                .ok_or_else(|| exhausted("concurrency"))?,
            queued_activations: self
                .queued_activations
                .checked_add(1)
                .ok_or_else(|| exhausted("queue"))?,
            reserved_cpu_fuel: self
                .reserved_cpu_fuel
                .checked_add(budget.cpu_fuel)
                .ok_or_else(|| exhausted("cpu-fuel"))?,
            reserved_memory_bytes: self
                .reserved_memory_bytes
                .checked_add(budget.memory_bytes)
                .ok_or_else(|| exhausted("memory-bytes"))?,
        };
        for (exceeded, dimension) in [
            (
                next.active_activations > limits.maximum_concurrent_activations,
                "concurrency",
            ),
            (
                next.queued_activations > limits.maximum_queued_activations,
                "queue",
            ),
            (
                next.reserved_cpu_fuel > limits.maximum_reserved_cpu_fuel,
                "cpu-fuel",
            ),
            (
                next.reserved_memory_bytes > limits.maximum_reserved_memory_bytes,
                "memory-bytes",
            ),
        ] {
            if exceeded {
                return Err(exhausted(dimension));
            }
        }
        Ok(next)
    }

    fn release(&mut self, record: &Reservation) {
        self.active_activations -= 1;
        self.queued_activations -= u32::from(record.queued);
        self.reserved_cpu_fuel -= record.cpu_fuel;
        self.reserved_memory_bytes -= record.memory_bytes;
    }
}

struct Reservation {
    tenant: TenantId,
    trust_class: String,
    queue_class: String,
    cell_class: String,
    cpu_fuel: u64,
    memory_bytes: u64,
    queued: bool,
}

#[derive(Default)]
struct State {
    usage: QuotaUsage,
    tenants: BTreeMap<TenantId, QuotaUsage>,
    trust_classes: BTreeMap<String, QuotaUsage>,
    queues: BTreeMap<String, u32>,
    cells: BTreeMap<String, u32>,
    reservations: BTreeMap<ActivationId, Reservation>,
}

struct Inner {
    policy: NodeAdmissionPolicy,
    state: Mutex<State>,
}

/// One node-owned atomic reservation ledger. Clone this value; do not construct
/// separate ledgers for services, tenants, controllers, or new route generations.
/// Only configured tenants can acquire state, and zero-usage entries are removed.
#[derive(Clone)]
pub struct LocalQuotaProvider {
    inner: Arc<Inner>,
}

#[derive(Clone, Copy)]
pub(crate) struct ReservationSpec<'a> {
    pub activation_id: &'a ActivationId,
    pub tenant: &'a TenantId,
    pub trust_class: &'a str,
    pub queue_class: &'a str,
    pub cell_class: &'a str,
    pub grant: &'a EffectiveActivationBudget,
    pub timing: crate::timing::ReservationTiming,
}

impl LocalQuotaProvider {
    pub fn new(policy: NodeAdmissionPolicy) -> Result<Self, PlatformError> {
        policy.validate()?;
        Ok(Self {
            inner: Arc::new(Inner {
                policy,
                state: Mutex::new(State::default()),
            }),
        })
    }

    #[must_use]
    pub fn policy(&self) -> &NodeAdmissionPolicy {
        &self.inner.policy
    }

    pub fn usage(&self) -> Result<QuotaUsage, PlatformError> {
        Ok(self.lock()?.usage)
    }

    /// Trusted-local diagnostic showing that idle tenant state is not retained.
    pub fn retained_tenant_count(&self) -> Result<usize, PlatformError> {
        Ok(self.lock()?.tenants.len())
    }

    pub fn snapshot_now(&self, tenant: &TenantId) -> Result<QuotaSnapshot, PlatformError> {
        let policy = self.policy().tenants.get(tenant).ok_or_else(|| {
            rejection(
                PlatformErrorCode::PermissionDenied,
                "tenant",
                "principal",
                "tenant-not-authorized",
            )
        })?;
        let usage = self
            .lock()?
            .tenants
            .get(tenant)
            .copied()
            .unwrap_or_default();
        Ok(QuotaSnapshot {
            tenant: tenant.clone(),
            maximum_concurrent_activations: policy.limits.maximum_concurrent_activations,
            active_activations: usage.active_activations,
            queued_activations: usage.queued_activations,
            remaining_cpu_fuel: policy.limits.maximum_reserved_cpu_fuel - usage.reserved_cpu_fuel,
            remaining_memory_bytes: policy.limits.maximum_reserved_memory_bytes
                - usage.reserved_memory_bytes,
            reset_at_unix_millis: None,
        })
    }

    pub(crate) fn reserve(&self, spec: ReservationSpec<'_>) -> Result<(), PlatformError> {
        let policy = self.policy();
        let tenant = &policy.tenants[spec.tenant];
        let trust = &policy.trust_classes[spec.trust_class];
        let queue = &policy.queue_classes[spec.queue_class];
        let class = &policy.cell_classes[spec.cell_class];
        let mut state = self.lock()?;
        if state.reservations.contains_key(spec.activation_id) {
            return Err(rejection(
                PlatformErrorCode::AlreadyExists,
                "request",
                "activation-id",
                "activation-id-unavailable",
            ));
        }
        // Calculate every new value and perform every rejection before mutation.
        // The same critical section includes deadline estimation, so racing
        // admissions observe reservations made by earlier winners.
        let next_usage = state
            .usage
            .reserve(&spec.grant.budget, policy.limits, "node")?;
        let next_tenant = state
            .tenants
            .get(spec.tenant)
            .copied()
            .unwrap_or_default()
            .reserve(&spec.grant.budget, tenant.limits, "tenant")?;
        let next_trust = state
            .trust_classes
            .get(spec.trust_class)
            .copied()
            .unwrap_or_default()
            .reserve(&spec.grant.budget, trust.limits, "trust-class")?;
        let next_queue = state
            .queues
            .get(spec.queue_class)
            .copied()
            .unwrap_or(0)
            .checked_add(1)
            .filter(|count| *count <= queue.maximum_queued_activations)
            .ok_or_else(|| {
                rejection(
                    PlatformErrorCode::ResourceExhausted,
                    "queue-class",
                    "queue",
                    "capacity-exhausted",
                )
            })?;
        let current_cell = state.cells.get(spec.cell_class).copied().unwrap_or(0);
        let next_cell = current_cell.checked_add(1).ok_or_else(|| {
            rejection(
                PlatformErrorCode::ResourceExhausted,
                "node",
                "concurrency",
                "capacity-exhausted",
            )
        })?;
        spec.timing
            .validate(policy, spec.grant, current_cell, class.parallelism)?;
        let record = Reservation {
            tenant: spec.tenant.clone(),
            trust_class: spec.trust_class.to_owned(),
            queue_class: spec.queue_class.to_owned(),
            cell_class: spec.cell_class.to_owned(),
            cpu_fuel: spec.grant.budget.cpu_fuel,
            memory_bytes: spec.grant.budget.memory_bytes,
            queued: true,
        };
        state.tenants.insert(record.tenant.clone(), next_tenant);
        state
            .trust_classes
            .insert(record.trust_class.clone(), next_trust);
        state.queues.insert(record.queue_class.clone(), next_queue);
        state.cells.insert(record.cell_class.clone(), next_cell);
        state
            .reservations
            .insert(spec.activation_id.clone(), record);
        state.usage = next_usage;
        Ok(())
    }

    pub(crate) fn start(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
        let mut state = self.lock()?;
        let record = state.reservations.get_mut(activation_id).ok_or_else(|| {
            rejection(
                PlatformErrorCode::Internal,
                "request",
                "quota",
                "reservation-not-live",
            )
        })?;
        if !record.queued {
            return Err(rejection(
                PlatformErrorCode::Internal,
                "request",
                "quota",
                "reservation-already-started",
            ));
        }
        record.queued = false;
        let tenant = record.tenant.clone();
        let trust = record.trust_class.clone();
        let queue = record.queue_class.clone();
        state.usage.queued_activations -= 1;
        state
            .tenants
            .get_mut(&tenant)
            .expect("live tenant reservation")
            .queued_activations -= 1;
        state
            .trust_classes
            .get_mut(&trust)
            .expect("live trust reservation")
            .queued_activations -= 1;
        decrement(&mut state.queues, &queue);
        Ok(())
    }

    pub(crate) fn release(&self, activation_id: &ActivationId) {
        // Drop must reclaim a live reservation even after a poisoned reader.
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(record) = state.reservations.remove(activation_id) {
            state.usage.release(&record);
            release_usage(&mut state.tenants, &record.tenant, &record);
            release_usage(&mut state.trust_classes, &record.trust_class, &record);
            if record.queued {
                decrement(&mut state.queues, &record.queue_class);
            }
            decrement(&mut state.cells, &record.cell_class);
        }
    }

    fn lock(&self) -> Result<MutexGuard<'_, State>, PlatformError> {
        self.inner.state.lock().map_err(|_| {
            rejection(
                PlatformErrorCode::Unavailable,
                "node",
                "quota",
                "quota-state-unavailable",
            )
        })
    }
}

fn release_usage<K: Ord>(map: &mut BTreeMap<K, QuotaUsage>, key: &K, record: &Reservation) {
    let usage = map.get_mut(key).expect("live quota reservation");
    usage.release(record);
    if usage.active_activations == 0 {
        map.remove(key);
    }
}

fn decrement(map: &mut BTreeMap<String, u32>, key: &str) {
    let count = map.get_mut(key).expect("live class reservation");
    *count -= 1;
    if *count == 0 {
        map.remove(key);
    }
}

impl QuotaProvider for LocalQuotaProvider {
    fn snapshot<'a>(
        &'a self,
        tenant: &'a TenantId,
    ) -> BoxFuture<'a, Result<QuotaSnapshot, PlatformError>> {
        Box::pin(async move { self.snapshot_now(tenant) })
    }
}
