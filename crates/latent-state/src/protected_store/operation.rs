use std::sync::{Arc, OnceLock};

use super::physical::{FailureLatch, PhysicalStore};
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::store_io::{StoreIoError, StoreIoRetained, StoreIoRetirement};

/// Affine, bounded physical operation fence. A provider/command owner keeps the
/// exclusive protected root open until its accepted physical operation and
/// buffers have actually retired. This is not a native read view or DB handle.
#[must_use = "retire only after actual physical cleanup; unexpected drop quarantines the root"]
pub struct ProtectedStoreOperation {
    retained: Option<StoreIoRetained<OnceLock<PhysicalStore>, ()>>,
    failure: Arc<FailureLatch>,
}

impl ProtectedStoreOwner {
    /// Reserve before durable claim or any physical provider operation starts.
    /// The same accepted-owner/byte budgets bound all operation pins and their
    /// pre-reserved retirement slots; logical close cannot discard retirement.
    pub fn reserve_operation(&self) -> Result<ProtectedStoreOperation, ProtectedStoreError> {
        self.available()?;
        let retained = self
            .ready
            .reserve_retained(512)
            .map_err(ProtectedStoreError::Io)?;
        Ok(ProtectedStoreOperation {
            retained: Some(retained),
            failure: Arc::clone(&self.failure),
        })
    }
}

impl ProtectedStoreOperation {
    /// Actual cleanup owns this call, including a proven never-started path.
    /// Release is queued on the existing fixed storage workers, even after
    /// logical close/quarantine. Until that release runs, root ownership remains.
    pub fn retire(mut self) -> StoreIoRetirement {
        self.retained
            .take()
            .expect("affine physical operation pin")
            .retire()
    }
}

impl Drop for ProtectedStoreOperation {
    fn drop(&mut self) {
        if let Some(retained) = self.retained.take() {
            self.failure
                .record(ProtectedStoreError::Io(StoreIoError::RecoveryRequired));
            // Losing physical completion evidence cannot release exclusive root
            // and authorize another process/owner while old work may be live.
            // The bounded reserved slot is retained until actual process loss.
            std::mem::forget(retained);
        }
    }
}
