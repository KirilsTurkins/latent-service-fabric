//! Node-owned I/O admission, affine buffers and bounded producer/consumer streams.
//!
//! No executor, worker thread, socket, retry or detached task is created here.
//! Adapters move the call into the actual I/O or bounded blocking-job owner.
use super::session::{Shared, SharedWeak};
use super::{
    capacity, denied, error, invalid, waiting::WaitingCall, CapabilitySession, PlatformError,
    ProviderCall,
};
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformErrorCode};
use std::{
    alloc::Layout,
    marker::PhantomData,
    ops::{Deref, DerefMut},
};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore};

mod audit;
mod buffer;
mod future;
mod limits;
pub use future::{IoFuture, PreparedIoFuture, PreparedIoFutureWith};
mod memory;
pub(in crate::broker) use memory::HttpInputOrigin;
pub use memory::IoMemory;
mod stream;
mod transfer;
pub use buffer::IoBuffer;
use limits::{Charge, Counters, Kind};
pub use limits::{IoLimits, IoSnapshot};
pub use stream::{IoStreamReader, IoStreamTerminal, IoStreamWriter};
pub use transfer::{
    IoInputChunk, IoOutputChunk, IoOutputCopy, IoTransfer, IoTransferBuffer, IoTransferOptions,
    PreparedIoCopy,
};

const OPERATION_METADATA: usize = 2048;
const CANCEL_POLL: Duration = Duration::from_millis(10);
const ALLOCATION_BOOKKEEPING: usize = 64;

fn reserve_allocation(
    budget: &ActivationBudget,
    layout: Layout,
    explicit_host: bool,
) -> Result<Option<HostMemoryReservation>, PlatformError> {
    if layout.size() == 0 || (!explicit_host && !budget.profile().supports_descendants()) {
        return Ok(None);
    }
    let bytes = layout
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
        .and_then(|n| u64::try_from(n).ok())
        .ok_or_else(capacity)?;
    budget
        .reserve_host_memory(bytes)
        .map(Some)
        .map_err(|e| e.to_platform_error())
}

type OperationOwner = Shared<Operation>;
type OperationWeak = SharedWeak<Operation>;

