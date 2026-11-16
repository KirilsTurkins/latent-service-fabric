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
pub(in crate::broker) use admission::RequestOwner;
mod ingress;
pub use ingress::IngressRequest;
mod deferred;
pub use deferred::DeferredRequest;
mod protocol;
pub use protocol::{
    ProviderMetadata, StreamKernelBacking, StreamKernelBankCharge, StreamKernelNodeBacking,
    StreamKernelOwnership,
};
mod client;
mod control;
mod limits;
mod maintenance;
pub use admission::{PoolAdmission, PoolCall, PoolReady};
pub use client::{ConnectionReservation, PooledConnection, ProviderClient};
pub use control::{
    CleanupFuture, CleanupResult, ProviderJob, StreamKernelCloseJob, StreamKernelCloseObservation,
    StreamKernelCloseReceipt,
};
use limits::{Charge, Kind, Quotas};
pub use limits::{ProviderPoolLimits, ProviderPoolSnapshot};
pub use maintenance::{MaintenanceRequest, ProviderMaintenance};

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

/// A trusted caller may publish an epoch while holding its own state lock, then
/// finish the original pool notification after releasing that lock. Create this
/// guard before acquiring any such lock so unwinding drops the lock first.
#[doc(hidden)]
pub struct DeferredProviderInstall<'a> {
    pools: &'a ProviderPools,
    epoch: Option<Arc<Epoch>>,
    old_epoch: Option<Arc<Epoch>>,
    committed: bool,
}

fn drop_deferred_owner<T>(owner: T) {
    if std::thread::panicking() {
        // Preserve the original unwind while still reaching notification.
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(owner)));
    } else {
        drop(owner);
    }
}

// Run maintenance even if an arbitrary wake callback panics. During an
// existing unwind a second panic is contained so the original is preserved.
fn notify_then_maintain<N: FnOnce(), M: FnOnce()>(notify: N, maintain: M) {
    struct Maintain<M: FnOnce()>(Option<M>);
    impl<M: FnOnce()> Drop for Maintain<M> {
        fn drop(&mut self) {
            if let Some(maintain) = self.0.take() {
                if std::thread::panicking() {
                    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(maintain));
                } else {
                    maintain();
                }
            }
        }
    }
    let _maintain = Maintain(Some(maintain));
    notify();
}

#[cfg(test)]
mod deferred_install_controls {
    use super::{drop_deferred_owner, notify_then_maintain};
    use std::{
        cell::Cell,
        panic::{catch_unwind, AssertUnwindSafe},
    };

    #[test]
    fn notification_panic_still_runs_maintenance_and_propagates() {
        let maintained = Cell::new(false);
        let error = catch_unwind(AssertUnwindSafe(|| {
            notify_then_maintain(|| panic!("wake panic"), || maintained.set(true));
        }))
        .unwrap_err();
        assert_eq!(error.downcast_ref::<&str>(), Some(&"wake panic"));
        assert!(maintained.get());
    }

    #[test]
    fn old_owner_panic_during_unwind_preserves_original_and_completion() {
        struct Old<'a>(&'a Cell<usize>);
        impl Drop for Old<'_> {
            fn drop(&mut self) {
                self.0.set(self.0.get() + 1);
                panic!("old owner panic");
            }
        }
        struct Completion<'a> {
            dropped: &'a Cell<usize>,
            notified: &'a Cell<bool>,
        }
        impl Drop for Completion<'_> {
            fn drop(&mut self) {
                drop_deferred_owner(Old(self.dropped));
                self.notified.set(true);
            }
        }
        let dropped = Cell::new(0);
        let notified = Cell::new(false);
        let error = catch_unwind(AssertUnwindSafe(|| {
            let _completion = Completion {
                dropped: &dropped,
                notified: &notified,
            };
            panic!("original panic");
        }))
        .unwrap_err();
        assert_eq!(error.downcast_ref::<&str>(), Some(&"original panic"));
        assert_eq!(dropped.get(), 1);
        assert!(notified.get());
    }
}

