use std::sync::OnceLock;

use super::physical::PhysicalStore;
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{ReadView, StoreError};
use crate::store_io::{StoreIoJob, StoreIoKind, StoreIoRetained};

/// Coherent host snapshot. The native handle has no public accessor and every
/// read borrows it inside a fixed worker. Drop retires it on those same workers.
pub struct ProtectedStoreView {
    retained: StoreIoRetained<OnceLock<PhysicalStore>, ReadView>,
}

pub type ProtectedViewResult<T> = (ProtectedStoreView, Result<T, ProtectedStoreError>);
pub type ProtectedViewJob<T> = StoreIoJob<ProtectedViewResult<T>>;

impl ProtectedStoreOwner {
    pub fn open_view(
        &self,
    ) -> Result<StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.available()?;
        let mut retained = self
            .ready
            .reserve_retained::<ReadView>(8192)
            .map_err(ProtectedStoreError::Io)?;
        self.ready
            .submit(StoreIoKind::Read, 0, move |store| {
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
                Ok(ProtectedStoreView { retained })
            })
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
            .submit(StoreIoKind::Read, retained_payload_bytes, move |store| {
                let result = (|| {
                    store.check()?;
                    let native = view.retained.get().expect("worker-owned opened read view");
                    let result = store.classify(operation(native));
                    store.check()?;
                    result
                })();
                (view, result)
            })
            .map_err(ProtectedStoreError::Io)
    }
}
