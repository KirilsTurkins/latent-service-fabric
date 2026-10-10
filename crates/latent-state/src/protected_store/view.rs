use std::any::Any;
use std::sync::{Arc, OnceLock};

use super::physical::PhysicalStore;
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{ReadView, StoreError};
use crate::store_io::{
    StoreIoJob, StoreIoKind, StoreIoRetained, StoreIoRetirement, StoreIoRetirementWitness,
};

/// Coherent host snapshot. The native handle has no public accessor and every
/// read borrows it inside a fixed worker. Drop retires it on those same workers.
pub struct ProtectedStoreView {
    retained: StoreIoRetained<OnceLock<PhysicalStore>, ReadView>,
    recovery: bool,
}

impl ProtectedStoreView {
    /// Capture before moving this view through a job whose response may detach.
    /// One observer is permitted for the entire affine lifetime. A positive
    /// observation proves actual native destruction and physical charge release.
    pub fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.retained.retirement_witness()
    }

    /// Observe actual native view destruction on the fixed storage workers.
    /// Dropping this receipt detaches observation without cancelling cleanup.
    pub fn retire(self) -> StoreIoRetirement {
        self.retained.retire()
    }
}

pub type ProtectedViewResult<T> = (ProtectedStoreView, Result<T, ProtectedStoreError>);
pub type ProtectedViewJob<T> = StoreIoJob<ProtectedViewResult<T>>;

impl ProtectedStoreOwner {
    pub fn open_view(
        &self,
    ) -> Result<StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.open_view_with_owner(None, false)
    }

    /// Retain the original request/global capacity keeper through actual native
    /// view destruction, including detached job responses and retirement after
    /// logical close. It is bound before any worker can open or publish the view.
    pub fn open_view_retaining(
        &self,
        owner: Arc<dyn Any + Send + Sync>,
    ) -> Result<StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.open_view_with_owner(Some(owner), false)
    }

    /// Authenticated host recovery uses the same engine and its existing reserved
    /// I/O/retirement partition. Ordinary pressure cannot take these slots.
    pub fn open_recovery_view_retaining(
        &self,
        owner: Arc<dyn Any + Send + Sync>,
    ) -> Result<StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.open_view_with_owner(Some(owner), true)
    }

    fn open_view_with_owner(
        &self,
        owner: Option<Arc<dyn Any + Send + Sync>>,
        recovery: bool,
    ) -> Result<StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.available()?;
        let mut retained = if recovery {
            self.ready.reserve_recovery_retained::<ReadView>(8192)
        } else {
            self.ready.reserve_retained::<ReadView>(8192)
        }
        .map_err(ProtectedStoreError::Io)?;
        if let Some(owner) = owner {
            retained.retain_owner(owner).map_err(|_| {
                ProtectedStoreError::Io(crate::store_io::StoreIoError::RecoveryRequired)
            })?;
        }
        self.ready
            .submit(
                if recovery {
                    StoreIoKind::RecoveryRead
                } else {
                    StoreIoKind::Read
                },
                0,
                move |store| {
                    store.check()?;
                    let view = store.classify(store.engine().snapshot())?;
                    // This affine reserved slot was created empty. On every failure it
                    // schedules retirement, including detachment before publication.
                    if let Err(view) = retained.attach(view) {
                        drop(view); // already on the native worker
                        return Err(ProtectedStoreError::Io(
                            crate::store_io::StoreIoError::RecoveryRequired,
                        ));
                    }
                    store.check()?;
                    Ok(ProtectedStoreView { retained, recovery })
                },
            )
            .map_err(ProtectedStoreError::Io)
    }

    /// Move the complete host transaction payload into `operation`, declaring
    /// all retained input and possible result bytes. Errors before acceptance
    /// consume this view and enqueue its reserved native retirement.
    pub fn with_view<T: Send + 'static>(
        &self,
        view: ProtectedStoreView,
        retained_payload_bytes: u64,
        operation: impl FnOnce(&ReadView) -> Result<T, StoreError> + Send + 'static,
    ) -> Result<ProtectedViewJob<T>, ProtectedStoreError> {
        if !self.ready.owns_retained(&view.retained) {
            return Err(ProtectedStoreError::ForeignView);
        }
        self.available()?;
        self.ready
            .submit(
                if view.recovery {
                    StoreIoKind::RecoveryRead
                } else {
                    StoreIoKind::Read
                },
                retained_payload_bytes,
                move |store| {
                    let result = (|| {
                        store.check()?;
                        let native = view.retained.get().expect("worker-owned opened read view");
                        let result = store.classify(operation(native));
                        store.check()?;
                        result
                    })();
                    (view, result)
                },
            )
            .map_err(ProtectedStoreError::Io)
    }
}
