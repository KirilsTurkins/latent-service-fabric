use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};

use super::physical::{FailureLatch, PhysicalStore};
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::StoreError;
use crate::store_io::{StoreIoError, StoreIoJob, StoreIoKind, StoreIoRetained, StoreIoRetirement};

struct Registration(Arc<AtomicBool>);

impl Drop for Registration {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

/// One node dispatcher registration tied to the actual shared physical store.
/// Clone aliases cannot recover/advance epochs while this role remains live.
#[must_use = "retire only after actual dispatcher physical drain"]
pub struct ProtectedStoreDispatcher {
    retained: Option<StoreIoRetained<OnceLock<PhysicalStore>, Registration>>,
    failure: Arc<FailureLatch>,
}

impl ProtectedStoreOwner {
    pub fn reserve_dispatcher(
        &self,
    ) -> Result<
        StoreIoJob<Result<ProtectedStoreDispatcher, ProtectedStoreError>>,
        ProtectedStoreError,
    > {
        self.available()?;
        let mut retained = self
            .ready
            .reserve_retained(512)
            .map_err(ProtectedStoreError::Io)?;
        let failure = Arc::clone(&self.failure);
        self.ready
            .submit(StoreIoKind::Read, 0, move |store| {
                store.check()?;
                store
                    .dispatcher
                    .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                    .map_err(|_| ProtectedStoreError::Store(StoreError::Conflict))?;
                if let Err(registration) =
                    retained.attach(Registration(Arc::clone(&store.dispatcher)))
                {
                    drop(registration);
                    return Err(ProtectedStoreError::Io(StoreIoError::RecoveryRequired));
                }
                store.check()?;
                Ok(ProtectedStoreDispatcher {
                    retained: Some(retained),
                    failure,
                })
            })
            .map_err(ProtectedStoreError::Io)
    }
}

impl ProtectedStoreDispatcher {
    /// Await after all accepted provider work, attempt pins and buffers retire.
    /// Only actual fixed-worker retirement releases this role and its root pin.
    pub fn retire(mut self) -> StoreIoRetirement {
        self.retained
            .take()
            .expect("affine dispatcher role")
            .retire()
    }
}

impl Drop for ProtectedStoreDispatcher {
    fn drop(&mut self) {
        if let Some(retained) = self.retained.take() {
            self.failure
                .record(ProtectedStoreError::Io(StoreIoError::RecoveryRequired));
            std::mem::forget(retained);
        }
    }
}
