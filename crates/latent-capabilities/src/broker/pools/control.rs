use super::{
    busy, capacity, denied, Arc, AtomicUsize, Charge, Inner, Kind, Mutex, Notify, Ordering,
    PlatformError, PoolCall, PooledConnection, ProviderPools,
};
use std::{future::Future, pin::Pin, sync::TryLockError, time::Duration, time::Instant};
use tokio::{sync::oneshot, task::JoinHandle};

pub(super) struct Control {
    handle: tokio::runtime::Handle,
    pub(super) tasks: Mutex<Vec<Option<JoinHandle<()>>>>,
    pub(super) owner_task: Mutex<Option<JoinHandle<()>>>,
    pub owners: AtomicUsize,
    pub failed: super::AtomicBool,
}
impl Control {
    pub fn new(handle: tokio::runtime::Handle, slots: usize) -> Self {
        Self {
            handle,
            tasks: Mutex::new(std::iter::repeat_with(|| None).take(slots).collect()),
            owner_task: Mutex::new(None),
            owners: AtomicUsize::new(0),
            failed: super::AtomicBool::new(false),
        }
    }
}
/// Dropping the waiter never aborts or refunds its actual provider job. Returned
/// protocol data must carry its bounded I/O/connection leases, not bare buffers.
pub struct ProviderJob<T> {
    result: oneshot::Receiver<T>,
}
/// A close-request observation only. No variant certifies backing retirement,
/// releases a connection, or permits provider installation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamKernelCloseObservation {
    NotAttempted,
    RequestAccepted,
    Uncertain,
}

/// Fixed, affine observation storage retains the ORIGINAL cleanup work and
/// metadata charge through buffering and delivery. It carries no refund token.
pub struct StreamKernelCloseReceipt {
    observation: StreamKernelCloseObservation,
    _billing: CloseBilling,
}
impl StreamKernelCloseReceipt {
    pub fn observation(&self) -> StreamKernelCloseObservation {
        self.observation
    }
}

/// One existing cleanup channel, not another observer task or registry.
pub struct StreamKernelCloseJob {
    result: oneshot::Receiver<StreamKernelCloseReceipt>,
    _billing: CloseBilling,
}
impl StreamKernelCloseJob {
    pub async fn wait(mut self) -> Result<StreamKernelCloseReceipt, PlatformError> {
        let observed = (&mut self.result).await;
        // Destroy the receiving channel half BEFORE exposing the charged value.
        // Holding a completed future cannot retain unpaid channel storage.
        drop(self);
        observed.map_err(|_| {
            super::super::error(
                latent_core::PlatformErrorCode::Internal,
                "provider-job-failed",
            )
        })
    }
}
impl<T> ProviderJob<T> {
    pub async fn wait(self) -> Result<T, PlatformError> {
        self.result.await.map_err(|_| {
            super::super::error(
                latent_core::PlatformErrorCode::Internal,
                "provider-job-failed",
            )
        })
    }
}
pub enum CleanupResult<T: Send + 'static> {
    Closed,
    Retained(PooledConnection<T>),
}
pub type CleanupFuture<'a> = Pin<Box<dyn Future<Output = bool> + Send + 'a>>;

// This is the original connection owner, not another retention table or charge.
// It must be armed before a blocking close is submitted: a panic, dropped result
// waiter or runtime submission unwind cannot turn descriptor close into refund.
struct QuarantinedConnection<T: Send + 'static>(Option<PooledConnection<T>>);
impl<T: Send + 'static> Drop for QuarantinedConnection<T> {
    fn drop(&mut self) {
        if let Some(connection) = self.0.take() {
            connection.quarantine();
        }
    }
}
struct JobCharge {
    _metadata: Charge,
    _work: Charge,
    changed: Arc<Notify>,
}

const CLOSE_SHARED_METADATA: usize = 4096;

// ONE carrier for the SAME original JobCharge. Only worker, receiver and receipt
// can own guards (maximum three); no Weak/raw Arc/public Clone can escape.
// Match the existing session Billing pattern: EVERY strong guard uses into_inner
// so the carrier/header is deallocated BEFORE the returned affine charge drops.
struct CloseBilling(Option<Arc<JobCharge>>);
impl CloseBilling {
    fn new(charge: JobCharge) -> Self {
        Self(Some(Arc::new(charge)))
    }
    fn share(&self) -> Self {
        Self(Some(Arc::clone(
            self.0.as_ref().expect("live close billing"),
        )))
    }
}
impl Drop for CloseBilling {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            drop(Arc::into_inner(charge));
        }
    }
}

