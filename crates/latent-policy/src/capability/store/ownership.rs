use super::super::{capacity, unavailable};
use latent_core::PlatformError;
use std::sync::{
    atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering},
    Arc, RwLock,
};

/// This compact fence owns no file, catalog map, documents or background task.
pub(super) struct Owner {
    pub fence: RwLock<()>,
    pub live: AtomicBool,
    pub healthy: AtomicBool,
    readers: AtomicUsize,
    mutation_readers: AtomicUsize,
    maximum_readers: usize,
}
impl Owner {
    pub fn new(maximum_readers: usize) -> Arc<Self> {
        Arc::new(Self {
            fence: RwLock::new(()),
            live: AtomicBool::new(true),
            healthy: AtomicBool::new(true),
            readers: AtomicUsize::new(0),
            mutation_readers: AtomicUsize::new(0),
            maximum_readers,
        })
    }
    pub fn check(&self) -> Result<(), PlatformError> {
        if !self.live.load(Ordering::Acquire) || !self.healthy.load(Ordering::Acquire) {
            return Err(unavailable());
        }
        Ok(())
    }
    pub fn lease(self: &Arc<Self>) -> Result<PolicyReadLease, PlatformError> {
        self.check()?;
        self.readers
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                (value < self.maximum_readers).then_some(value + 1)
            })
            .map_err(|_| capacity())?;
        Ok(PolicyReadLease {
            _inner: Arc::new(Lease {
                owner: Arc::clone(self),
                mutation: false,
            }),
        })
    }
    pub fn mutation_lease(self: &Arc<Self>) -> Result<PolicyReadLease, PlatformError> {
        self.check()?;
        // Held snapshots/read pages cannot prevent a revocation from returning
        // its compact receipt. Four separate response owners bound this headroom.
        self.mutation_readers
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                (value < 4).then_some(value + 1)
            })
            .map_err(|_| capacity())?;
        Ok(PolicyReadLease {
            _inner: Arc::new(Lease {
                owner: Arc::clone(self),
                mutation: true,
            }),
        })
    }
    pub fn poison(&self) {
        self.healthy.store(false, Ordering::Release);
    }
    pub fn retire(&self) {
        self.live.store(false, Ordering::Release);
    }
    pub fn readers(&self) -> usize {
        self.readers.load(Ordering::Acquire) + self.mutation_readers.load(Ordering::Acquire)
    }
}
pub(super) struct Stamp {
    pub revision: AtomicU64,
}
impl Stamp {
    pub fn new(revision: u64) -> Arc<Self> {
        Arc::new(Self {
            revision: AtomicU64::new(revision),
        })
    }
}

/// Keep through the final serialization/body/frame owner. Clones share one
/// reservation, so dropping an RPC waiter cannot refund retained response data.
#[derive(Clone)]
pub struct PolicyReadLease {
    _inner: Arc<Lease>,
}
struct Lease {
    owner: Arc<Owner>,
    mutation: bool,
}
impl Drop for Lease {
    fn drop(&mut self) {
        let counter = if self.mutation {
            &self.owner.mutation_readers
        } else {
            &self.owner.readers
        };
        counter.fetch_sub(1, Ordering::AcqRel);
    }
}
pub struct PolicyRead<T> {
    pub(super) value: T,
    pub(super) lease: PolicyReadLease,
}
impl<T> PolicyRead<T> {
    #[must_use]
    pub fn value(&self) -> &T {
        &self.value
    }
    #[must_use]
    pub fn into_parts(self) -> (T, PolicyReadLease) {
        (self.value, self.lease)
    }
}
