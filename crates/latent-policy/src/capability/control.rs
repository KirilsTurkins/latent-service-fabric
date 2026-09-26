//! Bounded work submitted to the existing node control runtime. No resident
//! worker, listener, thread or task is allocated for a dormant policy record.
use super::{capacity, invalid, unavailable, PolicyStore};
use latent_core::{BoxFuture, PlatformError};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    time::Instant,
};
use tokio::{runtime::Handle, sync::Notify};

struct Inner {
    store: Arc<PolicyStore>,
    runtime: Handle,
    maximum_jobs: usize,
    jobs: AtomicUsize,
    stopped: AtomicBool,
    changed: Notify,
}
#[derive(Clone)]
pub struct PolicyControlHandle {
    inner: Arc<Inner>,
}
/// Reserve before cloning a bounded control request. A cancelled waiter never
/// drops this owner while its submitted blocking operation can still commit.
pub struct PolicyWorkPermit {
    inner: Arc<Inner>,
}
impl PolicyControlHandle {
    pub fn new(
        store: Arc<PolicyStore>,
        runtime: Handle,
        maximum_jobs: usize,
    ) -> Result<Self, PlatformError> {
        if !(1..=16).contains(&maximum_jobs) {
            return Err(invalid());
        }
        Ok(Self {
            inner: Arc::new(Inner {
                store,
                runtime,
                maximum_jobs,
                jobs: AtomicUsize::new(0),
                stopped: AtomicBool::new(false),
                changed: Notify::new(),
            }),
        })
    }
    pub fn reserve(&self) -> Result<PolicyWorkPermit, PlatformError> {
        if self.inner.stopped.load(Ordering::Acquire) {
            return Err(unavailable());
        }
        self.inner
            .jobs
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                (value < self.inner.maximum_jobs).then_some(value + 1)
            })
            .map_err(|_| capacity())?;
        let permit = PolicyWorkPermit {
            inner: Arc::clone(&self.inner),
        };
        if self.inner.stopped.load(Ordering::Acquire) {
            return Err(unavailable());
        }
        Ok(permit)
    }
    #[must_use]
    pub fn store(&self) -> &Arc<PolicyStore> {
        &self.inner.store
    }
    #[must_use]
    pub fn active_jobs(&self) -> usize {
        self.inner.jobs.load(Ordering::Acquire)
    }
    #[must_use]
    pub fn maximum_jobs(&self) -> usize {
        self.inner.maximum_jobs
    }
    pub fn retire(&self) {
        self.inner.stopped.store(true, Ordering::Release);
        self.inner.store.retire();
    }
    /// False means real work remains owned; it is never reported as reclaimed.
    /// Filesystem calls that the kernel does not return remain a node/OS limit.
    pub async fn shutdown(&self, deadline: Instant) -> bool {
        self.retire();
        loop {
            let changed = self.inner.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.active_jobs() == 0 {
                return true;
            }
            if tokio::time::timeout_at(deadline.into(), changed)
                .await
                .is_err()
            {
                return self.active_jobs() == 0;
            }
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests;
impl PolicyWorkPermit {
    pub fn run<T: Send + 'static>(
        self,
        action: impl FnOnce(&PolicyStore) -> Result<T, PlatformError> + Send + 'static,
    ) -> BoxFuture<'static, Result<T, PlatformError>> {
        let runtime = self.inner.runtime.clone();
        let task = runtime.spawn_blocking(move || {
            // This permit moves into the actual job, including its queue wait.
            // Its closure and borrowed store work finish before it retires.
            let permit = self;
            if permit.inner.stopped.load(Ordering::Acquire) {
                drop(action);
                return Err(unavailable());
            }
            action(&permit.inner.store)
        });
        Box::pin(async move { task.await.map_err(|_| unavailable())? })
    }
}
impl Drop for PolicyWorkPermit {
    fn drop(&mut self) {
        self.inner.jobs.fetch_sub(1, Ordering::AcqRel);
        self.inner.changed.notify_waiters();
    }
}