/// One explicitly configured, bounded shared node owner; never service-owned.
pub struct IoRuntime {
    inner: Arc<Inner>,
}
struct Inner {
    limits: IoLimits,
    counters: Arc<Counters>,
    slots: Arc<Semaphore>,
    closed: AtomicBool,
    changed: Notify,
}
impl IoRuntime {
    pub fn new(limits: IoLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            inner: Arc::new(Inner {
                limits,
                counters: Arc::new(Counters::new(limits)),
                slots: Arc::new(Semaphore::new(limits.maximum_running_calls)),
                closed: AtomicBool::new(false),
                changed: Notify::new(),
            }),
        })
    }
    /// Reserve queue/metadata ownership before copying input or allocating a
    /// waiting future. No provider work is authorized until `IoReady::start`.
    pub fn admit(&self, session: &CapabilitySession) -> Result<IoAdmission, PlatformError> {
        self.admit_inner(session, None)
    }
    /// A per-operation timeout is converted once on entry, before queueing. It
    /// may narrow the Store deadline, never extend or restart it after an await.
    pub fn admit_until(
        &self,
        session: &CapabilitySession,
        deadline: Instant,
    ) -> Result<IoAdmission, PlatformError> {
        self.admit_inner(session, Some(deadline))
    }
    fn admit_inner(
        &self,
        session: &CapabilitySession,
        requested: Option<Instant>,
    ) -> Result<IoAdmission, PlatformError> {
        if self.inner.closed.load(Ordering::Acquire) {
            return Err(retired());
        }
        let slot = self.inner.counters.acquire(Kind::Call, 1)?;
        let queue = self.inner.counters.acquire(Kind::Queued, 1)?;
        let metadata = self
            .inner
            .counters
            .acquire(Kind::Metadata, OPERATION_METADATA)?;
        let waiting = WaitingCall::new(session)?;
        let original = waiting.deadline()?;
        let deadline = match requested {
            Some(deadline) if deadline > original => return Err(denied()),
            Some(deadline) => deadline,
            None => original,
        };
        let queue_deadline = Instant::now()
            .checked_add(self.inner.limits.maximum_queue_wait)
            .ok_or_else(invalid)?
            .min(deadline);
        // Node metadata is an independent fixed admission envelope, not an
        // activation-memory charge. Check the complete enlarged physical shell
        // without changing that envelope or any node/session counter.
        let shared_bytes = OperationOwner::allocation_bytes()?;
        let call_bytes = PreparedRunningCall::<ProviderCall>::allocation_bytes()?;
        if shared_bytes
            .checked_add(call_bytes)
            .is_none_or(|n| n > OPERATION_METADATA as u64)
        {
            return Err(capacity());
        }
        // Both actual native backings are admitted before either allocation or
        // provider dispatch. A rejected second request drops the first unused.
        let shared = OperationOwner::reserve(&session.core.budget)?;
        let running = PreparedRunningCall::<ProviderCall>::reserve(&session.core.budget)?;
        let operation = shared.allocate(Operation {
            execution: Mutex::new(Execution {
                authority: Authority::Waiting(waiting),
                running_backing: Some(running),
                slot: None,
                queue: Some(queue),
                output_issued: 0,
                transfer_issued: false,
            }),
            runtime: Arc::clone(&self.inner),
            deadline,
            stop: AtomicBool::new(false),
            waiting: AtomicUsize::new(0),
            cleaning: AtomicBool::new(false),
            owner: Mutex::new(None),
            changed: Notify::new(),
            _metadata: metadata,
            _slot: slot,
        });
        operation.check()?;
        Ok(IoAdmission {
            operation: Some(operation),
            queue_deadline,
        })
    }
    #[must_use]
    pub fn snapshot(&self) -> IoSnapshot {
        let mut snapshot = self.inner.counters.snapshot();
        snapshot.occupied_running_slots =
            self.inner.limits.maximum_running_calls - self.inner.slots.available_permits();
        snapshot
    }
    pub fn retire(&self) {
        self.inner.closed.store(true, Ordering::Release);
        self.inner.slots.close();
        self.inner.changed.notify_waiters();
    }
}
impl Drop for IoRuntime {
    fn drop(&mut self) {
        self.retire();
    }
}

struct Execution {
    // Destroy original activation ownership before returning the running slot.
    authority: Authority,
    // Unallocated running-call body; consumed once only at Waiting -> Running.
    running_backing: Option<PreparedRunningCall<ProviderCall>>,
    slot: Option<OwnedSemaphorePermit>,
    queue: Option<Charge>,
    output_issued: usize,
    transfer_issued: bool,
}
enum Authority {
    Waiting(WaitingCall),
    Running(RunningCall<ProviderCall>),
}
struct Operation {
    execution: Mutex<Execution>,
    runtime: Arc<Inner>,
    deadline: Instant,
    stop: AtomicBool,
    waiting: AtomicUsize,
    cleaning: AtomicBool,
    owner: Mutex<Option<super::pools::RequestOwner>>,
    changed: Notify,
    _metadata: Charge,
    _slot: Charge,
}
// The existing node metadata envelope is logical admission, separate from
// original ActivationBudget physical reservations. No global RSS claim.
const _: () = assert!(
    std::mem::size_of::<Operation>()
        + std::mem::size_of::<ProviderCall>()
        + 2 * std::mem::size_of::<usize>()
        <= OPERATION_METADATA
);