impl DeferredProviderInstall<'_> {
    /// The caller has published the replacement in its own state.
    pub fn commit(&mut self) {
        assert!(self.epoch.is_some(), "no provider installation to commit");
        self.committed = true;
    }

    /// Flush notification and maintenance now; Drop also does so on error.
    pub fn finish(mut self) {
        self.flush();
    }

    fn flush(&mut self) {
        let Some(epoch) = self.epoch.as_ref() else {
            return;
        };
        if !self.committed {
            // A published-but-uncommitted epoch must not remain usable. The old
            // epoch may already be retired; this is fail-closed, not rollback.
            epoch.retire();
        }
        // The replaced epoch may be the final Arc. Keep its original
        // destruction before notification, but outside the caller's lock.
        // Leave the new epoch armed if destruction unwinds, so Drop still
        // performs the pending notification after the caller lock is gone.
        // Every physical client holds its own Arc<Epoch>. A final epoch Arc
        // therefore contains only its fixed bookkeeping, not a live client.
        drop_deferred_owner(self.old_epoch.take());
        let _epoch = self.epoch.take();
        let notify = || self.pools.inner.changed.notify_waiters();
        let maintain = || self.pools.inner.maintain();
        if std::thread::panicking() {
            // A second arbitrary waker panic must not abort the original
            // unwind; the helper still attempts the original maintenance.
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                notify_then_maintain(notify, maintain);
            }));
        } else {
            notify_then_maintain(notify, maintain);
        }
    }
}

impl Drop for DeferredProviderInstall<'_> {
    fn drop(&mut self) {
        self.flush();
    }
}
pub(super) struct Inner {
    broker: Arc<ActivationCapabilityBroker>,
    io: Arc<IoRuntime>,
    quotas: Arc<Quotas>,
    // The SAME one fixed request Vec; per-slot locks let Request::drop retire
    // only its original weak row without taking the caller/pool state lock.
    requests: Vec<Mutex<admission::RequestSlot>>,
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
    tenants: Vec<Weak<admission::Tenant>>,
    last_tenant: String,
}
struct Epoch {
    logical_id: String,
    instance: u64,
    registration: ProviderRegistration,
    credentials: Zeroizing<Vec<u8>>,
    retired: AtomicBool,
    quarantined: AtomicUsize,
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
    /// Close admission to this epoch without refunding its physical owners.
    pub fn retire(&self) {
        self.epoch.retire();
    }
    #[must_use]
    pub fn is_retired(&self) -> bool {
        self.epoch.retired.load(Ordering::Acquire)
    }
    /// Unproved physical retirement, including original failed dial capacity.
    /// This is not a socket-state or readiness inference.
    #[must_use]
    pub fn quarantined_connections(&self) -> usize {
        self.epoch.quarantined.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn logical_id(&self) -> &str {
        &self.epoch.logical_id
    }

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
    fn progress_stream_quarantine(&self);
}
impl ProviderPools {
    pub fn limits(&self) -> Result<ProviderPoolLimits, PlatformError> {
        self.inner.quotas.limits()
    }
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
        if std::mem::size_of::<Mutex<admission::RequestSlot>>() > 128 {
            return Err(capacity());
        }
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
            requests: std::iter::repeat_with(|| Mutex::new(admission::RequestSlot::default()))
                .take(slots)
                .collect(),
            state: Mutex::new(State {
                next_instance: 0,
                next_request: 0,
                epochs: Vec::with_capacity(limits.maximum_configurations),
                retained_epochs: Vec::with_capacity(limits.maximum_configurations),
                clients: Vec::with_capacity(limits.maximum_clients),
                retained_clients: Vec::with_capacity(limits.maximum_clients),
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
        inner
            .broker
            .inner
            .pool_diagnostics
            .set(Arc::downgrade(&inner))
            .map_err(|_| denied())?;
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
        let mut completion = self.defer_install();
        let installed = self.install_deferred(input, expected_epoch, &mut completion)?;
        completion.commit();
        completion.finish();
        Ok(installed)
    }

    /// Construct before taking any caller lock that a waker can re-enter.
    #[doc(hidden)]
    pub fn defer_install(&self) -> DeferredProviderInstall<'_> {
        DeferredProviderInstall {
            pools: self,
            epoch: None,
            old_epoch: None,
            committed: false,
        }
    }

