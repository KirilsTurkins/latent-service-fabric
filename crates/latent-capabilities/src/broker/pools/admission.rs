use super::{
    busy, capacity, checked_text, client, denied, invalid, limits, Arc, AtomicBool, AtomicUsize,
    Charge, Epoch, Inner, Instant, Kind, Mutex, Ordering, PlatformError, ProviderClient,
    ProviderPools, State, Weak,
};
use crate::broker::session::{PreparedShared, SessionCoreOwner, Shared, SharedWeak};
use crate::broker::{
    io::{IoAdmission, IoCall, IoReady},
    CapabilitySession, ProviderCall,
};
use std::{
    sync::{
        atomic::{AtomicU64, AtomicU8},
        TryLockError,
    },
    time::Duration,
};

const PENDING: u8 = 0;
const READY: u8 = 1;
const RUNNING: u8 = 2;
const CANCELLED: u8 = 3;

pub(super) struct Tenant {
    id: String,
    pub requests: AtomicUsize,
    pub running: AtomicUsize,
    last_provider: AtomicU64,
    _metadata: Charge,
}
pub(in crate::broker) struct Request {
    owner: Weak<Inner>,
    pub(super) client: Arc<client::ClientCore>,
    tenant: Arc<Tenant>,
    pub(super) sequence: u64,
    slot: usize,
    deadline: Instant,
    phase: AtomicU8,
    waiting: AtomicBool,
    accounting: Mutex<Accounting>,
    _metadata: Charge,
}
struct Accounting {
    pending: Option<Charge>,
    running: Option<Running>,
}
struct Running {
    _quota: Charge,
    tenant: Arc<Tenant>,
    epoch: Arc<Epoch>,
}
impl Drop for Running {
    fn drop(&mut self) {
        self.tenant.running.fetch_sub(1, Ordering::AcqRel);
        self.epoch.usage.running.fetch_sub(1, Ordering::AcqRel);
    }
}
impl Drop for Request {
    fn drop(&mut self) {
        self.tenant.requests.fetch_sub(1, Ordering::AcqRel);
        self.client
            .epoch
            .usage
            .requests
            .fetch_sub(1, Ordering::AcqRel);
        // Drop counters before notifying: no wakeup can mistake a still-held
        // running permit for released capacity and then miss its actual return.
        let accounting = self
            .accounting
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        drop(accounting.running.take());
        drop(accounting.pending.take());
        if let Some(owner) = self.owner.upgrade() {
            retire_slot(&owner, self.slot, self.sequence);
            owner.changed.notify_waiters();
        }
    }
}
pub(in crate::broker) type RequestOwner = Shared<Request>;
pub(super) type RequestWeak = SharedWeak<Request>;

#[derive(Default)]
pub(super) struct RequestSlot {
    sequence: u64,
    request: RequestWeak,
}
fn retire_slot(owner: &Inner, index: usize, sequence: u64) {
    let Some(slot) = owner.requests.get(index) else {
        return;
    };
    let removed = {
        let mut slot = slot
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if slot.sequence == sequence && slot.request.strong_count() == 0 {
            // No user code/Strong drop under this lock. An old destructor may
            // race reuse after strong_count reaches zero; sequence is original.
            std::mem::take(&mut *slot)
        } else {
            RequestSlot::default()
        }
    };
    // The original Shared.billing still owns the full backing until its Arc
    // payload + implicit weak physically retire. Foreign weak clones also pay.
    drop(removed);
}

// Native admission borrows the SAME already-paid immutable session identity.
// Legacy retains its original checked_text String allocation and Drop route.
enum RegistrationTenant {
    Legacy(String),
    Native(SessionCoreOwner),
}
impl RegistrationTenant {
    fn new(session: &CapabilitySession) -> Result<Self, PlatformError> {
        let tenant = &session.core.plan.target.tenant.0;
        if session.core.budget.profile().supports_descendants() {
            if !crate::broker::token(tenant) {
                return Err(invalid());
            }
            Ok(Self::Native(session.core.clone()))
        } else {
            Ok(Self::Legacy(checked_text(tenant)?))
        }
    }
    fn value(&self) -> &str {
        match self {
            Self::Legacy(value) => value,
            Self::Native(core) => &core.plan.target.tenant.0,
        }
    }
}
pub struct PoolAdmission {
    io: Option<IoAdmission>,
    request: Option<RequestOwner>,
    registration: Option<Registration>,
}
struct Registration {
    owner: Arc<Inner>,
    client: Arc<client::ClientCore>,
    tenant: RegistrationTenant,
    backing: Option<PreparedShared<Request>>,
    deadline: Instant,
    pending: Option<Charge>,
    metadata: Option<Charge>,
}
pub struct PoolReady {
    io: IoReady,
    request: RequestOwner,
}
pub struct PoolCall {
    pub(super) io: IoCall,
    request: RequestOwner,
}