#[cfg(test)]
pub(super) struct ClosePublicationBarrier {
    pub(super) published: std::sync::mpsc::SyncSender<()>,
    pub(super) resume: std::sync::mpsc::Receiver<()>,
}

// Drop order is custody: quarantine the connection, destroy callback/sender,
// then release worker billing LAST. Capture this WHOLE value via run(), never
// its individual fields, so closure precision cannot split this ordering.
struct StreamCloseWorker<T: Send + 'static, F> {
    retained: QuarantinedConnection<T>,
    close: Option<F>,
    sender: Option<oneshot::Sender<StreamKernelCloseReceipt>>,
    #[cfg(test)]
    after_send: Option<ClosePublicationBarrier>,
    billing: CloseBilling,
}
impl<T, F> StreamCloseWorker<T, F>
where
    T: Send + 'static,
    F: FnOnce(&mut T) -> StreamKernelCloseObservation + Send + 'static,
{
    fn run(mut self) {
        let observation = self.close.take().expect("one physical close")(
            self.retained
                .0
                .as_mut()
                .expect("original cleanup owner")
                .resource(),
        );
        drop(std::mem::replace(
            &mut self.retained,
            QuarantinedConnection(None),
        )); // Original owner is quarantined BEFORE publication.
        let receipt = StreamKernelCloseReceipt {
            observation,
            _billing: self.billing.share(),
        };
        // Worker billing remains live even if send wakes a fast receiver which
        // consumes/drops BOTH its channel half and receipt before send returns.
        let _ = self
            .sender
            .take()
            .expect("one close publication")
            .send(receipt);
        #[cfg(test)]
        if let Some(barrier) = self.after_send.take() {
            barrier.published.send(()).expect("publication observer");
            barrier
                .resume
                .recv_timeout(Duration::from_secs(2))
                .expect("bounded worker-tail release");
        }
    }
}
impl Drop for JobCharge {
    fn drop(&mut self) {
        self.changed.notify_waiters();
    }
}