    /// Publish with the original epoch compare-and-swap but defer callbacks.
    /// A successful caller must publish its own state and commit the guard.
    #[doc(hidden)]
    pub fn install_deferred(
        &self,
        input: ProviderSetup<'_>,
        expected_epoch: u64,
        completion: &mut DeferredProviderInstall<'_>,
    ) -> Result<InstalledProvider, PlatformError> {
        if !Arc::ptr_eq(&self.inner, &completion.pools.inner)
            || completion.epoch.is_some()
            || completion.old_epoch.is_some()
            || completion.committed
        {
            return Err(invalid());
        }
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
        // Trusted configuration must complete its bounded registry update even
        // when the maintenance owner briefly inspects the same table. There is
        // no provider I/O or physical resource destruction under this lock.
        let mut state = self.inner.state.lock().map_err(|_| busy())?;
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
            quarantined: AtomicUsize::new(0),
            usage,
            _metadata: metadata,
            _slot: slot,
        });
        // From the first irreversible fence onward, the caller's guard must
        // signal waiters even if subsequent publication unwinds.
        completion.epoch = Some(Arc::clone(&epoch));
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
        // Preserve the replaced owner before any subsequent bookkeeping can
        // unwind; the deferred guard releases it only after caller unlock.
        completion.old_epoch = old;
        state.next_instance = instance;
        state.retained_epochs.retain(|old| old.strong_count() != 0);
        state.retained_epochs.push(Arc::downgrade(&epoch));
        drop(state);
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
    /// Existing paid stream maintenance drives original retained clients, even
    /// after epoch retirement. No new client/table/admission/deadline is minted.
    pub fn maintain_stream_quarantine(&self, provider: &InstalledProvider, _now: Instant) {
        let reference = provider.epoch.registration.reference();
        if reference.capability() != super::network::STREAM_CAPABILITY
            || reference.profile() != super::network::STREAM_PROFILE
        {
            return;
        }
        let count = match self.inner.state.try_lock() {
            Ok(state) => state.retained_clients.len(),
            Err(_) => return,
        };
        for index in 0..count {
            let client = {
                let Ok(state) = self.inner.state.try_lock() else {
                    return;
                };
                state.retained_clients.get(index).and_then(Weak::upgrade)
            };
            if let Some(client) =
                client.filter(|client| Arc::ptr_eq(&client.core().epoch, &provider.epoch))
            {
                client.progress_stream_quarantine();
            }
        }
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
            // Maintenance may hold a snapshot lock while retiring an owner.
            // A refused observation is not a failed shutdown: wait within the
            // original deadline, without retrying or releasing any live work.
            match self.snapshot() {
                Ok(snapshot)
                    if snapshot.connections == 0
                        && snapshot.workers == 0
                        && snapshot.cleanup_jobs == 0
                        && snapshot.running_requests == 0
                        && snapshot.pending_requests == 0
                        && snapshot.control_owners == 0 =>
                {
                    return Ok(snapshot);
                }
                Ok(_) => {}
                Err(error)
                    if error.code == latent_core::PlatformErrorCode::ResourceExhausted
                        && error.message == "capability-busy"
                        && Instant::now() < deadline => {}
                Err(error) => return Err(error),
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
pub(super) fn diagnostic_snapshot(
    owner: &Weak<Inner>,
) -> Result<Option<(ProviderPoolSnapshot, super::io::IoSnapshot)>, PlatformError> {
    owner
        .upgrade()
        .map(|owner| Ok((owner.snapshot()?, owner.io.snapshot())))
        .transpose()
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