// ProviderCall preparation is sized; the stream ring reuses the same physical owner.
// Type-connected preparation avoids an
// erased/representative Box layout and carries unused credit through queueing.
struct PreparedRunningCall<T> {
    allocation: Option<HostMemoryReservation>,
    value: PhantomData<fn() -> T>,
}
impl<T> PreparedRunningCall<T> {
    fn allocation_bytes() -> Result<u64, PlatformError> {
        let bytes = Layout::new::<T>().size();
        if bytes == 0 {
            return Ok(0);
        }
        bytes
            .checked_add(ALLOCATION_BOOKKEEPING)
            .and_then(|n| u64::try_from(n).ok())
            .ok_or_else(capacity)
    }
    fn reserve(budget: &ActivationBudget) -> Result<Self, PlatformError> {
        let bytes = Self::allocation_bytes()?;
        let allocation = if budget.profile().supports_descendants() && bytes != 0 {
            Some(
                budget
                    .reserve_host_memory(bytes)
                    .map_err(|e| e.to_platform_error())?,
            )
        } else {
            None
        };
        Ok(Self {
            allocation,
            value: PhantomData,
        })
    }
    fn finish(mut self, value: T) -> RunningCall<T> {
        let mut owner = RunningCall {
            value: Some(Box::new(value)),
            allocation: self.allocation.take(),
        };
        // The physical-first Drop is installed BEFORE confirmation may panic.
        if let Some(allocation) = &mut owner.allocation {
            allocation.confirm();
        }
        owner
    }
}
struct RunningCall<T: ?Sized> {
    value: Option<Box<T>>,
    allocation: Option<HostMemoryReservation>,
}
impl<T: ?Sized> RunningCall<T> {
    // The caller admits the exact sized/slice layout BEFORE constructing Box.
    fn from_box(value: Box<T>, allocation: Option<HostMemoryReservation>) -> Self {
        let mut owned = Self {
            value: Some(value),
            allocation,
        };
        if let Some(allocation) = &mut owned.allocation {
            allocation.confirm();
        }
        owned
    }
}
impl<T: ?Sized> Deref for RunningCall<T> {
    type Target = T;
    fn deref(&self) -> &T {
        self.value.as_deref().expect("live running call")
    }
}
impl<T: ?Sized> DerefMut for RunningCall<T> {
    fn deref_mut(&mut self) -> &mut T {
        self.value.as_deref_mut().expect("live running call")
    }
}
// Safe conservative cleanup: if a value destructor unwinds, this SAME original
// guard is retained. No unsafe code, allocator replacement or leaked authority.
struct RefundAfterRetirement(Option<HostMemoryReservation>);
impl RefundAfterRetirement {
    fn refund(mut self) {
        drop(self.0.take());
    }
}
impl Drop for RefundAfterRetirement {
    fn drop(&mut self) {
        if let Some(allocation) = self.0.take() {
            std::mem::forget(allocation);
        }
    }
}
impl<T: ?Sized> Drop for RunningCall<T> {
    fn drop(&mut self) {
        let allocation = RefundAfterRetirement(self.allocation.take());
        drop(self.value.take()); // actual T AND its Box backing retire first
        allocation.refund();
    }
}
impl Operation {
    fn with_session<T>(&self, inspect: impl FnOnce(&CapabilitySession) -> T) -> T {
        let core = {
            let state = self
                .execution
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            match &state.authority {
                Authority::Waiting(waiting) => waiting.core.clone(),
                Authority::Running(call) => call.session_core(),
            }
        };
        // No operation lock survives into a broker/policy/catalog admission.
        CapabilitySession::with_work_scope(core, inspect)
    }
    fn accept_output(&self, bytes: usize) -> Result<(), PlatformError> {
        if self.runtime.closed.load(Ordering::Acquire) {
            return Err(retired());
        }
        if self.stop.load(Ordering::Acquire) {
            return Err(cancelled());
        }
        if Instant::now() >= self.deadline {
            return Err(expired());
        }
        let mut state = self
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Authority::Running(call) = &state.authority else {
            return Err(denied());
        };
        call.check()?;
        let next = state
            .output_issued
            .checked_add(bytes)
            .filter(|n| *n <= call.maximum_output_bytes())
            .ok_or_else(capacity)?;
        // Cumulative policy ceiling, independent of refundable live-byte charges.
        state.output_issued = next;
        Ok(())
    }
    fn effective_deadline(&self) -> Instant {
        let state = self
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &state.authority {
            Authority::Running(call) => call.deadline().min(self.deadline),
            Authority::Waiting(_) => self.deadline,
        }
    }
    fn phase(&self) -> IoWorkPhase {
        if self.cleaning.load(Ordering::Acquire) {
            return IoWorkPhase::Cleaning;
        }
        let state = self
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &state.authority {
            Authority::Waiting(_) if state.slot.is_none() => IoWorkPhase::Queued,
            Authority::Waiting(_) => IoWorkPhase::Ready,
            Authority::Running(_) if self.waiting.load(Ordering::Acquire) != 0 => {
                IoWorkPhase::WaitingProvider
            }
            Authority::Running(_) => IoWorkPhase::Running,
        }
    }
    fn check(&self) -> Result<(), PlatformError> {
        if self.runtime.closed.load(Ordering::Acquire) {
            return Err(retired());
        }
        if self.stop.load(Ordering::Acquire) {
            return Err(cancelled());
        }
        if Instant::now() >= self.deadline {
            use latent_core::diagnostic::{
                ActivationDiagnostic as D, DiagnosticReason as R, DiagnosticStage as S,
            };
            let running = {
                let state = self
                    .execution
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                matches!(state.authority, Authority::Running(_))
            };
            let diagnostic = if running {
                D::new(S::Provider, R::ProviderTimeout)
            } else {
                D::new(S::Queue, R::DeadlineExceeded)
            };
            self.with_session(|session| session.core.observe_diagnostic(diagnostic.clone()));
            return Err(diagnostic.attach(expired()));
        }
        let state = self
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &state.authority {
            Authority::Waiting(waiting) => waiting.check(),
            Authority::Running(call) => call.check(),
        }
    }
    fn request_stop(&self) {
        self.stop.store(true, Ordering::Release);
        self.changed.notify_waiters();
    }
    async fn stopped(&self) -> PlatformError {
        loop {
            let local = self.changed.notified();
            let node = self.runtime.changed.notified();
            tokio::pin!(local, node);
            local.as_mut().enable();
            node.as_mut().enable();
            if let Err(error) = self.check() {
                return error;
            }
            tokio::select! {
                () = &mut local => {}, () = &mut node => {},
                () = tokio::time::sleep_until(self.effective_deadline().into()) => {},
                () = tokio::time::sleep(CANCEL_POLL) => {},
            }
        }
    }
}