impl ProviderPools {
    pub fn admit<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        session: &CapabilitySession,
    ) -> Result<PoolAdmission, PlatformError> {
        self.admit_until(client, session, session.deadline()?)
    }
    /// Narrow once on entry; queue, connection and all body work share this bound.
    pub fn admit_until<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        session: &CapabilitySession,
        deadline: Instant,
    ) -> Result<PoolAdmission, PlatformError> {
        if !Arc::ptr_eq(&session.core.owner, &self.inner.broker.inner)
            || !session.core.plan.bindings.iter().any(|b| {
                Arc::ptr_eq(
                    &b.provider,
                    &client.core.epoch.registration.reference().entry,
                )
            })
        {
            return Err(denied());
        }
        let io = self.inner.io.admit_until(session, deadline)?;
        self.inner.check()?;
        if client.core.epoch.retired.load(Ordering::Acquire)
            || !client
                .core
                .owner
                .upgrade()
                .is_some_and(|o| Arc::ptr_eq(&o, &self.inner))
        {
            return Err(denied());
        }
        let limits = self.inner.quotas.limits()?;
        let pending = self.inner.quotas.acquire(Kind::Pending, 1)?;
        let metadata = self.inner.quotas.acquire(Kind::Metadata, 4096)?;
        let deadline = Instant::now()
            .checked_add(limits.maximum_queue_age)
            .ok_or_else(invalid)?
            .min(io.queue_deadline());
        if RequestOwner::allocation_bytes()? > 4096 {
            return Err(capacity());
        }
        // Original quota/deadline checks precede native admission; both still
        // precede registration text allocation, fairness and publication.
        let backing = RequestOwner::reserve(&session.core.budget)?;
        let mut admission = PoolAdmission {
            io: Some(io),
            request: None,
            registration: Some(Registration {
                owner: Arc::clone(&self.inner),
                client: Arc::clone(&client.core),
                tenant: RegistrationTenant::new(session)?,
                backing: Some(backing),
                deadline,
                pending: Some(pending),
                metadata: Some(metadata),
            }),
        };
        // Reserve finite I/O, queue and metadata ownership before returning.
        // A maintenance reader may delay bookkeeping, never the queue deadline.
        admission.try_register()?;
        Ok(admission)
    }
}
pub(super) fn tenant(
    state: &mut State,
    owner: &Arc<Inner>,
    id: &str,
) -> Result<Arc<Tenant>, PlatformError> {
    if let Some(tenant) = state
        .tenants
        .iter()
        .filter_map(Weak::upgrade)
        .find(|t| t.id == id)
    {
        return Ok(tenant);
    }
    let slot = state
        .tenants
        .iter()
        .position(|t| t.strong_count() == 0)
        .ok_or_else(capacity)?;
    let metadata = owner.quotas.acquire(Kind::Metadata, 1024)?;
    let tenant = Arc::new(Tenant {
        id: checked_text(id)?,
        requests: AtomicUsize::new(0),
        running: AtomicUsize::new(0),
        last_provider: AtomicU64::new(0),
        _metadata: metadata,
    });
    state.tenants[slot] = Arc::downgrade(&tenant);
    Ok(tenant)
}
impl PoolAdmission {
    /// Admit the exact future backing before its source-owned builder runs.
    pub fn prepare_io_future<Make, F>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFuture<Make, F>, PlatformError>
    where
        Make: FnOnce() -> F,
    {
        self.io
            .as_ref()
            .expect("affine admission")
            .prepare_io_future(make)
    }
    /// Admit F before creating/moving effectful Args; factory itself stays private.
    pub fn prepare_io_future_with<Make, F, Args>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFutureWith<Make, F, Args>, PlatformError>
    where
        Make: FnOnce(Args) -> F,
    {
        self.io
            .as_ref()
            .expect("affine admission")
            .prepare_io_future_with(make)
    }
    fn try_register(&mut self) -> Result<bool, PlatformError> {
        let Some(registration) = self.registration.as_mut() else {
            return Ok(true);
        };
        let owner = &registration.owner;
        owner.check()?;
        let io = self.io.as_ref().expect("affine admission");
        io.checkpoint()?;
        if Instant::now() >= registration.deadline {
            return Err(expired());
        }
        let mut state = match owner.state.try_lock() {
            Ok(state) => state,
            Err(TryLockError::WouldBlock) => return Ok(false),
            Err(TryLockError::Poisoned(_)) => return Err(busy()),
        };
        if registration.client.epoch.retired.load(Ordering::Acquire) {
            return Err(denied());
        }
        let limits = owner.quotas.limits()?;
        let slot = owner
            .requests
            .iter()
            .position(|slot| {
                slot.lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .request
                    .strong_count()
                    == 0
            })
            .ok_or_else(capacity)?;
        let tenant = tenant(&mut state, owner, registration.tenant.value())?;
        let sequence = state.next_request.checked_add(1).ok_or_else(capacity)?;
        limits::increment(&tenant.requests, 1, limits.maximum_requests_per_tenant)?;
        if let Err(error) = limits::increment(
            &registration.client.epoch.usage.requests,
            1,
            limits.maximum_requests_per_provider,
        ) {
            tenant.requests.fetch_sub(1, Ordering::AcqRel);
            return Err(error);
        }
        let request = registration
            .backing
            .take()
            .expect("one prepared request")
            .allocate(Request {
                owner: Arc::downgrade(owner),
                client: Arc::clone(&registration.client),
                tenant,
                sequence,
                slot,
                deadline: registration.deadline,
                phase: AtomicU8::new(PENDING),
                waiting: AtomicBool::new(false),
                accounting: Mutex::new(Accounting {
                    pending: registration.pending.take(),
                    running: None,
                }),
                _metadata: registration
                    .metadata
                    .take()
                    .expect("one registration owns metadata"),
            });
        io.retain_owner(request.clone())?;
        let row = RequestSlot {
            sequence,
            request: RequestOwner::downgrade(&request),
        };
        let displaced = {
            let mut slot = owner.requests[slot]
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            std::mem::replace(&mut *slot, row)
        };
        drop(displaced); // native weak/header destruction never holds slot lock
        state.next_request = sequence;
        drop(state);
        self.request = Some(request);
        self.registration = None;
        Ok(true)
    }
    /// A weak observation/cancellation handle for this exact admitted request.
    pub fn stop_handle(&self) -> crate::broker::io::IoStopHandle {
        self.io.as_ref().expect("affine admission").stop_handle()
    }
    /// Materialize borrowed ingress only after this SAME admission prepays it.
    pub fn copy_input(
        &self,
        source: &[u8],
        metadata: usize,
    ) -> Result<super::super::io::IoBuffer, PlatformError> {
        self.io
            .as_ref()
            .expect("affine admission")
            .copy_input(source, metadata)
    }
    pub fn reserve_input(
        &self,
        bytes: usize,
        metadata: usize,
    ) -> Result<super::super::io::IoMemory, PlatformError> {
        self.io
            .as_ref()
            .expect("affine admission")
            .reserve_input(bytes, metadata)
    }
    pub fn input(
        &self,
        capacity: usize,
        protocol_metadata: usize,
    ) -> Result<super::super::io::IoBuffer, PlatformError> {
        self.io
            .as_ref()
            .expect("pool admission")
            .input(capacity, protocol_metadata)
    }
    pub async fn wait(mut self) -> Result<PoolReady, PlatformError> {
        while !self.try_register()? {
            let deadline = self
                .registration
                .as_ref()
                .expect("pending registration")
                .deadline;
            let io = self.io.as_ref().expect("affine admission");
            tokio::select! {
                failure = io.stopped() => return Err(failure),
                () = tokio::time::sleep_until(deadline.min(Instant::now() + Duration::from_millis(1)).into()) => {},
            }
        }
        let request = self.request.as_ref().expect("registered admission").clone();
        let owner = request.owner.upgrade().ok_or_else(denied)?;
        request.waiting.store(true, Ordering::Release);
        loop {
            let changed = owner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let io = self.io.as_ref().expect("pool admission");
            io.checkpoint()?;
            owner.check()?;
            if request.client.epoch.retired.load(Ordering::Acquire) {
                return Err(denied());
            }
            if Instant::now() >= request.deadline {
                return Err(expired());
            }
            let scheduled = schedule(&owner)?;
            if request.phase.load(Ordering::Acquire) == READY {
                break;
            }
            let observation = if scheduled {
                request.deadline
            } else {
                request
                    .deadline
                    .min(Instant::now() + Duration::from_millis(1))
            };
            tokio::select! {
                failure = io.stopped() => return Err(failure),
                () = &mut changed => {},
                () = tokio::time::sleep_until(observation.into()) => {},
            }
        }
        // Keep the same absolute I/O queue deadline across both bounded queues.
        let ready = self.io.take().expect("pool admission").wait().await?;
        Ok(PoolReady { io: ready, request })
    }
}
impl Drop for PoolAdmission {
    fn drop(&mut self) {
        if self.io.is_some() {
            if let Some(request) = &self.request {
                request.phase.store(CANCELLED, Ordering::Release);
                if let Some(owner) = request.owner.upgrade() {
                    owner.changed.notify_waiters();
                }
            }
        }
    }
}