impl ProviderPools {
    pub fn spawn<F, T>(
        &self,
        call: PoolCall,
        work: impl FnOnce(PoolCall) -> F + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError>
    where
        F: Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        if !call.belongs_to(&self.inner) {
            return Err(denied());
        }
        call.io.checkpoint()?;
        self.spawn_inner(Kind::Worker, false, move || async move { work(call).await })
    }
    pub fn spawn_blocking<T: Send + 'static>(
        &self,
        call: PoolCall,
        work: impl FnOnce(PoolCall) -> T + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError> {
        if !call.belongs_to(&self.inner) {
            return Err(denied());
        }
        call.io.checkpoint()?;
        self.control_blocking(move || work(call))
    }
    /// Retain one admitted call while the fixed worker table is briefly held by
    /// maintenance. The original I/O deadline and cancellation bound this wait;
    /// capacity, retirement and poisoned ownership remain immediate failures.
    pub async fn spawn_blocking_wait<T: Send + 'static>(
        &self,
        call: PoolCall,
        work: impl FnOnce(PoolCall) -> T + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError> {
        if !call.belongs_to(&self.inner) {
            return Err(denied());
        }
        call.io.checkpoint()?;
        let deadline = call.io.deadline();
        let waiter = call.io.job_waiter();
        let lease = call.io.lease();
        let mut work = Some(move || work(call));
        waiter
            .wait(async {
                loop {
                    // The stop observer can already be waiting on its bounded
                    // timer. Recheck immediately before each admission attempt.
                    lease.checkpoint()?;
                    if let Some(job) = self.try_control_blocking(&mut work)? {
                        return Ok(job);
                    }
                    tokio::time::sleep_until(
                        deadline
                            .min(Instant::now() + Duration::from_millis(1))
                            .into(),
                    )
                    .await;
                }
            })
            .await?
    }
    /// Trusted operator work (for example, protected secret reloads) uses the
    /// same finite node worker slots. This is not guest capability authority.
    /// The closure must own prepaid buffers and its actual filesystem work;
    /// abandoning the result waiter never refunds a running physical worker.
    pub fn control_blocking<T: Send + 'static>(
        &self,
        work: impl FnOnce() -> T + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError> {
        self.try_control_blocking(&mut Some(work))?.ok_or_else(busy)
    }
    pub async fn control_blocking_before<T: Send + 'static>(
        &self,
        deadline: Instant,
        work: impl FnOnce() -> T + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError> {
        let mut work = Some(work);
        loop {
            self.inner.check()?;
            if Instant::now() >= deadline {
                return Err(super::super::error(
                    latent_core::PlatformErrorCode::DeadlineExceeded,
                    "provider-control-admission-deadline",
                ));
            }
            if let Some(job) = self.try_control_blocking(&mut work)? {
                return Ok(job);
            }
            tokio::time::sleep_until(
                deadline
                    .min(Instant::now() + Duration::from_millis(1))
                    .into(),
            )
            .await;
        }
    }
    fn try_control_blocking<T: Send + 'static>(
        &self,
        work: &mut Option<impl FnOnce() -> T + Send + 'static>,
    ) -> Result<Option<ProviderJob<T>>, PlatformError> {
        let mut tasks = match self.inner.control.tasks.try_lock() {
            Ok(tasks) => tasks,
            Err(TryLockError::WouldBlock) => return Ok(None),
            Err(TryLockError::Poisoned(_)) => {
                return Err(super::super::error(
                    latent_core::PlatformErrorCode::Unavailable,
                    "provider-control-owner-poisoned",
                ));
            }
        };
        self.inner.check()?;
        let slot = tasks
            .iter()
            .position(Option::is_none)
            .ok_or_else(capacity)?;
        let charge = charge(
            &self.inner,
            Kind::Worker,
            std::mem::size_of_val(work.as_ref().expect("work is retained until admission"))
                .saturating_add(std::mem::size_of::<T>()),
        )?;
        let work = work.take().expect("one control admission owns the work");
        let (send, result) = oneshot::channel();
        tasks[slot] = Some(self.inner.control.handle.spawn_blocking(move || {
            let _charge = charge;
            let value = work();
            // A dropped result waiter destroys actual returned owners here.
            let _ = send.send(value);
        }));
        Ok(Some(ProviderJob { result }))
    }
    /// Cleanup has its own fixed slots and remains available during draining.
    /// Success destroys the actual T before releasing any connection charge;
    /// failure returns the still-owned connection, visibly charged as failed.
    pub fn cleanup<T: Send + 'static>(
        &self,
        mut connection: PooledConnection<T>,
        close: impl for<'a> FnOnce(&'a mut T) -> CleanupFuture<'a> + Send + 'static,
    ) -> Result<ProviderJob<CleanupResult<T>>, PlatformError> {
        if !connection.belongs_to(&self.inner) {
            return Err(denied());
        }
        self.spawn_inner(Kind::Cleanup, true, move || async move {
            if close(connection.resource()).await {
                drop(connection);
                CleanupResult::Closed
            } else {
                connection.cleanup_failed();
                CleanupResult::Retained(connection)
            }
        })
    }
    /// Close a physical facade on the existing finite blocking-worker table,
    /// including during drain, and retain its original owner unconditionally.
    /// There is no caller-supplied retirement boolean. A lost unit-result waiter
    /// cannot destroy the retained resource. Failed admission returns the exact
    /// connection, so the caller can quarantine it without running close inline.
    #[expect(
        clippy::type_complexity,
        reason = "failed admission returns the unchanged affine physical owner"
    )]
    pub fn cleanup_blocking_quarantined<T, F>(
        &self,
        connection: PooledConnection<T>,
        close: F,
    ) -> Result<ProviderJob<()>, (PlatformError, PooledConnection<T>)>
    where
        T: Send + 'static,
        F: FnOnce(&mut T) + Send + 'static,
    {
        if !connection.belongs_to(&self.inner) {
            return Err((denied(), connection));
        }
        let mut tasks = match self.inner.control.tasks.try_lock() {
            Ok(tasks) => tasks,
            Err(TryLockError::WouldBlock) => return Err((busy(), connection)),
            Err(TryLockError::Poisoned(_)) => {
                return Err((
                    super::super::error(
                        latent_core::PlatformErrorCode::Unavailable,
                        "provider-control-owner-poisoned",
                    ),
                    connection,
                ));
            }
        };
        let Some(slot) = tasks.iter().position(Option::is_none) else {
            return Err((capacity(), connection));
        };
        // Same original cleanup quota and metadata ceiling as async cleanup.
        // It remains available after node/provider admission has been closed.
        let charge = match charge(
            &self.inner,
            Kind::Cleanup,
            std::mem::size_of::<QuarantinedConnection<T>>()
                .saturating_add(std::mem::size_of::<F>()),
        ) {
            Ok(charge) => charge,
            Err(error) => return Err((error, connection)),
        };
        let mut retained = QuarantinedConnection(Some(connection));
        let (send, result) = oneshot::channel();
        tasks[slot] = Some(self.inner.control.handle.spawn_blocking(move || {
            let _charge = charge;
            close(
                retained
                    .0
                    .as_mut()
                    .expect("original cleanup owner")
                    .resource(),
            );
            drop(retained); // Actual close returned; capacity is STILL retained.
            let _ = send.send(());
        }));
        Ok(ProviderJob { result })
    }
    /// The same physical/quarantine operation with one fixed stream-close
    /// observation. Accepted CLOSE is data, never a retirement assertion.
    /// Existing general cleanup and ProviderJob behavior remain unchanged.
    pub fn cleanup_stream_kernel_blocking_quarantined<T, F>(
        &self,
        connection: PooledConnection<T>,
        close: F,
    ) -> Result<StreamKernelCloseJob, (PlatformError, PooledConnection<T>)>
    where
        T: Send + 'static,
        F: FnOnce(&mut T) -> StreamKernelCloseObservation + Send + 'static,
    {
        #[cfg(test)]
        {
            self.cleanup_stream_kernel_inner(connection, close, None)
        }
        #[cfg(not(test))]
        {
            self.cleanup_stream_kernel_inner(connection, close)
        }
    }

    #[cfg(test)]
    pub(super) fn cleanup_stream_kernel_with_publication_barrier<T, F>(
        &self,
        connection: PooledConnection<T>,
        close: F,
        barrier: ClosePublicationBarrier,
    ) -> Result<StreamKernelCloseJob, (PlatformError, PooledConnection<T>)>
    where
        T: Send + 'static,
        F: FnOnce(&mut T) -> StreamKernelCloseObservation + Send + 'static,
    {
        self.cleanup_stream_kernel_inner(connection, close, Some(barrier))
    }

    fn cleanup_stream_kernel_inner<T, F>(
        &self,
        connection: PooledConnection<T>,
        close: F,
        #[cfg(test)] after_send: Option<ClosePublicationBarrier>,
    ) -> Result<StreamKernelCloseJob, (PlatformError, PooledConnection<T>)>
    where
        T: Send + 'static,
        F: FnOnce(&mut T) -> StreamKernelCloseObservation + Send + 'static,
    {
        if !connection.belongs_to(&self.inner) {
            return Err((denied(), connection));
        }
        let mut tasks = match self.inner.control.tasks.try_lock() {
            Ok(tasks) => tasks,
            Err(TryLockError::WouldBlock) => return Err((busy(), connection)),
            Err(TryLockError::Poisoned(_)) => {
                return Err((
                    super::super::error(
                        latent_core::PlatformErrorCode::Unavailable,
                        "provider-control-owner-poisoned",
                    ),
                    connection,
                ));
            }
        };
        let Some(slot) = tasks.iter().position(Option::is_none) else {
            return Err((capacity(), connection));
        };
        // Reserve BEFORE carrier/channel/task. Original quotas and job overhead,
        // plus fixed carrier padding and the actual compiled closed-state sizes.
        let charge = match charge(
            &self.inner,
            Kind::Cleanup,
            std::mem::size_of::<StreamCloseWorker<T, F>>()
                .saturating_add(std::mem::size_of::<StreamKernelCloseReceipt>())
                .saturating_add(std::mem::size_of::<StreamKernelCloseJob>())
                .saturating_add(CLOSE_SHARED_METADATA),
        ) {
            Ok(charge) => charge,
            Err(error) => return Err((error, connection)),
        };
        let retained = QuarantinedConnection(Some(connection));
        let billing = CloseBilling::new(charge);
        let (send, result) = oneshot::channel();
        let job = StreamKernelCloseJob {
            result,
            _billing: billing.share(),
        };
        let worker = StreamCloseWorker {
            retained,
            close: Some(close),
            sender: Some(send),
            #[cfg(test)]
            after_send,
            billing,
        };
        tasks[slot] = Some(
            self.inner
                .control
                .handle
                .spawn_blocking(move || worker.run()),
        );
        Ok(job)
    }
    fn spawn_inner<F, T>(
        &self,
        kind: Kind,
        draining: bool,
        work: impl FnOnce() -> F + Send + 'static,
    ) -> Result<ProviderJob<T>, PlatformError>
    where
        F: Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        let mut tasks = self.inner.control.tasks.try_lock().map_err(|_| busy())?;
        if !draining {
            self.inner.check()?;
        }
        let slot = tasks
            .iter()
            .position(Option::is_none)
            .ok_or_else(capacity)?;
        let bytes = std::mem::size_of_val(&work)
            .saturating_add(std::mem::size_of::<F>())
            .saturating_add(std::mem::size_of::<T>());
        let charge = charge(&self.inner, kind, bytes)?;
        let (send, result) = oneshot::channel();
        tasks[slot] = Some(self.inner.control.handle.spawn(async move {
            let _charge = charge;
            let value = work().await;
            let _ = send.send(value);
        }));
        Ok(ProviderJob { result })
    }
}
fn charge(owner: &Inner, kind: Kind, bytes: usize) -> Result<JobCharge, PlatformError> {
    let work = owner.quotas.acquire(kind, 1)?;
    let metadata = owner
        .quotas
        .acquire(Kind::Metadata, bytes.saturating_add(4096))?;
    Ok(JobCharge {
        _metadata: metadata,
        _work: work,
        changed: Arc::clone(&owner.changed),
    })
}
pub(super) fn start(inner: &Arc<Inner>) {
    inner.control.owners.store(1, Ordering::Release);
    let owner = Arc::clone(inner);
    let guard = ControlGuard {
        owner: Arc::downgrade(inner),
        finished: false,
    };
    // One node control task on the supplied runtime. It never performs protocol
    // reconnects, spawns per-service timers, or expands the worker/cleanup arrays.
    let task = inner.control.handle.spawn(async move {
        let mut guard = guard;
        loop {
            let changed = owner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            reap(&owner).await;
            owner.maintain();
            if let Ok(snapshot) = owner.snapshot() {
                let joined = owner.control.tasks.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
                    .iter().all(Option::is_none);
                if snapshot.closed && joined && snapshot.connections == 0 && snapshot.pending_requests == 0
                    && snapshot.running_requests == 0 {
                    owner.changed.notify_waiters();
                    guard.finished = true;
                    break;
                }
            }
            tokio::select! { () = &mut changed => {}, () = tokio::time::sleep(Duration::from_millis(25)) => {} }
        }
    });
    *inner
        .control
        .owner_task
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(task);
}
struct ControlGuard {
    owner: super::Weak<Inner>,
    finished: bool,
}
impl Drop for ControlGuard {
    fn drop(&mut self) {
        if !self.finished {
            if let Some(owner) = self.owner.upgrade() {
                owner.control.failed.store(true, Ordering::Release);
                owner.closed.store(true, Ordering::Release);
                owner.io.retire();
                owner.changed.notify_waiters();
            }
        }
    }
}
pub(super) async fn join_finished_owner(owner: &Inner) {
    let finished = {
        let mut task = owner
            .control
            .owner_task
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if task.as_ref().is_some_and(JoinHandle::is_finished) {
            task.take()
        } else {
            None
        }
    };
    if let Some(task) = finished {
        let _ = task.await;
        owner.control.owners.store(0, Ordering::Release);
        owner.changed.notify_waiters();
    }
}
async fn reap(owner: &Inner) {
    let slots = owner
        .control
        .tasks
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .len();
    for index in 0..slots {
        let finished = {
            let mut tasks = owner
                .control
                .tasks
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if tasks[index].as_ref().is_some_and(JoinHandle::is_finished) {
                tasks[index].take()
            } else {
                None
            }
        };
        if let Some(task) = finished {
            let _ = task.await;
        }
    }
}
