//! Fixed-size observation of an owned job's lifetime, not caller authority.
//! One control allocation and timestamp per maximum-jobs-bounded live job;
//! like Job/Waiter bookkeeping, this is fixed compiler overhead, not cached
//! runtime metadata. Clones never retain a repository, artifact or runtime.
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Instant;

#[derive(Clone)]
pub(crate) struct JobControl {
    stopped: Arc<AtomicBool>,
    created: Instant,
    #[cfg(test)]
    waits: Arc<std::sync::atomic::AtomicUsize>,
}

impl JobControl {
    pub(crate) fn new() -> Self {
        Self {
            stopped: Arc::new(AtomicBool::new(false)),
            created: Instant::now(),
            #[cfg(test)]
            waits: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
        }
    }
    pub(crate) fn created(&self) -> Instant {
        self.created
    }
    pub(crate) fn is_stopped(&self) -> bool {
        self.stopped.load(Ordering::Acquire)
    }
    pub(crate) fn stop(&self) {
        self.stopped.store(true, Ordering::Release);
    }
    #[cfg(test)]
    pub(crate) fn record_wait(&self) {
        self.waits.fetch_add(1, Ordering::SeqCst);
    }
    #[cfg(test)]
    pub(super) fn waits(&self) -> usize {
        self.waits.load(Ordering::SeqCst)
    }
    #[cfg(test)]
    pub(super) fn owners(&self) -> usize {
        Arc::strong_count(&self.stopped)
    }
}