impl PoolReady {
    /// Re-enter the original activation scope after queue admission. This is a
    /// fresh final grant check, not reuse of an Allow DTO captured before waiting.
    pub async fn dispatch(
        self,
        capability: &str,
        operation: &str,
        resource: latent_policy::capability::ResourceTarget<'_>,
        input: &[u8],
        cost: super::super::CapabilityCallCost,
    ) -> Result<PoolCall, PlatformError> {
        let dispatch = self.io.with_session(|session| {
            session.prepare_owned_dispatch(capability, operation, resource, input, cost)
        })?;
        dispatch
            .dispatch(|call| {
                call.require_host_mode()?;
                self.start(call)
            })
            .await?
    }
    pub fn start(self, call: ProviderCall) -> Result<PoolCall, PlatformError> {
        // The broker's guarded dispatch, after both waits, defines acceptance.
        // Rotation after that fence may let this exact accepted old epoch finish.
        if !call.provider_matches(&self.request.client.epoch.registration.reference()) {
            return Err(denied());
        }
        let io = self.io.start(call)?;
        self.request.phase.store(RUNNING, Ordering::Release);
        drop(
            self.request
                .accounting
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .pending
                .take(),
        );
        Ok(PoolCall {
            io,
            request: self.request,
        })
    }
}
impl PoolCall {
    pub(in crate::broker) fn retains_original_request(&self) -> bool {
        self.io.retains_request(&self.request)
    }
    /// Admit the exact future backing before its source-owned builder runs.
    pub fn prepare_io_future<Make, F>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFuture<Make, F>, PlatformError>
    where
        Make: FnOnce() -> F,
    {
        self.io.prepare_io_future(make)
    }
    /// Admit F before creating/moving effectful Args; factory itself stays private.
    pub fn prepare_io_future_with<Make, F, Args>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFutureWith<Make, F, Args>, PlatformError>
    where
        Make: FnOnce(Args) -> F,
    {
        self.io.prepare_io_future_with(make)
    }
    pub(super) fn stream_request(&self) -> &Request {
        &self.request
    }
    pub(super) fn retain_stream_request(&self) -> RequestOwner {
        self.request.clone()
    }
    pub fn io_mut(&mut self) -> &mut IoCall {
        &mut self.io
    }
    #[must_use]
    pub fn io(&self) -> &IoCall {
        &self.io
    }
    pub(super) fn check_client(
        &self,
        client: &Arc<client::ClientCore>,
    ) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(client, &self.request.client) {
            return Err(denied());
        }
        self.io.checkpoint()
    }
    pub(super) fn belongs_to(&self, owner: &Arc<Inner>) -> bool {
        self.request
            .owner
            .upgrade()
            .is_some_and(|o| Arc::ptr_eq(&o, owner))
    }
}
fn expired() -> PlatformError {
    super::super::error(
        latent_core::PlatformErrorCode::DeadlineExceeded,
        "provider-queue-deadline",
    )
}
// Two-level round robin: one tenant cannot gain extra turns by using many
// providers, and one provider cannot starve its tenant's other providers.
fn before(left: &Request, right: &Request, last: &str) -> bool {
    let left_tenant = (left.tenant.id.as_str() <= last, left.tenant.id.as_str());
    let right_tenant = (right.tenant.id.as_str() <= last, right.tenant.id.as_str());
    if left_tenant != right_tenant {
        return left_tenant < right_tenant;
    }
    let last_provider = left.tenant.last_provider.load(Ordering::Acquire);
    let key = |r: &Request| {
        (
            r.client.epoch.usage.identity <= last_provider,
            r.client.epoch.usage.identity,
            r.sequence,
        )
    };
    key(left) < key(right)
}
// False means that this turn could not inspect the registry, not that its
// admitted requests exhausted a budget. Poisoned ownership still fails closed.
fn schedule(owner: &Arc<Inner>) -> Result<bool, PlatformError> {
    let mut state = match owner.state.try_lock() {
        Ok(state) => state,
        Err(TryLockError::WouldBlock) => return Ok(false),
        Err(TryLockError::Poisoned(_)) => {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "provider-pool-owner-poisoned",
            ));
        }
    };
    let limits = owner.quotas.limits()?;
    // Finite work per admission turn. Each granted waiter also schedules peers.
    for _ in 0..16 {
        if owner.quotas.use_of(Kind::Running) >= limits.maximum_running_requests {
            break;
        }
        let mut selected: Option<RequestOwner> = None;
        for slot in &owner.requests {
            let request = {
                let slot = slot
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                slot.request.upgrade()
            };
            let Some(request) = request else {
                continue;
            };
            if request.phase.load(Ordering::Acquire) != PENDING
                || !request.waiting.load(Ordering::Acquire)
                || request.client.epoch.retired.load(Ordering::Acquire)
                || Instant::now() >= request.deadline
                || request.tenant.running.load(Ordering::Acquire)
                    >= limits.maximum_running_per_tenant
                || request.client.epoch.usage.running.load(Ordering::Acquire)
                    >= limits.maximum_running_per_provider
            {
                continue;
            }
            if selected
                .as_ref()
                .is_none_or(|old| before(&request, old, &state.last_tenant))
            {
                selected = Some(request);
            }
        }
        let Some(request) = selected else {
            break;
        };
        let quota = owner.quotas.acquire(Kind::Running, 1)?;
        // Only this registry lock adds running owners; destructors only subtract.
        request.tenant.running.fetch_add(1, Ordering::AcqRel);
        request
            .client
            .epoch
            .usage
            .running
            .fetch_add(1, Ordering::AcqRel);
        let running = Running {
            _quota: quota,
            tenant: Arc::clone(&request.tenant),
            epoch: Arc::clone(&request.client.epoch),
        };
        let mut accounting = request
            .accounting
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if request
            .phase
            .compare_exchange(PENDING, READY, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            continue;
        }
        accounting.running = Some(running);
        request
            .tenant
            .last_provider
            .store(request.client.epoch.usage.identity, Ordering::Release);
        state.last_tenant.clear();
        state.last_tenant.push_str(&request.tenant.id);
        owner.changed.notify_waiters();
    }
    Ok(true)
}

