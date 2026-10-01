use std::sync::OnceLock;

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

pub type ProtectedViewOpenJob = StoreIoJob<Result<ProtectedStoreView, ProtectedStoreError>>;
type ViewOpening = (ProtectedViewOpenJob, Option<StoreIoRetirementWitness>);

impl ProtectedStoreOwner {
    pub fn open_view(&self) -> Result<ProtectedViewOpenJob, ProtectedStoreError> {
        self.open_view_inner(false).map(|(job, _)| job)
    }

    /// Issue the single native retirement observer before accepting an open.
    /// The host keeps it across failed opening, response detachment and every
    /// move of the view. No elapsed deadline can complete this observer.
    pub fn open_view_observed(
        &self,
    ) -> Result<(ProtectedViewOpenJob, StoreIoRetirementWitness), ProtectedStoreError> {
        self.open_view_inner(true).map(|(job, witness)| {
            (
                job,
                witness.expect("fresh affine view issues its first observer"),
            )
        })
    }

    fn open_view_inner(&self, observed: bool) -> Result<ViewOpening, ProtectedStoreError> {
        self.available()?;
        let mut retained = self
            .ready
            .reserve_retained::<ReadView>(8192)
            .map_err(ProtectedStoreError::Io)?;
        let witness = if observed {
            retained.retirement_witness()
        } else {
            None
        };
        let job = self
            .ready
            .submit(StoreIoKind::Read, 0, move |store| {
                store.check()?;
                let view = store.classify(store.engine().snapshot())?;
                if let Err(view) = retained.attach(view) {
                    drop(view); // already on the native worker
                    return Err(ProtectedStoreError::Io(
                        crate::store_io::StoreIoError::RecoveryRequired,
                    ));
                }
                store.check()?;
                Ok(ProtectedStoreView { retained })
            })
            .map_err(ProtectedStoreError::Io)?;
        Ok((job, witness))
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