/// Cancellation is a request; this weak handle cannot refund real work.
#[derive(Clone)]
pub struct IoStopHandle {
    operation: OperationWeak,
}
/// Internal ownership state; the public activation remains Running while I/O waits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IoWorkPhase {
    Queued,
    Ready,
    Running,
    WaitingProvider,
    Cleaning,
    Retired,
}
impl IoStopHandle {
    /// Observe only the already-owned operation. A weak handle cannot keep an
    /// activation alive, extend its deadline, or authorize provider work.
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.operation.upgrade().ok_or_else(retired)?.check()
    }
    pub fn deadline(&self) -> Result<Instant, PlatformError> {
        let operation = self.operation.upgrade().ok_or_else(retired)?;
        operation.check()?;
        Ok(operation.effective_deadline())
    }
    #[must_use]
    pub fn phase(&self) -> IoWorkPhase {
        self.operation
            .upgrade()
            .map_or(IoWorkPhase::Retired, |op| op.phase())
    }
    pub fn stop(&self) {
        if let Some(op) = self.operation.upgrade() {
            op.request_stop();
        }
    }
}

pub struct IoAdmission {
    operation: Option<OperationOwner>,
    queue_deadline: Instant,
}
impl IoAdmission {
    /// Admit the exact future backing before its source-owned builder runs.
    pub fn prepare_io_future<Make, F>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFuture<Make, F>, PlatformError>
    where
        Make: FnOnce() -> F,
    {
        self.operation
            .as_ref()
            .expect("affine admission")
            .with_session(|session| session.prepare_io_future(make))
    }
    /// Admit F before creating/moving effectful Args; factory itself stays private.
    pub fn prepare_io_future_with<Make, F, Args>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFutureWith<Make, F, Args>, PlatformError>
    where
        Make: FnOnce(Args) -> F,
    {
        self.operation
            .as_ref()
            .expect("affine admission")
            .with_session(|session| session.prepare_io_future_with(make))
    }
    pub(super) fn retain_owner(
        &self,
        owner: super::pools::RequestOwner,
    ) -> Result<(), PlatformError> {
        let mut current = self
            .operation
            .as_ref()
            .expect("affine admission")
            .owner
            .try_lock()
            .map_err(|_| super::busy())?;
        if current.is_some() {
            return Err(denied());
        }
        *current = Some(owner);
        Ok(())
    }
    pub(super) fn queue_deadline(&self) -> Instant {
        self.queue_deadline
    }
    pub(super) fn checkpoint(&self) -> Result<(), PlatformError> {
        self.operation.as_ref().expect("affine admission").check()
    }
    pub(super) async fn stopped(&self) -> PlatformError {
        self.operation
            .as_ref()
            .expect("affine admission")
            .stopped()
            .await
    }
    pub fn input(
        &self,
        capacity: usize,
        protocol_metadata: usize,
    ) -> Result<IoBuffer, PlatformError> {
        IoBuffer::allocate(
            self.operation.as_ref().expect("affine admission"),
            capacity,
            protocol_metadata,
        )
    }
    #[must_use]
    pub fn stop_handle(&self) -> IoStopHandle {
        IoStopHandle {
            operation: self
                .operation
                .as_ref()
                .expect("affine admission")
                .downgrade(),
        }
    }
    pub async fn wait(mut self) -> Result<IoReady, PlatformError> {
        let op = self.operation.as_ref().expect("affine admission");
        op.check()?;
        // Tokio's semaphore queues fairly. The number of waiters and their age
        // were bounded before enqueueing; there is no retry/re-enqueue loop.
        let slot = tokio::select! {
            biased;
            failure = op.stopped() => return Err(failure),
            () = tokio::time::sleep_until(self.queue_deadline.into()) => return Err(expired()),
            slot = Arc::clone(&op.runtime.slots).acquire_owned() => slot.map_err(|_| retired())?,
        };
        op.check()?;
        {
            let mut state = op
                .execution
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.slot = Some(slot);
            drop(state.queue.take());
        }
        Ok(IoReady {
            operation: self.operation.take(),
        })
    }
}
impl Drop for IoAdmission {
    fn drop(&mut self) {
        if let Some(op) = &self.operation {
            op.cleaning.store(true, Ordering::Release);
            op.request_stop();
        }
    }
}

