use super::{busy, capacity, invalid, PlatformError};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, RwLock,
    },
    time::Duration,
};

/// Node ceilings, including retired epochs and physically retained resources.
/// Live lowering cannot erase outstanding ownership or raise startup ceilings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProviderPoolLimits {
    pub maximum_configurations: usize,
    pub maximum_clients: usize,
    pub maximum_clients_per_provider: usize,
    pub maximum_connections: usize,
    pub maximum_connections_per_client: usize,
    pub maximum_idle_connections: usize,
    pub maximum_pending_requests: usize,
    pub maximum_running_requests: usize,
    pub maximum_requests_per_tenant: usize,
    pub maximum_requests_per_provider: usize,
    pub maximum_running_per_tenant: usize,
    pub maximum_running_per_provider: usize,
    pub maximum_workers: usize,
    pub maximum_cleanup_jobs: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_configuration_bytes: usize,
    pub maximum_queue_age: Duration,
    pub maximum_idle_age: Duration,
    pub initial_backoff: Duration,
    pub maximum_backoff: Duration,
}
impl Default for ProviderPoolLimits {
    fn default() -> Self {
        Self {
            maximum_configurations: 32,
            maximum_clients: 128,
            maximum_clients_per_provider: 8,
            maximum_connections: 256,
            maximum_connections_per_client: 8,
            maximum_idle_connections: 64,
            maximum_pending_requests: 128,
            maximum_running_requests: 64,
            maximum_requests_per_tenant: 32,
            maximum_requests_per_provider: 64,
            maximum_running_per_tenant: 16,
            maximum_running_per_provider: 32,
            maximum_workers: 16,
            maximum_cleanup_jobs: 8,
            maximum_metadata_bytes: 8 * 1024 * 1024,
            maximum_configuration_bytes: 65536,
            maximum_queue_age: Duration::from_secs(5),
            maximum_idle_age: Duration::from_secs(30),
            initial_backoff: Duration::from_millis(100),
            maximum_backoff: Duration::from_secs(30),
        }
    }
}
impl ProviderPoolLimits {
    fn values(self) -> [usize; 16] {
        [
            self.maximum_configurations,
            self.maximum_clients,
            self.maximum_clients_per_provider,
            self.maximum_connections,
            self.maximum_connections_per_client,
            self.maximum_idle_connections,
            self.maximum_pending_requests,
            self.maximum_running_requests,
            self.maximum_requests_per_tenant,
            self.maximum_requests_per_provider,
            self.maximum_running_per_tenant,
            self.maximum_running_per_provider,
            self.maximum_workers,
            self.maximum_cleanup_jobs,
            self.maximum_metadata_bytes,
            self.maximum_configuration_bytes,
        ]
    }
    pub fn validate(self) -> Result<(), PlatformError> {
        let hard = [
            256,
            1024,
            128,
            4096,
            256,
            1024,
            1024,
            1024,
            1024,
            1024,
            1024,
            1024,
            128,
            128,
            64 * 1024 * 1024,
            1024 * 1024,
        ];
        if self
            .values()
            .into_iter()
            .zip(hard)
            .any(|(v, h)| v == 0 || v > h)
            || self.maximum_clients_per_provider > self.maximum_clients
            || self.maximum_connections_per_client > self.maximum_connections
            || self.maximum_idle_connections > self.maximum_connections
            || self.maximum_running_per_tenant > self.maximum_running_requests
            || self.maximum_running_per_provider > self.maximum_running_requests
            || self.maximum_running_per_tenant > self.maximum_requests_per_tenant
            || self.maximum_running_per_provider > self.maximum_requests_per_provider
            || self.maximum_configuration_bytes > self.maximum_metadata_bytes
            || self.maximum_queue_age.is_zero()
            || self.maximum_queue_age > Duration::from_mins(1)
            || self.maximum_idle_age.is_zero()
            || self.maximum_idle_age > Duration::from_hours(1)
            || self.initial_backoff.is_zero()
            || self.initial_backoff > self.maximum_backoff
            || self.maximum_backoff > Duration::from_mins(5)
        {
            return Err(invalid());
        }
        Ok(())
    }
    pub(super) fn narrows(self, old: Self) -> bool {
        self.values()
            .into_iter()
            .zip(old.values())
            .all(|(a, b)| a <= b)
            && self.maximum_queue_age <= old.maximum_queue_age
            && self.maximum_idle_age <= old.maximum_idle_age
            && self.initial_backoff == old.initial_backoff
            && self.maximum_backoff == old.maximum_backoff
    }
    fn quotas(self) -> [usize; 9] {
        [
            self.maximum_configurations,
            self.maximum_clients,
            self.maximum_connections,
            self.maximum_idle_connections,
            self.maximum_pending_requests,
            self.maximum_running_requests,
            self.maximum_workers,
            self.maximum_cleanup_jobs,
            self.maximum_metadata_bytes,
        ]
    }
}

