//! Physical reads and preparation sources share deletion admission, not eligibility.
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    RwLock, RwLockReadGuard, RwLockWriteGuard,
};

#[derive(Default)]
pub(super) struct PublicationReads {
    fence: RwLock<()>,
    preparations: AtomicUsize,
    poisoned: AtomicBool,
}
impl PublicationReads {
    pub(super) fn read(&self) -> Result<RwLockReadGuard<'_, ()>, PlatformError> {
        let guard = self.fence.try_read().map_err(|_| busy())?;
        if self.poisoned.load(Ordering::Acquire) {
            return Err(busy());
        }
        Ok(guard)
    }
    pub(super) fn capture(&self) -> bool {
        let Ok(_guard) = self.read() else {
            return false;
        };
        self.increment()
    }
    fn increment(&self) -> bool {
        if self
            .preparations
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                count.checked_add(1)
            })
            .is_err()
        {
            // An impossible counter overflow must never become a false zero.
            self.poisoned.store(true, Ordering::Release);
            return false;
        }
        true
    }
    pub(super) fn clone_preparation(&self) {
        // A live source already excludes deletion. Clones require no lock,
        // allocation, filesystem work, or fallible API.
        self.increment();
    }
    pub(super) fn release(&self) {
        if self
            .preparations
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |count| {
                count.checked_sub(1)
            })
            .is_err()
        {
            self.poisoned.store(true, Ordering::Release);
        }
    }
    pub(super) fn exclusive(&self) -> Result<RwLockWriteGuard<'_, ()>, PlatformError> {
        let guard = self.fence.try_write().map_err(|_| busy())?;
        if self.poisoned.load(Ordering::Acquire) || self.preparations.load(Ordering::Acquire) != 0 {
            return Err(busy());
        }
        Ok(guard)
    }
}
fn busy() -> PlatformError {
    super::error(
        PlatformErrorCode::Unavailable,
        "publication-deletion-readers-active",
    )
}

impl super::DirectoryArtifactRepository {
    pub(crate) fn capture_preparation_read(&self) -> bool {
        self.read_owners.capture()
    }
    pub(crate) fn clone_preparation_read(&self) {
        self.read_owners.clone_preparation();
    }
    pub(crate) fn release_preparation_read(&self) {
        self.read_owners.release();
    }
}