/// Capacity is ready. Re-enter the broker's guarded dispatch now, after waiting.
pub struct IoReady {
    operation: Option<OperationOwner>,
}
impl IoReady {
    pub(super) fn with_session<T>(&self, inspect: impl FnOnce(&CapabilitySession) -> T) -> T {
        self.operation
            .as_ref()
            .expect("affine ready slot")
            .with_session(inspect)
    }
    pub fn start(mut self, call: ProviderCall) -> Result<IoCall, PlatformError> {
        let op = self.operation.as_ref().expect("affine ready slot");
        op.check()?;
        call.check()?;
        let old = {
            let mut state = op
                .execution
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let Authority::Waiting(waiting) = &state.authority else {
                return Err(denied());
            };
            if !waiting
                .core
                .budget
                .is_same_instance(call.budget_accounting())
                || &waiting.core.activation_id != call.activation_id()
                || !call.same_session(&waiting.core)
            {
                return Err(denied());
            }
            let backing = state
                .running_backing
                .take()
                .expect("waiting call owns its preparation");
            let call = backing.finish(call);
            std::mem::replace(&mut state.authority, Authority::Running(call))
        };
        // No temporary gap in activation ownership at the waiting -> running edge.
        drop(old);
        Ok(IoCall {
            operation: self.operation.take().expect("affine ready slot"),
        })
    }
}
impl Drop for IoReady {
    fn drop(&mut self) {
        if let Some(op) = &self.operation {
            op.cleaning.store(true, Ordering::Release);
            op.request_stop();
        }
    }
}