#[derive(Clone, Copy)]
pub(super) enum Kind {
    Configuration,
    Client,
    Connection,
    Idle,
    Pending,
    Running,
    Worker,
    Cleanup,
    Metadata,
}
pub(super) struct Quotas {
    pub limits: RwLock<ProviderPoolLimits>,
    values: [AtomicUsize; 9],
}
impl Quotas {
    pub fn new(limits: ProviderPoolLimits) -> Arc<Self> {
        Arc::new(Self {
            limits: RwLock::new(limits),
            values: std::array::from_fn(|_| AtomicUsize::new(0)),
        })
    }
    pub fn limits(&self) -> Result<ProviderPoolLimits, PlatformError> {
        self.limits.try_read().map(|v| *v).map_err(|_| busy())
    }
    pub fn acquire(self: &Arc<Self>, kind: Kind, amount: usize) -> Result<Charge, PlatformError> {
        let limits = self.limits.try_read().map_err(|_| busy())?;
        increment(
            &self.values[kind as usize],
            amount,
            limits.quotas()[kind as usize],
        )?;
        Ok(Charge {
            owner: Arc::clone(self),
            kind,
            amount,
        })
    }
    pub fn use_of(&self, kind: Kind) -> usize {
        self.values[kind as usize].load(Ordering::Acquire)
    }
    pub fn lower(&self, next: ProviderPoolLimits) -> Result<(), PlatformError> {
        next.validate()?;
        let mut current = self.limits.try_write().map_err(|_| busy())?;
        if !next.narrows(*current) {
            return Err(invalid());
        }
        if self
            .values
            .iter()
            .zip(next.quotas())
            .any(|(used, max)| used.load(Ordering::Acquire) > max)
        {
            return Err(capacity());
        }
        *current = next;
        Ok(())
    }
}
pub(super) fn increment(
    value: &AtomicUsize,
    amount: usize,
    limit: usize,
) -> Result<(), PlatformError> {
    let mut used = value.load(Ordering::Acquire);
    for _ in 0..16 {
        let next = used
            .checked_add(amount)
            .filter(|v| *v <= limit)
            .ok_or_else(capacity)?;
        match value.compare_exchange_weak(used, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return Ok(()),
            Err(now) => used = now,
        }
    }
    Err(busy())
}
pub(super) struct Charge {
    owner: Arc<Quotas>,
    kind: Kind,
    amount: usize,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.owner.values[self.kind as usize].fetch_sub(self.amount, Ordering::AcqRel);
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct ProviderPoolSnapshot {
    pub configurations: usize,
    pub retained_configurations: usize,
    pub clients: usize,
    pub connections: usize,
    pub active_connections: usize,
    pub connecting_connections: usize,
    pub retired_connections: usize,
    pub idle_connections: usize,
    pub pending_requests: usize,
    pub running_requests: usize,
    pub workers: usize,
    pub cleanup_jobs: usize,
    pub failed_cleanup: usize,
    pub metadata_bytes: usize,
    pub control_owners: usize,
    pub control_failed: bool,
    pub closed: bool,
}
impl ProviderPoolSnapshot {
    #[must_use]
    pub fn is_clean(&self) -> bool {
        self.closed
            && !self.control_failed
            && self.control_owners == 0
            && self.connections == 0
            && self.pending_requests == 0
            && self.running_requests == 0
            && self.workers == 0
            && self.cleanup_jobs == 0
            && self.failed_cleanup == 0
    }
}
