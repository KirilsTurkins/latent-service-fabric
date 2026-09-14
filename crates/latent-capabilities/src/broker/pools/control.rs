use super::{
    busy, capacity, denied, Arc, AtomicUsize, Charge, Inner, Kind, Mutex, Notify, Ordering,
    PlatformError, PoolCall, PooledConnection, ProviderPools,
};
use std::{future::Future, pin::Pin, time::Duration};
use tokio::{sync::oneshot, task::JoinHandle};

pub(super) struct Control {
    handle: tokio::runtime::Handle,
    tasks: Mutex<Vec<Option<JoinHandle<()>>>>,
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
struct JobCharge {
    _metadata: Charge,
    _work: Charge,
    changed: Arc<Notify>,
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
        let mut tasks = self.inner.control.tasks.try_lock().map_err(|_| busy())?;
        self.inner.check()?;
        let slot = tasks
            .iter()
            .position(Option::is_none)
            .ok_or_else(capacity)?;
        let charge = charge(
            &self.inner,
            Kind::Worker,
            std::mem::size_of_val(&work).saturating_add(std::mem::size_of::<T>()),
        )?;
        let (send, result) = oneshot::channel();
        tasks[slot] = Some(self.inner.control.handle.spawn_blocking(move || {
            let _charge = charge;
            let value = work(call);
            // A dropped result waiter destroys actual returned owners here.
            let _ = send.send(value);
        }));
        Ok(ProviderJob { result })
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
