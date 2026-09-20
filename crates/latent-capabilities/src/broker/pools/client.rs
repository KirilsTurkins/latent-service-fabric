use super::{
    busy, capacity, denied, invalid, limits, Any, Arc, AtomicUsize, Charge, Epoch, ErasedClient,
    IngressRequest, Inner, InstalledProvider, Instant, Kind, MaintenanceRequest, Mutex, Ordering,
    PlatformError, PoolCall, ProviderPools, Weak,
};
use crate::broker::io::IoLease;
use std::{collections::VecDeque, time::Duration};

pub(super) struct ClientCore {
    pub epoch: Arc<Epoch>,
    pub origin: u16,
    pub owner: Weak<Inner>,
    pub connections: AtomicUsize,
    backoff: Mutex<Backoff>,
    _metadata: Charge,
    _slot: Charge,
}
struct Backoff {
    dialing: bool,
    failures: u32,
    next: Option<Instant>,
}
impl ClientCore {
    pub(super) fn is_connecting(&self) -> Result<bool, PlatformError> {
        self.backoff
            .try_lock()
            .map(|state| state.dialing)
            .map_err(|_| busy())
    }
}
impl Drop for ClientCore {
    fn drop(&mut self) {
        self.epoch.usage.clients.fetch_sub(1, Ordering::AcqRel);
    }
}
/// One explicitly configured origin/client slot, shared across activations.
/// T must own its physical connection; detached driver jobs need their own bounded
/// provider worker lease. Dropping a socket facade is not driver termination.
pub struct ProviderClient<T: Send + 'static> {
    pub(super) core: Arc<ClientCore>,
    idle: Mutex<VecDeque<Idle<T>>>,
}
struct Idle<T> {
    physical: Physical<T>,
    since: Instant,
    capacity_guard: Charge,
}
struct Physical<T> {
    // Rust destroys the real resource before its connection accounting.
    value: T,
    lifetime: ConnectionLifetime,
}
struct ConnectionLifetime {
    client: Arc<ClientCore>,
    failed: bool,
    _metadata: Charge,
    _slot: Charge,
}
impl Drop for ConnectionLifetime {
    fn drop(&mut self) {
        self.client.connections.fetch_sub(1, Ordering::AcqRel);
        if let Some(owner) = self.client.owner.upgrade() {
            if self.failed {
                owner.failed_cleanup.fetch_sub(1, Ordering::AcqRel);
            }
            owner.changed.notify_waiters();
        }
    }
}
impl ProviderPools {
    /// The trusted adapter maps its validated origin list to small opaque slots.
    /// No URL, token, tenant, public service name or credential-derived key is
    /// stored here. Reopening a configured slot returns the same typed client.
    pub fn client<T: Send + 'static>(
        &self,
        provider: &InstalledProvider,
        origin: u16,
    ) -> Result<Arc<ProviderClient<T>>, PlatformError> {
        // This is trusted client-slot configuration, including the second half
        // of provider installation. Maintenance contention must not leave an
        // installed epoch without its configured client. The table contains
        // bounded bookkeeping; physical clients are retired outside its lock.
        let mut state = self.inner.state.lock().map_err(|_| busy())?;
        self.inner.check()?;
        if provider.epoch.retired.load(Ordering::Acquire)
            || !state.epochs.iter().any(|e| Arc::ptr_eq(e, &provider.epoch))
        {
            return Err(denied());
        }
        if let Some(client) = state.clients.iter().find(|c| {
            c.core().epoch.instance == provider.epoch.instance && c.core().origin == origin
        }) {
            return Arc::clone(client)
                .as_any()
                .downcast()
                .map_err(|_| invalid());
        }
        let limits = self.inner.quotas.limits()?;
        let slot = self.inner.quotas.acquire(Kind::Client, 1)?;
        let bytes = std::mem::size_of::<Idle<T>>()
            .checked_mul(limits.maximum_connections_per_client)
            .and_then(|v| v.checked_add(4096))
            .ok_or_else(capacity)?;
        let metadata = self.inner.quotas.acquire(Kind::Metadata, bytes)?;
        limits::increment(
            &provider.epoch.usage.clients,
            1,
            limits.maximum_clients_per_provider,
        )?;
        let client = Arc::new(ProviderClient {
            core: Arc::new(ClientCore {
                epoch: Arc::clone(&provider.epoch),
                origin,
                owner: Arc::downgrade(&self.inner),
                connections: AtomicUsize::new(0),
                backoff: Mutex::new(Backoff {
                    dialing: false,
                    failures: 0,
                    next: None,
                }),
                _metadata: metadata,
                _slot: slot,
            }),
            idle: Mutex::new(VecDeque::with_capacity(
                limits.maximum_connections_per_client,
            )),
        });
        state.clients.push(client.clone());
        state.retained_clients.retain(|old| old.strong_count() != 0);
        let erased: Arc<dyn ErasedClient> = client.clone();
        state.retained_clients.push(Arc::downgrade(&erased));
        Ok(client)
    }
}
impl<T: Send + 'static> ProviderClient<T> {
    /// Stop a configured poller without retiring unrelated node providers.
    /// Actual idle resources are destroyed outside the ownership lock. Active
    /// requests retain their separate owners until their caller drives cleanup.
    pub fn close_idle(&self) -> Result<(), PlatformError> {
        let idle = std::mem::take(&mut *self.idle.try_lock().map_err(|_| busy())?);
        drop(idle);
        Ok(())
    }
    pub fn checkout(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        call.check_client(&self.core)?;
        self.checkout_owned(Some(call.io.lease()), None)
    }
    pub fn checkout_ingress(
        self: &Arc<Self>,
        request: &IngressRequest,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        request.check_client(&self.core)?;
        self.checkout_owned(None, Some(request.clone()))
    }
    fn checkout_owned(
        self: &Arc<Self>,
        activation: Option<IoLease>,
        ingress: Option<IngressRequest>,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        let mut idle = self.idle.try_lock().map_err(|_| busy())?;
        let value = idle.pop_front();
        drop(idle);
        let Some(value) = value else {
            return Ok(None);
        };
        let owner = self.core.owner.upgrade().ok_or_else(denied)?;
        if value.since.elapsed() >= owner.quotas.limits()?.maximum_idle_age {
            return Ok(None);
        }
        let Idle {
            physical,
            capacity_guard,
            ..
        } = value;
        drop(capacity_guard);
        Ok(Some(PooledConnection {
            physical: Some(physical),
            client: Arc::clone(self),
            activation,
            maintenance: None,
            ingress,
        }))
    }
    /// Reserve before a socket/dial task is allocated. One dial per client and
    /// capped exponential backoff prevent reconnect storms; no retry is issued.
    pub fn reserve_connection(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        call.check_client(&self.core)?;
        self.reserve_owned(Some(call.io.lease()), None, None)
    }
    /// Recovery connections retain their finite operator request until the
    /// actual resource is destroyed. They cannot become an idle guest client.
    pub fn reserve_maintenance_connection(
        self: &Arc<Self>,
        request: &MaintenanceRequest,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        request.check_client(&self.core)?;
        self.reserve_owned(None, Some(request.clone()), None)
    }
    /// Inbound work cannot borrow another tenant/client's request capacity.
    pub fn reserve_ingress_connection(
        self: &Arc<Self>,
        request: &IngressRequest,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        request.check_client(&self.core)?;
        self.reserve_owned(None, None, Some(request.clone()))
    }
    fn reserve_owned(
        self: &Arc<Self>,
        activation: Option<IoLease>,
        maintenance: Option<MaintenanceRequest>,
        ingress: Option<IngressRequest>,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        let owner = self.core.owner.upgrade().ok_or_else(denied)?;
        let _state = owner.state.try_lock().map_err(|_| busy())?;
        owner.check()?;
        let limits = owner.quotas.limits()?;
        let mut backoff = self.core.backoff.try_lock().map_err(|_| busy())?;
        if backoff.dialing {
            return Err(busy());
        }
        if backoff.next.is_some_and(|next| next > Instant::now()) {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "provider-backoff",
            ));
        }
        let slot = owner.quotas.acquire(Kind::Connection, 1)?;
        let metadata = owner.quotas.acquire(Kind::Metadata, 4096)?;
        limits::increment(
            &self.core.connections,
            1,
            limits.maximum_connections_per_client,
        )?;
        backoff.dialing = true;
        Ok(ConnectionReservation {
            client: Arc::clone(self),
            activation,
            maintenance,
            ingress,
            lifetime: Some(ConnectionLifetime {
                client: Arc::clone(&self.core),
                failed: false,
                _metadata: metadata,
                _slot: slot,
            }),
            success: false,
        })
    }
    /// Finite failure state only. Readiness never invents a background retry.
    pub fn retry_after(&self) -> Result<Option<Duration>, PlatformError> {
        let state = self.core.backoff.try_lock().map_err(|_| busy())?;
        Ok(state
            .next
            .map(|next| next.saturating_duration_since(Instant::now())))
    }
}
impl<T: Send + 'static> ErasedClient for ProviderClient<T> {
    fn core(&self) -> &Arc<ClientCore> {
        &self.core
    }
    fn as_any(self: Arc<Self>) -> Arc<dyn Any + Send + Sync> {
        self
    }
    fn maintain(&self, now: Instant, closed: bool) {
        let retired = closed || self.core.epoch.retired.load(Ordering::Acquire);
        let maximum = self
            .core
            .owner
            .upgrade()
            .and_then(|o| o.quotas.limits().ok())
            .map_or(Duration::ZERO, |l| l.maximum_idle_age);
        loop {
            let Ok(mut idle) = self.idle.try_lock() else {
                return;
            };
            if !idle.front().is_some_and(|entry| {
                retired || now.saturating_duration_since(entry.since) >= maximum
            }) {
                return;
            }
            let old = idle.pop_front();
            drop(idle);
            drop(old);
        }
    }
}
pub struct ConnectionReservation<T: Send + 'static> {
    client: Arc<ProviderClient<T>>,
    lifetime: Option<ConnectionLifetime>,
    activation: Option<IoLease>,
    maintenance: Option<MaintenanceRequest>,
    ingress: Option<IngressRequest>,
    success: bool,
}
impl<T: Send + 'static> ConnectionReservation<T> {
    pub fn connected(mut self, value: T) -> Result<PooledConnection<T>, PlatformError> {
        if let Some(activation) = &self.activation {
            activation.checkpoint()?;
        } else if let Some(ingress) = &self.ingress {
            ingress.checkpoint()?;
        } else {
            self.maintenance
                .as_ref()
                .expect("operator dial owner")
                .checkpoint()?;
        }
        self.success = true;
        Ok(PooledConnection {
            physical: Some(Physical {
                value,
                lifetime: self.lifetime.take().expect("dial capacity"),
            }),
            client: Arc::clone(&self.client),
            activation: self.activation.take(),
            maintenance: self.maintenance.take(),
            ingress: self.ingress.take(),
        })
    }
}
impl<T: Send + 'static> Drop for ConnectionReservation<T> {
    fn drop(&mut self) {
        let limits = self
            .client
            .core
            .owner
            .upgrade()
            .and_then(|o| o.quotas.limits().ok());
        let mut backoff = self
            .client
            .core
            .backoff
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        backoff.dialing = false;
        if self.success {
            backoff.failures = 0;
            backoff.next = None;
        } else if let Some(limits) = limits {
            backoff.failures = backoff.failures.saturating_add(1).min(32);
            let factor = 1_u32.checked_shl(backoff.failures - 1).unwrap_or(u32::MAX);
            let duration = limits
                .initial_backoff
                .saturating_mul(factor)
                .min(limits.maximum_backoff);
            backoff.next = Instant::now().checked_add(duration);
        }
    }
}
/// Actual connection ownership plus its original activation lease. Neither a
/// cancelled response waiter nor a detached `JoinHandle` can release this charge.
pub struct PooledConnection<T: Send + 'static> {
    physical: Option<Physical<T>>,
    client: Arc<ProviderClient<T>>,
    activation: Option<IoLease>,
    maintenance: Option<MaintenanceRequest>,
    ingress: Option<IngressRequest>,
}
impl<T: Send + 'static> PooledConnection<T> {
    pub(super) fn belongs_to(&self, owner: &Arc<Inner>) -> bool {
        self.client
            .core
            .owner
            .upgrade()
            .is_some_and(|o| Arc::ptr_eq(&o, owner))
    }
    pub fn resource(&mut self) -> &mut T {
        &mut self.physical.as_mut().expect("connection owner").value
    }
    /// Only a protocol adapter that has verified a reusable connection may park
    /// it. Expired/cancelled activations and retired epochs cannot populate idle.
    pub fn park(mut self) -> Result<(), PlatformError> {
        if self.maintenance.is_some() {
            return Err(denied());
        }
        if let Some(activation) = &self.activation {
            activation.checkpoint()?;
        } else {
            self.ingress
                .as_ref()
                .expect("active ingress connection")
                .checkpoint()?;
        }
        let owner = self.client.core.owner.upgrade().ok_or_else(denied)?;
        let _state = owner.state.try_lock().map_err(|_| busy())?;
        owner.check()?;
        if self.client.core.epoch.retired.load(Ordering::Acquire)
            || self
                .physical
                .as_ref()
                .expect("connection owner")
                .lifetime
                .failed
        {
            return Err(denied());
        }
        let charge = owner.quotas.acquire(Kind::Idle, 1)?;
        let mut idle = self.client.idle.try_lock().map_err(|_| busy())?;
        idle.push_back(Idle {
            physical: self.physical.take().expect("connection owner"),
            since: Instant::now(),
            capacity_guard: charge,
        });
        Ok(())
    }
    pub(super) fn cleanup_failed(&mut self) {
        let lifetime = &mut self.physical.as_mut().expect("connection owner").lifetime;
        if !lifetime.failed {
            lifetime.failed = true;
            if let Some(owner) = self.client.core.owner.upgrade() {
                owner.failed_cleanup.fetch_add(1, Ordering::AcqRel);
            }
        }
    }
}