#[cfg(test)]
mod native_tests {
    use super::*;
    use crate::broker::pools::tests::fixture::Setup;

    #[tokio::test]
    async fn native_request_preparation_and_last_weak_keep_original_backing() {
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) =
            setup.native_session_for(&setup.provider, "a", "native-pool-request");
        let baseline = control.budget.host_memory_bytes();
        let guards = control.budget.outstanding_reservations();
        let tenant = RegistrationTenant::new(&session).unwrap();
        assert!(matches!(&tenant, RegistrationTenant::Native(_)));
        assert!(std::ptr::eq(
            tenant.value().as_ptr(),
            session.core.plan.target.tenant.0.as_ptr()
        ));
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(tenant);
        let probe = setup.pools.inner.io.admit(&session).unwrap();
        let operation_bytes = control.budget.host_memory_bytes() - baseline;
        drop(probe);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        let request_bytes = RequestOwner::allocation_bytes().unwrap();
        assert!(request_bytes > 0 && request_bytes <= 4096);
        let padding_bytes =
            control.budget.granted().memory_bytes - baseline - operation_bytes - request_bytes + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        let before = setup.pools.snapshot().unwrap();
        let error = setup.pools.admit(&setup.client, &session).err().unwrap();
        assert_eq!(
            error.code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(setup.pools.snapshot().unwrap(), before);
        assert_eq!(control.budget.host_memory_bytes(), baseline + padding_bytes);
        assert_eq!(control.budget.outstanding_reservations(), guards + 1);
        assert!(setup.pools.inner.requests.iter().all(|slot| slot
            .lock()
            .unwrap()
            .request
            .strong_count()
            == 0));
        drop(padding);
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        assert!(admission.registration.is_none());
        let request = admission.request.as_ref().unwrap();
        let slot = request.slot;
        let last = RequestOwner::downgrade(request);
        let other = last.clone();
        assert_eq!(
            control.budget.host_memory_bytes(),
            baseline + operation_bytes + request_bytes
        );
        drop(admission);
        assert_eq!(setup.pools.snapshot().unwrap().pending_requests, 0);
        assert_eq!(control.budget.host_memory_bytes(), baseline + request_bytes);
        assert_eq!(control.budget.outstanding_reservations(), guards + 1);
        assert!(last.upgrade().is_none());
        // The real registry weak retired without taking the pool state lock.
        // These genuine foreign weak clones still retain FULL physical credit.
        assert_eq!(setup.pools.inner.requests[slot].lock().unwrap().sequence, 0);
        drop(last);
        assert_eq!(control.budget.host_memory_bytes(), baseline + request_bytes);
        drop(other);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);
        let fresh = setup.pools.admit(&setup.client, &session).unwrap();
        let request = fresh.request.as_ref().unwrap();
        let slot = request.slot;
        let sequence = request.sequence;
        retire_slot(&setup.pools.inner, slot, sequence - 1); // stale old Drop
        retire_slot(&setup.pools.inner, slot, sequence); // live key is not retirement
        assert!(setup.pools.inner.requests[slot]
            .lock()
            .unwrap()
            .request
            .ptr_eq_shared(request));
        drop(fresh);
        assert_eq!(setup.pools.inner.requests[slot].lock().unwrap().sequence, 0);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        let (legacy, legacy_control) = setup.session("legacy-registration-string");
        assert!(matches!(
            RegistrationTenant::new(&legacy).unwrap(),
            RegistrationTenant::Legacy(_)
        ));
        assert_eq!(legacy_control.budget.host_memory_bytes(), 0);
    }

    #[tokio::test]
    async fn native_blob_copy_is_affine_and_retains_source_or_copy_until_last_use() {
        use crate::broker::blob::{BlobChunk, BlobError};
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) = setup.native_session_for(&setup.provider, "a", "native-blob-copy");
        let baseline = control.budget.host_memory_bytes();
        let guards = control.budget.outstanding_reservations();
        let call = setup.call(&session).await;
        let mut data = call.io().buffer(8, 512).unwrap();
        let prepared = call.io().reserve_copy(8, 512).unwrap();
        data.spare_mut().unwrap().copy_from_slice(b"resident");
        data.advance_written(8).unwrap();
        let mut chunk = BlobChunk::new(data, prepared, call).unwrap();
        let before = control.budget.host_memory_bytes();
        let copy = chunk.copy_bytes().unwrap();
        assert_eq!(copy.as_ref(), b"resident");
        assert_eq!(control.budget.host_memory_bytes(), before);
        assert!(matches!(chunk.copy_bytes(), Err(BlobError::InvalidState)));
        assert_eq!(control.budget.host_memory_bytes(), before);
        drop(chunk);
        assert_eq!(control.budget.host_memory_bytes(), before - (8 + 64));
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
        assert_eq!(copy.as_ref(), b"resident");
        drop(copy);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);

        // The reverse lifetime also keeps Request/Operation: dropping the copy
        // requests cleaning, but cannot return the still-retained source quota.
        let call = setup.call(&session).await;
        let data = call.io().buffer(1, 512).unwrap(); // genuine valid empty range
        let prepared = call.io().reserve_copy(1, 512).unwrap();
        let mut empty = BlobChunk::new(data, prepared, call).unwrap();
        let empty_copy = empty.copy_bytes().unwrap();
        assert!(empty_copy.as_ref().is_empty());
        assert!(matches!(empty.copy_bytes(), Err(BlobError::InvalidState)));
        drop(empty_copy);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
        assert!(empty.bytes().is_empty());
        drop(empty);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);
        let fresh = setup.call(&session).await;
        drop(fresh);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
    }

    #[tokio::test]
    async fn native_blob_copy_refuses_original_budget_and_foreign_operation_before_copy() {
        use crate::broker::blob::{BlobChunk, BlobError};
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) =
            setup.native_session_for(&setup.provider, "a", "blob-copy-refusal");
        let baseline = control.budget.host_memory_bytes();
        let call = setup.call(&session).await;
        let mut data = call.io().buffer(8, 512).unwrap();
        let before = control.budget.host_memory_bytes();
        let allowance = 8 + 64; // exact private ALLOCATION_BOOKKEEPING envelope
        let padding_bytes = control.budget.granted().memory_bytes - before - allowance + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        let snapshot = setup.pools.inner.io.snapshot();
        let peak = control.budget.snapshot_at(Instant::now()).peak_memory_bytes;
        assert!(call.io().reserve_copy(8, 512).is_err());
        assert_eq!(setup.pools.inner.io.snapshot(), snapshot);
        assert_eq!(control.budget.host_memory_bytes(), before + padding_bytes);
        assert_eq!(
            control.budget.snapshot_at(Instant::now()).peak_memory_bytes,
            peak
        );
        assert!(data.bytes().is_empty()); // no range was read before admission
        drop(padding);
        let scratch = call.io().reserve_scratch(8, 512).unwrap();
        assert_eq!(control.budget.host_memory_bytes(), before); // unchanged logical API
        drop(scratch);
        data.spare_mut().unwrap().copy_from_slice(b"resident");
        data.advance_written(8).unwrap();
        let (foreign, foreign_control) =
            setup.native_session_for(&setup.provider, "a", "blob-copy-foreign");
        let foreign_baseline = foreign_control.budget.host_memory_bytes();
        let other = setup.call(&foreign).await;
        let prepared = other.io().reserve_copy(8, 512).unwrap();
        let before_foreign = foreign_control.budget.host_memory_bytes();
        assert!(matches!(
            BlobChunk::new(data, prepared, call),
            Err(BlobError::PermissionDenied)
        ));
        assert!(foreign_control.budget.host_memory_bytes() < before_foreign);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
        drop(other);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
        assert_eq!(foreign_control.budget.host_memory_bytes(), foreign_baseline);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
    }

    #[tokio::test]
    async fn native_blob_copy_rejects_swapped_pool_call_request_and_io_identity() {
        use crate::broker::blob::{BlobChunk, BlobError};
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (first, first_control) =
            setup.native_session_for(&setup.provider, "a", "blob-copy-swapped-a");
        let (second, second_control) =
            setup.native_session_for(&setup.provider, "a", "blob-copy-swapped-b");
        let first_baseline = first_control.budget.host_memory_bytes();
        let second_baseline = second_control.budget.host_memory_bytes();
        let mut a = setup.call(&first).await;
        let mut b = setup.call(&second).await;
        // Public io_mut is not authority to substitute Request. All three
        // operation pointers below match, while a.request deliberately does not.
        std::mem::swap(a.io_mut(), b.io_mut());
        let data = a.io().buffer(1, 512).unwrap();
        let copy = a.io().reserve_copy(1, 512).unwrap();
        assert!(matches!(
            BlobChunk::new(data, copy, a),
            Err(BlobError::PermissionDenied)
        ));
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 2);
        drop(b);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
        assert_eq!(first_control.budget.host_memory_bytes(), first_baseline);
        assert_eq!(second_control.budget.host_memory_bytes(), second_baseline);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
    }

    #[tokio::test]
    async fn native_blob_input_bridge_refuses_original_budget_before_materialization() {
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) =
            setup.native_session_for(&setup.provider, "a", "blob-input-refusal");
        let baseline = control.budget.host_memory_bytes();
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        let before = control.budget.host_memory_bytes();
        let padding_bytes = control.budget.granted().memory_bytes - before - (8 + 64) + 1;
        let padding = control.budget.reserve_host_memory(padding_bytes).unwrap();
        let snapshot = setup.pools.inner.io.snapshot();
        let peak = control.budget.snapshot_at(Instant::now()).peak_memory_bytes;
        assert_eq!(
            admission.copy_input(b"resident", 512).err().unwrap().code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(setup.pools.inner.io.snapshot(), snapshot);
        assert_eq!(control.budget.host_memory_bytes(), before + padding_bytes);
        assert_eq!(
            control.budget.snapshot_at(Instant::now()).peak_memory_bytes,
            peak
        );
        drop(padding);
        let input = admission.copy_input(b"resident", 512).unwrap();
        assert_eq!(input.bytes(), b"resident");
        assert_eq!(input.capacity(), 8);
        assert_eq!(control.budget.host_memory_bytes(), before + 8 + 64);
        drop(input);
        assert_eq!(control.budget.host_memory_bytes(), before);
        drop(admission);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
    }

    #[tokio::test]
    async fn native_blob_input_bridge_keeps_credit_through_real_worker_observer_cancel() {
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) =
            setup.native_session_for(&setup.provider, "a", "blob-input-worker");
        let baseline = control.budget.host_memory_bytes();
        let guards = control.budget.outstanding_reservations();
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        let input = admission.copy_input(b"resident", 512).unwrap();
        let call = admission
            .wait()
            .await
            .unwrap()
            .start(crate::broker::pools::tests::fixture::dispatch(&session))
            .unwrap();
        let held = control.budget.host_memory_bytes();
        let (entered, started) = tokio::sync::oneshot::channel();
        let (release, blocked) = std::sync::mpsc::sync_channel(1);
        let (finished, completed) = tokio::sync::oneshot::channel();
        let job = setup
            .pools
            .spawn_blocking_wait(call, move |call| {
                assert_eq!(input.bytes(), b"resident");
                entered.send(()).unwrap();
                blocked.recv_timeout(Duration::from_secs(2)).unwrap();
                assert_eq!(input.bytes(), b"resident");
                drop(input); // Physical bytes + same original reservation.
                drop(call);
                let _ = finished.send(());
            })
            .await
            .unwrap();
        tokio::time::timeout(Duration::from_secs(2), started)
            .await
            .unwrap()
            .unwrap();
        control.probe.0.store(true, Ordering::Release);
        drop(job); // Abandon only the response, not its running physical work.
        assert!(control.budget.host_memory_bytes() >= held);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(2), completed)
            .await
            .unwrap()
            .unwrap();
        // Reap the actual normal worker before claiming the final baseline.
        let report = setup
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        assert!(report.is_clean());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
    }

    #[tokio::test]
    async fn native_blob_input_bridge_owns_borrowed_bytes_and_empty_range_without_escape() {
        let setup = Setup::new(super::super::ProviderPoolLimits::default());
        let (session, control) =
            setup.native_session_for(&setup.provider, "a", "blob-input-borrow");
        let baseline = control.budget.host_memory_bytes();
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        let mut source = *b"resident";
        let input = admission.copy_input(&source, 512).unwrap();
        source.fill(0);
        assert_eq!(input.bytes(), b"resident");
        let before_abandon = control.budget.host_memory_bytes();
        drop(admission);
        assert_eq!(input.bytes(), b"resident");
        assert_eq!(control.budget.host_memory_bytes(), before_abandon);
        assert_eq!(setup.pools.inner.io.snapshot().calls, 1);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0); // never dispatched
        drop(input);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
        let fresh = setup.pools.admit(&setup.client, &session).unwrap();
        let before = control.budget.host_memory_bytes();
        let empty = fresh.copy_input(&[], 512).unwrap();
        assert!(empty.bytes().is_empty());
        assert_eq!(empty.capacity(), 1); // Genuine allocated minimum, not a zero-size guess.
        assert_eq!(control.budget.host_memory_bytes(), before + 1 + 64);
        drop(empty);
        assert_eq!(control.budget.host_memory_bytes(), before);
        drop(fresh);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(setup.pools.inner.io.snapshot(), Default::default());
    }
}