/// Move this into the actual provider future or an existing bounded worker job.
/// Buffers and streams keep the owner charged after a response waiter is dropped.
pub struct IoCall {
    operation: OperationOwner,
}
/// Cancellable response ownership for a separately charged physical worker.
/// Dropping a pending waiter requests stop; it never aborts/refunds that worker.
pub struct IoJobWaiter {
    operation: OperationOwner,
    completed: bool,
}
impl IoJobWaiter {
    pub async fn wait<F: std::future::Future>(
        mut self,
        future: F,
    ) -> Result<F::Output, PlatformError> {
        self.operation.check()?;
        self.operation.waiting.fetch_add(1, Ordering::AcqRel);
        let _waiting = Waiting(&self.operation.waiting);
        let result = tokio::select! {
            biased;
            failure = self.operation.stopped() => Err(failure),
            result = future => { self.operation.check()?; Ok(result) },
        };
        self.completed = result.is_ok();
        result
    }
}
impl Drop for IoJobWaiter {
    fn drop(&mut self) {
        if !self.completed {
            self.operation.request_stop();
        }
    }
}
/// Internal physical-work lease. No constructor can mint another activation.
pub(super) struct IoLease(OperationOwner);
impl IoLease {
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.0.check()
    }
}
impl IoCall {
    pub(in crate::broker) fn retains_request(&self, request: &super::pools::RequestOwner) -> bool {
        self.operation
            .owner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_ref()
            .is_some_and(|owner| Shared::ptr_eq(owner, request))
    }
    /// Admit the exact future backing before its source-owned builder runs.
    pub fn prepare_io_future<Make, F>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFuture<Make, F>, PlatformError>
    where
        Make: FnOnce() -> F,
    {
        self.operation
            .with_session(|session| session.prepare_io_future(make))
    }
    /// Admit F before creating/moving effectful Args; factory itself stays private.
    pub fn prepare_io_future_with<Make, F, Args>(
        &self,
        make: Make,
    ) -> Result<crate::broker::io::PreparedIoFutureWith<Make, F, Args>, PlatformError>
    where
        Make: FnOnce(Args) -> F,
    {
        self.operation
            .with_session(|session| session.prepare_io_future_with(make))
    }
    pub fn recheck_authority(&self) -> Result<(), PlatformError> {
        self.checkpoint()?;
        let mut state = self
            .operation
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Authority::Running(call) = &mut state.authority else {
            return Err(denied());
        };
        call.recheck_authority()
    }
    #[must_use]
    pub fn job_waiter(&self) -> IoJobWaiter {
        IoJobWaiter {
            operation: self.operation.clone(),
            completed: false,
        }
    }
    pub(super) fn with_session<T>(&self, inspect: impl FnOnce(&CapabilitySession) -> T) -> T {
        self.operation.with_session(inspect)
    }
    pub(super) fn lease(&self) -> IoLease {
        IoLease(self.operation.clone())
    }
    /// Yield on the caller's existing runtime, retaining this call and all its
    /// original activation/cell ownership. Cancellation drops only this waiting
    /// future; a detached blocking worker must separately own its actual lease.
    pub async fn wait_for<F: std::future::Future>(
        &self,
        future: F,
    ) -> Result<F::Output, PlatformError> {
        self.checkpoint()?;
        self.operation.waiting.fetch_add(1, Ordering::AcqRel);
        let _waiting = Waiting(&self.operation.waiting);
        tokio::select! {
            biased;
            failure = self.operation.stopped() => Err(failure),
            result = future => { self.checkpoint()?; Ok(result) },
        }
    }
    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.operation.check()
    }
    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.operation.effective_deadline()
    }
    #[must_use]
    pub fn stop_handle(&self) -> IoStopHandle {
        IoStopHandle {
            operation: self.operation.downgrade(),
        }
    }
    pub async fn stopped(&self) -> PlatformError {
        self.operation.stopped().await
    }
    pub fn buffer(
        &self,
        capacity: usize,
        protocol_metadata: usize,
    ) -> Result<IoBuffer, PlatformError> {
        IoBuffer::allocate(&self.operation, capacity, protocol_metadata)
    }
    pub fn stream(&self, depth: usize) -> Result<(IoStreamWriter, IoStreamReader), PlatformError> {
        stream::create(&self.operation, depth)
    }
}
struct Waiting<'a>(&'a AtomicUsize);
impl Drop for Waiting<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}
impl Drop for IoCall {
    fn drop(&mut self) {
        self.operation.cleaning.store(true, Ordering::Release);
    }
}
fn retired() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "io-runtime-retired")
}
fn cancelled() -> PlatformError {
    error(PlatformErrorCode::Cancelled, "io-caller-stopped")
}
fn expired() -> PlatformError {
    error(PlatformErrorCode::DeadlineExceeded, "io-deadline")
}

#[cfg(test)]
mod tests;
