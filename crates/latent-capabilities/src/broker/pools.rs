//! Shared, explicitly configured node provider resources. No guest supplied name
//! creates a pool. Protocol adapters validate configuration before installation.
use super::io::IoRuntime;
use super::{
    busy, capacity, checked_text, denied, invalid, ActivationCapabilityBroker, PlatformError,
    ProviderConfiguration, ProviderReference, ProviderRegistration,
};
use std::{
    any::Any,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex, Weak,
    },
    time::Instant,
};
use tokio::sync::Notify;
use zeroize::Zeroizing;

mod admission;
mod client;
mod control;
mod limits;
pub use admission::{PoolAdmission, PoolCall, PoolReady};
pub use client::{ConnectionReservation, PooledConnection, ProviderClient};
pub use control::{CleanupFuture, CleanupResult, ProviderJob};
use limits::{Charge, Kind, Quotas};
pub use limits::{ProviderPoolLimits, ProviderPoolSnapshot};

/// Trusted, already validated provider settings. The authority digest identifies
/// public configuration only: never hash credentials into a public descriptor.
/// Credential bytes are copied into zeroizing epoch-owned storage after quota
/// reservation, and never appear in keys, references or snapshots.
#[derive(Clone, Copy)]
pub struct ProviderSetup<'a> {
    pub logical_id: &'a str,
    pub authority: ProviderConfiguration<'a>,
    pub credentials: &'a [u8],
}
pub struct ProviderPools {
    inner: Arc<Inner>,
}
struct Inner {
    broker: Arc<ActivationCapabilityBroker>,
    io: Arc<IoRuntime>,
    quotas: Arc<Quotas>,
    state: Mutex<State>,
    maintenance: Mutex<()>,
    changed: Arc<Notify>,
    closed: AtomicBool,
    failed_cleanup: AtomicUsize,
    control: control::Control,
    _metadata: Charge,
}
struct State {
    next_instance: u64,
    next_request: u64,
    epochs: Vec<Arc<Epoch>>,
    retained_epochs: Vec<Weak<Epoch>>,
    clients: Vec<Arc<dyn ErasedClient>>,
    retained_clients: Vec<Weak<dyn ErasedClient>>,
    requests: Vec<Weak<admission::Request>>,
    tenants: Vec<Weak<admission::Tenant>>,
    last_tenant: String,
}
struct Epoch {
    logical_id: String,
    instance: u64,
    registration: ProviderRegistration,
    credentials: Zeroizing<Vec<u8>>,
    retired: AtomicBool,
    usage: Arc<ProviderUse>,
    _metadata: Charge,
    _slot: Charge,
}
struct ProviderUse {
    identity: u64,
    clients: AtomicUsize,
    requests: AtomicUsize,
    running: AtomicUsize,
    _metadata: Charge,
}
impl Epoch {
    fn retire(&self) {
        self.retired.store(true, Ordering::Release);
        self.registration.retire();
    }
}
/// Immutable accepted epoch; cloning does not install another client or pool.
#[derive(Clone)]
pub struct InstalledProvider {
    epoch: Arc<Epoch>,
}
impl InstalledProvider {
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.epoch.registration.reference()
    }
    /// Trusted adapter access only. No credential string is returned in metadata.
    pub fn with_credentials<T>(&self, inspect: impl FnOnce(&[u8]) -> T) -> T {
        inspect(&self.epoch.credentials)
    }
}
trait ErasedClient: Any + Send + Sync {
    fn core(&self) -> &Arc<client::ClientCore>;
    fn as_any(self: Arc<Self>) -> Arc<dyn Any + Send + Sync>;
    fn maintain(&self, now: Instant, closed: bool);
}
impl ProviderPools {
    pub fn new(
        broker: Arc<ActivationCapabilityBroker>,
        io: Arc<IoRuntime>,
        control: tokio::runtime::Handle,
        limits: ProviderPoolLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        let quotas = Quotas::new(limits);
        let slots = limits.maximum_pending_requests + limits.maximum_running_requests;
        let metadata = quotas.acquire(
            Kind::Metadata,
            8192 + slots * 128 + limits.maximum_clients * 128 + limits.maximum_configurations * 128,
        )?;
        // A fresh registry cannot bypass live lowering or the retained resources
        // of an older registry on the same broker generation.
        broker
            .inner
            .pool_registered
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| denied())?;
        let inner = Arc::new(Inner {
            broker,
            io,
            quotas,
            state: Mutex::new(State {
                next_instance: 0,
                next_request: 0,
                epochs: Vec::with_capacity(limits.maximum_configurations),
                retained_epochs: Vec::with_capacity(limits.maximum_configurations),
                clients: Vec::with_capacity(limits.maximum_clients),
                retained_clients: Vec::with_capacity(limits.maximum_clients),
                requests: std::iter::repeat_with(Weak::new).take(slots).collect(),
                tenants: std::iter::repeat_with(Weak::new).take(slots).collect(),
                last_tenant: String::with_capacity(256),
            }),
            maintenance: Mutex::new(()),
            changed: Arc::new(Notify::new()),
            closed: AtomicBool::new(false),
            failed_cleanup: AtomicUsize::new(0),
            control: control::Control::new(
                control,
                limits.maximum_workers + limits.maximum_cleanup_jobs,
            ),
            _metadata: metadata,
        });
        control::start(&inner);
        Ok(Self { inner })
    }
    /// Expected epoch is zero for creation. A replacement needs quota headroom
    /// for both old and new physical owners; failure leaves the old epoch live.
    pub fn install(
        &self,
        input: ProviderSetup<'_>,
        expected_epoch: u64,
    ) -> Result<InstalledProvider, PlatformError> {
        let limits = self.inner.quotas.limits()?;
        if input.credentials.len() > limits.maximum_configuration_bytes {
            return Err(capacity());
        }
        let slot = self.inner.quotas.acquire(Kind::Configuration, 1)?;
        let metadata = self
            .inner
            .quotas
            .acquire(Kind::Metadata, 4096 + input.credentials.len())?;
        let logical_id = checked_text(input.logical_id)?;
        let registration = self.inner.broker.register_provider(input.authority)?;
        let mut state = self.inner.state.try_lock().map_err(|_| busy())?;
        self.inner.check()?;
        if input.credentials.len() > self.inner.quotas.limits()?.maximum_configuration_bytes {
            return Err(capacity());
        }
        let old = state.epochs.iter().position(|e| e.logical_id == logical_id);
        let actual = old.map_or(0, |i| state.epochs[i].registration.reference().entry.epoch);
        if actual != expected_epoch || input.authority.configuration_epoch <= actual {
            return Err(denied());
        }
        let instance = state.next_instance.checked_add(1).ok_or_else(capacity)?;
        let usage = if let Some(index) = old {
            Arc::clone(&state.epochs[index].usage)
        } else {
            let metadata = self.inner.quotas.acquire(Kind::Metadata, 1024)?;
            Arc::new(ProviderUse {
                identity: instance,
                clients: AtomicUsize::new(0),
                requests: AtomicUsize::new(0),
                running: AtomicUsize::new(0),
                _metadata: metadata,
            })
        };
        let epoch = Arc::new(Epoch {
            logical_id,
            instance,
            registration,
            credentials: Zeroizing::new(input.credentials.to_vec()),
            retired: AtomicBool::new(false),
            usage,
            _metadata: metadata,
            _slot: slot,
        });
        let old = if let Some(index) = old {
            // Broker's provider fence closes later dispatches before publication.
            state.epochs[index].retire();
            Some(std::mem::replace(
                &mut state.epochs[index],
                Arc::clone(&epoch),
            ))
        } else {
            state.epochs.push(Arc::clone(&epoch));
            None
        };
        state.next_instance = instance;
        state.retained_epochs.retain(|old| old.strong_count() != 0);
        state.retained_epochs.push(Arc::downgrade(&epoch));
        drop(state);
        drop(old);
        self.inner.changed.notify_waiters();
        self.inner.maintain();
        Ok(InstalledProvider { epoch })
    }
    pub fn provider(&self, logical_id: &str) -> Result<InstalledProvider, PlatformError> {
        self.inner.check()?;
        let state = self.inner.state.try_lock().map_err(|_| busy())?;
        let epoch = state
            .epochs
            .iter()
            .find(|e| e.logical_id == logical_id)
            .ok_or_else(denied)?;
        Ok(InstalledProvider {
            epoch: Arc::clone(epoch),
        })
    }
    pub fn lower_limits(&self, limits: ProviderPoolLimits) -> Result<(), PlatformError> {
        let state = self.inner.state.try_lock().map_err(|_| busy())?;
        if state
            .retained_epochs
            .iter()
            .filter_map(Weak::upgrade)
            .any(|e| {
                e.usage.clients.load(Ordering::Acquire) > limits.maximum_clients_per_provider
                    || e.usage.running.load(Ordering::Acquire) > limits.maximum_running_per_provider
                    || e.usage.requests.load(Ordering::Acquire)
                        > limits.maximum_requests_per_provider
                    || e.credentials.len() > limits.maximum_configuration_bytes
            })
            || state
                .retained_clients
                .iter()
                .filter_map(Weak::upgrade)
                .any(|c| {
                    c.core().connections.load(Ordering::Acquire)
                        > limits.maximum_connections_per_client
                })
            || state.tenants.iter().filter_map(Weak::upgrade).any(|t| {
                t.requests.load(Ordering::Acquire) > limits.maximum_requests_per_tenant
                    || t.running.load(Ordering::Acquire) > limits.maximum_running_per_tenant
            })
        {
            return Err(capacity());
        }
        self.inner.quotas.lower(limits)
    }
    pub fn snapshot(&self) -> Result<ProviderPoolSnapshot, PlatformError> {
        self.inner.snapshot()
    }
    pub fn retire(&self) {
        self.inner.retire();
    }
    /// A timeout reports retained ownership. It never aborts jobs or claims their
    /// sockets, threads or activation leases were reclaimed.
    pub async fn shutdown(&self, deadline: Instant) -> Result<ProviderPoolSnapshot, PlatformError> {
        self.retire();
        loop {
            let changed = self.inner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            control::join_finished_owner(&self.inner).await;
            let snapshot = self.snapshot()?;
            if snapshot.connections == 0
                && snapshot.workers == 0
                && snapshot.cleanup_jobs == 0
                && snapshot.running_requests == 0
                && snapshot.pending_requests == 0
                && snapshot.control_owners == 0
            {
                return Ok(snapshot);
            }
            tokio::select! {
                () = &mut changed => {},
                () = tokio::time::sleep(std::time::Duration::from_millis(25)) => {},
                () = tokio::time::sleep_until(deadline.into()) => {
                    control::join_finished_owner(&self.inner).await;
                    return self.snapshot();
                },
            }
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests;
impl Drop for ProviderPools {
    fn drop(&mut self) {
        self.retire();
    }
}
impl Inner {
    fn check(&self) -> Result<(), PlatformError> {
        if self.closed.load(Ordering::Acquire) {
            return Err(denied());
        }
        Ok(())
    }
    fn retire(&self) {
        self.closed.store(true, Ordering::Release);
        self.io.retire();
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        for epoch in &state.epochs {
            epoch.retire();
        }
        let epochs = std::mem::take(&mut state.epochs);
        let clients = std::mem::take(&mut state.clients);
        drop(state);
        for client in &clients {
            client.maintain(Instant::now(), true);
        }
        drop(clients);
        drop(epochs);
        self.changed.notify_waiters();
    }
    fn snapshot(&self) -> Result<ProviderPoolSnapshot, PlatformError> {
        let state = self.state.try_lock().map_err(|_| busy())?;
        let use_of = |kind| self.quotas.use_of(kind);
        let mut connecting = 0;
        let mut retired = 0;
        for client in state.retained_clients.iter().filter_map(Weak::upgrade) {
            connecting += usize::from(client.core().is_connecting()?);
            if client.core().epoch.retired.load(Ordering::Acquire) {
                retired += client.core().connections.load(Ordering::Acquire);
            }
        }
        let connections = use_of(Kind::Connection);
        let idle = use_of(Kind::Idle);
        Ok(ProviderPoolSnapshot {
            configurations: state.epochs.len(),
            retained_configurations: use_of(Kind::Configuration),
            clients: use_of(Kind::Client),
            connections,
            active_connections: connections.saturating_sub(idle).saturating_sub(connecting),
            connecting_connections: connecting,
            retired_connections: retired,
            idle_connections: idle,
            pending_requests: use_of(Kind::Pending),
            running_requests: use_of(Kind::Running),
            workers: use_of(Kind::Worker),
            cleanup_jobs: use_of(Kind::Cleanup),
            failed_cleanup: self.failed_cleanup.load(Ordering::Acquire),
            metadata_bytes: use_of(Kind::Metadata),
            control_owners: self.control.owners.load(Ordering::Acquire),
            control_failed: self.control.failed.load(Ordering::Acquire),
            closed: self.closed.load(Ordering::Acquire),
        })
    }
    fn maintain(&self) {
        let Ok(_maintenance) = self.maintenance.try_lock() else {
            return;
        };
        let count = match self.state.try_lock() {
            Ok(state) => state.retained_clients.len(),
            Err(_) => return,
        };
        for index in 0..count {
            let Ok(mut state) = self.state.try_lock() else {
                return;
            };
            let Some(client) = state.retained_clients.get(index).and_then(Weak::upgrade) else {
                continue;
            };
            if client.core().epoch.retired.load(Ordering::Acquire) {
                if let Some(slot) = state
                    .clients
                    .iter()
                    .position(|old| Arc::ptr_eq(old, &client))
                {
                    state.clients.swap_remove(slot);
                }
            }
            drop(state);
            // No scratch vector, and no physical resource is destroyed under
            // the registry lock. At most the fixed configured client ceiling.
            client.maintain(Instant::now(), self.closed.load(Ordering::Acquire));
        }
    }
}
