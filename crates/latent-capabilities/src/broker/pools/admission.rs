use super::{
    busy, capacity, checked_text, client, denied, invalid, limits, Arc, AtomicBool, AtomicUsize,
    Charge, Epoch, Inner, Instant, Kind, Mutex, Ordering, PlatformError, ProviderClient,
    ProviderPools, State, Weak,
};
use crate::broker::{
    io::{IoAdmission, IoCall, IoReady},
    CapabilitySession, ProviderCall,
};
use std::sync::atomic::{AtomicU64, AtomicU8};

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
pub(super) struct Request {
    owner: Weak<Inner>,
    pub client: Arc<client::ClientCore>,
    tenant: Arc<Tenant>,
    sequence: u64,
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
            owner.changed.notify_waiters();
        }
    }
}
pub struct PoolAdmission {
    io: Option<IoAdmission>,
    request: Arc<Request>,
}
pub struct PoolReady {
    io: IoReady,
    request: Arc<Request>,
}
pub struct PoolCall {
    pub(super) io: IoCall,
    request: Arc<Request>,
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
        let mut state = self.inner.state.try_lock().map_err(|_| busy())?;
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
        let slot = state
            .requests
            .iter()
            .position(|r| r.strong_count() == 0)
            .ok_or_else(capacity)?;
        let tenant = tenant(&mut state, &self.inner, &session.core.plan.target.tenant.0)?;
        let sequence = state.next_request.checked_add(1).ok_or_else(capacity)?;
        let deadline = Instant::now()
            .checked_add(limits.maximum_queue_age)
            .ok_or_else(invalid)?
            .min(io.queue_deadline());
        limits::increment(&tenant.requests, 1, limits.maximum_requests_per_tenant)?;
        if let Err(error) = limits::increment(
            &client.core.epoch.usage.requests,
            1,
            limits.maximum_requests_per_provider,
        ) {
            tenant.requests.fetch_sub(1, Ordering::AcqRel);
            return Err(error);
        }
        let request = Arc::new(Request {
            owner: Arc::downgrade(&self.inner),
            client: Arc::clone(&client.core),
            tenant,
            sequence,
            deadline,
            phase: AtomicU8::new(PENDING),
            waiting: AtomicBool::new(false),
            accounting: Mutex::new(Accounting {
                pending: Some(pending),
                running: None,
            }),
            _metadata: metadata,
        });
        io.retain_owner(request.clone())?;
        state.requests[slot] = Arc::downgrade(&request);
        state.next_request = sequence;
        Ok(PoolAdmission {
            io: Some(io),
            request,
        })
    }
}
fn tenant(state: &mut State, owner: &Arc<Inner>, id: &str) -> Result<Arc<Tenant>, PlatformError> {
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
        let owner = self.request.owner.upgrade().ok_or_else(denied)?;
        self.request.waiting.store(true, Ordering::Release);
        loop {
            let changed = owner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let io = self.io.as_ref().expect("pool admission");
            io.checkpoint()?;
            owner.check()?;
            if self.request.client.epoch.retired.load(Ordering::Acquire) {
                return Err(denied());
            }
            if Instant::now() >= self.request.deadline {
                return Err(expired());
            }
            schedule(&owner)?;
            if self.request.phase.load(Ordering::Acquire) == READY {
                break;
            }
            tokio::select! {
                failure = io.stopped() => return Err(failure),
                () = &mut changed => {},
                () = tokio::time::sleep_until(self.request.deadline.into()) => return Err(expired()),
            }
        }
        // Keep the same absolute I/O queue deadline across both bounded queues.
        let ready = self.io.take().expect("pool admission").wait().await?;
        Ok(PoolReady {
            io: ready,
            request: Arc::clone(&self.request),
        })
    }
}
impl Drop for PoolAdmission {
    fn drop(&mut self) {
        if self.io.is_some() {
            self.request.phase.store(CANCELLED, Ordering::Release);
            if let Some(owner) = self.request.owner.upgrade() {
                owner.changed.notify_waiters();
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
fn schedule(owner: &Arc<Inner>) -> Result<(), PlatformError> {
    let mut state = owner.state.try_lock().map_err(|_| busy())?;
    let limits = owner.quotas.limits()?;
    // Finite work per admission turn. Each granted waiter also schedules peers.
    for _ in 0..16 {
        if owner.quotas.use_of(Kind::Running) >= limits.maximum_running_requests {
            break;
        }
        let mut selected: Option<Arc<Request>> = None;
        for request in state.requests.iter().filter_map(Weak::upgrade) {
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
    Ok(())
}
