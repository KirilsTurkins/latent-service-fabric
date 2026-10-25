use super::{
    busy, capacity, denied, invalid, limits, Any, Arc, AtomicUsize, Charge, Epoch, ErasedClient,
    IngressRequest, Inner, InstalledProvider, Instant, Kind, MaintenanceRequest, Mutex, Ordering,
    PlatformError, PoolCall, ProviderPools, Weak,
};
use crate::broker::io::IoLease;
use std::{collections::VecDeque, time::Duration};
mod admission;
use admission::{bookkeeping, ClientAccessError};

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
    idle: Mutex<VecDeque<Retained<T>>>,
}
// One existing prepaid physical-owner table, not another admission queue.
// Quarantine entries retain their original client Arc intentionally: losing an
// external provider handle cannot certify unknown physical retirement.
enum Retained<T: Send + 'static> {
    Idle(Idle<T>),
    Connection {
        owner: PooledConnection<T>,
        stream_retirement: Option<fn(&mut T) -> bool>,
    },
    Dial {
        reservation: ConnectionReservation<T>,
        _value: T,
        stream_retirement: Option<fn(&mut T) -> bool>,
    },
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
        // Exact fixed element layout, including the stream callback pointer,
        // BEFORE VecDeque allocation. Original4096 covers unchanged headers.
        let bytes = std::alloc::Layout::array::<Retained<T>>(limits.maximum_connections_per_client)
            .map_err(|_| capacity())?
            .size()
            .checked_add(4096)
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
        loop {
            let mut idle = self.idle.try_lock().map_err(|_| busy())?;
            let Some(index) = idle
                .iter()
                .position(|entry| matches!(entry, Retained::Idle(_)))
            else {
                return Ok(());
            };
            let old = idle.remove(index);
            drop(idle);
            drop(old);
        }
    }
    pub fn checkout(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        call.check_client(&self.core)?;
        self.checkout_owned(Some(call.io.lease()), None)
            .map_err(ClientAccessError::immediate)
    }
    pub fn checkout_ingress(
        self: &Arc<Self>,
        request: &IngressRequest,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        request.check_client(&self.core)?;
        self.checkout_owned(None, Some(request.clone()))
            .map_err(ClientAccessError::immediate)
    }
    fn checkout_owned(
        self: &Arc<Self>,
        activation: Option<IoLease>,
        ingress: Option<IngressRequest>,
    ) -> Result<Option<PooledConnection<T>>, ClientAccessError> {
        let mut idle = bookkeeping(&self.idle)?;
        let value = idle
            .iter()
            .position(|entry| matches!(entry, Retained::Idle(_)))
            .and_then(|index| idle.remove(index));
        drop(idle);
        let Some(Retained::Idle(value)) = value else {
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
            .map_err(ClientAccessError::immediate)
    }
    /// Recovery connections retain their finite operator request until the
    /// actual resource is destroyed. They cannot become an idle guest client.
    pub fn reserve_maintenance_connection(
        self: &Arc<Self>,
        request: &MaintenanceRequest,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        request.check_client(&self.core)?;
        self.reserve_owned(None, Some(request.clone()), None)
            .map_err(ClientAccessError::immediate)
    }
    /// Inbound work cannot borrow another tenant/client's request capacity.
    pub fn reserve_ingress_connection(
        self: &Arc<Self>,
        request: &IngressRequest,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        request.check_client(&self.core)?;
        self.reserve_owned(None, None, Some(request.clone()))
            .map_err(ClientAccessError::immediate)
    }
    fn reserve_owned(
        self: &Arc<Self>,
        activation: Option<IoLease>,
        maintenance: Option<MaintenanceRequest>,
        ingress: Option<IngressRequest>,
    ) -> Result<ConnectionReservation<T>, ClientAccessError> {
        let owner = self.core.owner.upgrade().ok_or_else(denied)?;
        let _state = bookkeeping(&owner.state)?;
        owner.check()?;
        let limits = owner.quotas.limits()?;
        let mut backoff = bookkeeping(&self.core.backoff)?;
        if backoff.dialing {
            let error = busy();
            super::super::http::refusal::observe(
                super::super::http::refusal::Stage::PoolActiveDial,
                &error,
            );
            return Err(error.into());
        }
        if backoff.next.is_some_and(|next| next > Instant::now()) {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "provider-backoff",
            )
            .into());
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
            finished: false,
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
            let Some(index) = idle.iter().position(|entry| match entry {
                Retained::Idle(value) => {
                    retired || now.saturating_duration_since(value.since) >= maximum
                }
                Retained::Connection { owner, .. } => {
                    debug_assert!(owner.physical.is_some());
                    false
                }
                Retained::Dial { reservation, .. } => {
                    debug_assert!(reservation.lifetime.is_some());
                    false
                }
            }) else {
                return;
            };
            let old = idle.remove(index);
            drop(idle);
            drop(old);
        }
    }
    fn progress_stream_quarantine(&self) {
        self.progress_original_stream_quarantine();
    }
}
pub struct ConnectionReservation<T: Send + 'static> {
    client: Arc<ProviderClient<T>>,
    lifetime: Option<ConnectionLifetime>,
    activation: Option<IoLease>,
    maintenance: Option<MaintenanceRequest>,
    ingress: Option<IngressRequest>,
    success: bool,
    finished: bool,
}
impl<T: Send + 'static> ConnectionReservation<T> {
    pub fn connected(self, value: T) -> Result<PooledConnection<T>, PlatformError> {
        self.connected_retaining_on_error(value)
            .map_err(|(error, reservation, value)| {
                drop(value);
                drop(reservation);
                error
            })
    }
    /// A kernel adapter must retain both the original dial and actual resource
    /// when the final currentness check fails after physical allocation.
    #[expect(
        clippy::type_complexity,
        reason = "return the exact original affine owners with the failure"
    )]
    pub fn connected_retaining_on_error(
        mut self,
        value: T,
    ) -> Result<PooledConnection<T>, (PlatformError, Self, T)> {
        let result = if let Some(activation) = &self.activation {
            activation.checkpoint()
        } else if let Some(ingress) = &self.ingress {
            ingress.checkpoint()
        } else {
            self.maintenance
                .as_ref()
                .expect("operator dial owner")
                .checkpoint()
        };
        if let Err(error) = result {
            return Err((error, self, value));
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
    /// Keep a failed/cancelled dial's original leases when its kernel object
    /// has no final-retirement certificate. This entry can never be checked out.
    pub fn quarantine(self, value: T) {
        self.quarantine_with_stream_retirement(value, None);
    }
    /// Trusted stream adapter ONLY: continue this original resource in the
    /// existing paid quarantine, never a new dial/task/admission. The callback
    /// is fixed host code and may return true only after actual native RETIRED
    /// (or proven never-born). It is not a guest-supplied close certificate.
    pub fn quarantine_stream(self, value: T, retirement: fn(&mut T) -> bool) {
        let reference = self.client.core.epoch.registration.reference();
        let stream = reference.capability() == crate::broker::network::STREAM_CAPABILITY
            && reference.profile() == crate::broker::network::STREAM_PROFILE;
        self.quarantine_with_stream_retirement(value, stream.then_some(retirement));
    }
    fn quarantine_with_stream_retirement(
        mut self,
        value: T,
        retirement: Option<fn(&mut T) -> bool>,
    ) {
        let lifetime = self.lifetime.as_mut().expect("dial capacity");
        mark_failed(lifetime);
        self.finish_dial();
        let client = Arc::clone(&self.client);
        client.retain_quarantine(Retained::Dial {
            reservation: self,
            _value: value,
            stream_retirement: retirement,
        });
    }
    fn finish_dial(&mut self) {
        if self.finished {
            return;
        }
        self.finished = true;
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
impl<T: Send + 'static> Drop for ConnectionReservation<T> {
    fn drop(&mut self) {
        self.finish_dial();
    }
}
fn mark_failed(lifetime: &mut ConnectionLifetime) {
    if !lifetime.failed {
        lifetime.failed = true;
        if let Some(owner) = lifetime.client.owner.upgrade() {
            owner.failed_cleanup.fetch_add(1, Ordering::AcqRel);
            owner.changed.notify_waiters();
        }
    }
}
// The original table entry remains affine while its fixed synchronous native
// step runs outside locks. Unwind puts it back BEFORE original fields can Drop.
// The same connection quota reserves its existing VecDeque place throughout.
struct QuarantineStep<'a, T: Send + 'static> {
    client: &'a ProviderClient<T>,
    entry: Option<Retained<T>>,
}
impl<T: Send + 'static> Drop for QuarantineStep<'_, T> {
    fn drop(&mut self) {
        if let Some(entry) = self.entry.take() {
            let mut entries = self
                .client
                .idle
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if entries.len() >= entries.capacity() {
                // Impossible under original connection admission: this local
                // entry STILL holds its slot. Even an invariant violation must
                // not allocate, Drop or refund an unproved physical owner.
                drop(entries);
                self.client.core.epoch.retire();
                std::mem::forget(entry); // Permanently paid, bounded by that slot.
                return;
            }
            entries.push_back(entry);
        }
    }
}
impl<T: Send + 'static> ProviderClient<T> {
    fn progress_original_stream_quarantine(&self) {
        let count = match self.idle.try_lock() {
            Ok(entries) => entries.len(),
            Err(_) => return,
        };
        for _ in 0..count {
            let entry = {
                let Ok(mut entries) = self.idle.try_lock() else {
                    return;
                };
                entries.pop_front()
            };
            let Some(entry) = entry else {
                return;
            };
            let mut step = QuarantineStep {
                client: self,
                entry: Some(entry),
            };
            let retired = match step.entry.as_mut().expect("original retained resource") {
                Retained::Dial {
                    _value,
                    stream_retirement: Some(retire),
                    ..
                } => retire(_value),
                Retained::Connection {
                    owner,
                    stream_retirement: Some(retire),
                } => retire(owner.resource()),
                _ => false, // Original ordinary/unproved quarantine stays permanent.
            };
            if retired {
                let entry = step.entry.take();
                self.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
                drop(entry); // Actual resource/loan/Request/IoLease, OUTSIDE locks.
            }
        }
    }
    fn retain_quarantine(&self, value: Retained<T>) {
        // Every entry already holds exactly one live connection quota. Their
        // total is bounded before any dial, and this table was prepaid for that
        // maximum. No user callback, allocation, retirement guess or await here.
        let mut retained = self
            .idle
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.core.epoch.quarantined.fetch_add(1, Ordering::AcqRel);
        retained.push_back(value);
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
        idle.push_back(Retained::Idle(Idle {
            physical: self.physical.take().expect("connection owner"),
            since: Instant::now(),
            capacity_guard: charge,
        }));
        Ok(())
    }
    /// Permanently retain unproved physical retirement in the original bounded
    /// client table. Only a future source-authenticated platform profile may add
    /// a sealed final-free path; ordinary close/timeout/snapshot cannot release it.
    pub fn quarantine(self) {
        self.quarantine_with_stream_retirement(None);
    }
    /// Same original connection and prepaid quarantine as failed predials.
    pub fn quarantine_stream(self, retirement: fn(&mut T) -> bool) {
        let reference = self.client.core.epoch.registration.reference();
        let stream = reference.capability() == crate::broker::network::STREAM_CAPABILITY
            && reference.profile() == crate::broker::network::STREAM_PROFILE;
        self.quarantine_with_stream_retirement(stream.then_some(retirement));
    }
    fn quarantine_with_stream_retirement(mut self, retirement: Option<fn(&mut T) -> bool>) {
        self.cleanup_failed();
        let client = Arc::clone(&self.client);
        client.retain_quarantine(Retained::Connection {
            owner: self,
            stream_retirement: retirement,
        });
    }
    pub(super) fn cleanup_failed(&mut self) {
        mark_failed(&mut self.physical.as_mut().expect("connection owner").lifetime);
    }
}

#[cfg(test)]
mod stream_quarantine_controls {
    // Actual original pool/lease controls. These do NOT simulate a kernel
    // RETIRED proof or qualify the protected Socket callback.
    use super::super::tests::fixture::{connect, single, Setup};
    use super::*;
    use std::{
        net::TcpStream,
        panic::{catch_unwind, AssertUnwindSafe},
    };
    fn pending(_: &mut TcpStream) -> bool {
        false
    }
    fn panic_step(_: &mut TcpStream) -> bool {
        panic!("fixed retirement callback failed");
    }
    fn retired(_: &mut TcpStream) -> bool {
        true
    }

    #[tokio::test]
    async fn stream_quarantine_false_and_unwind_keep_original_lease_until_completed_step() {
        let setup = Setup::new(single());
        let (session, _control) = setup.session("quarantine-original-lease");
        let observer = session.observer();
        let call = setup.call(&session).await;
        let (connection, _peer) = connect(&setup.client, &call);
        connection.quarantine_with_stream_retirement(Some(pending));
        drop(call);
        drop(session);
        setup.client.progress_original_stream_quarantine();
        assert!(!observer.is_quiescent());
        assert_eq!(setup.client.idle.lock().unwrap().len(), 1);
        assert_eq!(setup.client.core.connections.load(Ordering::Acquire), 1);
        {
            let mut entries = setup.client.idle.lock().unwrap();
            let Retained::Connection {
                stream_retirement, ..
            } = entries.front_mut().unwrap()
            else {
                panic!("same original connection");
            };
            *stream_retirement = Some(panic_step); // Test-only fault injection.
        }
        assert!(catch_unwind(AssertUnwindSafe(|| setup
            .client
            .progress_original_stream_quarantine()))
        .is_err());
        assert!(!observer.is_quiescent());
        assert_eq!(setup.client.idle.lock().unwrap().len(), 1);
        assert_eq!(
            setup.client.core.epoch.quarantined.load(Ordering::Acquire),
            1
        );
        {
            let mut entries = setup.client.idle.lock().unwrap();
            let Retained::Connection {
                stream_retirement, ..
            } = entries.front_mut().unwrap()
            else {
                panic!("same original connection");
            };
            *stream_retirement = Some(retired); // Pool algorithm only, no native proof.
        }
        setup.client.progress_original_stream_quarantine();
        assert_eq!(setup.client.core.connections.load(Ordering::Acquire), 0);
        assert_eq!(
            setup.client.core.epoch.quarantined.load(Ordering::Acquire),
            0
        );
        assert!(observer.is_quiescent());
    }

    #[tokio::test]
    async fn temporarily_dequeued_quarantine_still_funds_its_original_reinsertion_place() {
        let setup = Setup::new(single());
        let (session, _control) = setup.session("quarantine-no-extra-slot");
        let call = setup.call(&session).await;
        let (connection, _peer) = connect(&setup.client, &call);
        connection.quarantine(); // Ordinary None remains permanent.
        let capacity = setup.client.idle.lock().unwrap().capacity();
        let entry = setup.client.idle.lock().unwrap().pop_front().unwrap();
        let step = QuarantineStep {
            client: &setup.client,
            entry: Some(entry),
        };
        // The table is empty, but the original physical slot is NOT available.
        assert!(setup.client.reserve_connection(&call).is_err());
        assert_eq!(setup.client.core.connections.load(Ordering::Acquire), 1);
        drop(step);
        setup.client.progress_original_stream_quarantine();
        let mut entries = setup.client.idle.lock().unwrap();
        assert_eq!(entries.capacity(), capacity);
        assert_eq!(entries.len(), 1);
        let Retained::Connection {
            stream_retirement, ..
        } = entries.front().unwrap()
        else {
            panic!("same original connection");
        };
        assert!(stream_retirement.is_none());
        let old = entries.pop_front();
        drop(entries);
        // Test ends by destroying its actual host TCP resource, not by minting
        // a protected retirement claim or changing the production None path.
        setup
            .client
            .core
            .epoch
            .quarantined
            .fetch_sub(1, Ordering::AcqRel);
        drop(old);
    }
}
