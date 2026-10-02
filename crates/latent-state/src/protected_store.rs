//! One protected, bounded node database. All native work, initialization and
//! affine view retirement belongs to the same fixed storage workers.

mod config;
mod dispatcher;
mod operation;
mod physical;
mod startup;
mod view;

pub use config::{ProtectedStoreConfig, StoreFilesystemProfile};
pub use dispatcher::ProtectedStoreDispatcher;
pub use operation::ProtectedStoreOperation;
pub use startup::{ProtectedStoreDrain, ProtectedStoreStartup};
pub use view::{ProtectedStoreView, ProtectedViewJob, ProtectedViewOpenJob, ProtectedViewResult};

use std::future::Future;
use std::sync::Arc;
use std::time::Instant;

use crate::embedded::{AtomicBatch, StoreError, StoreLimits};
use crate::store_io::{StoreIoError, StoreIoJob, StoreIoKind, StoreIoReady, StoreIoSnapshot};
use physical::{FailureLatch, PhysicalStore};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProtectedStoreError {
    InvalidConfiguration,
    UnsupportedPlatform,
    UnsupportedFilesystem,
    UnsafeRoot,
    ForeignView,
    Store(StoreError),
    Io(StoreIoError),
    /// Physical commit succeeded but its protected ownership fence was lost.
    /// The caller must recover the original command; this is not abort proof.
    CommitUncertain,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ProtectedFencedStoreError<E> {
    Store(ProtectedStoreError),
    Fence(E),
}

/// Readiness contains one node-owned database, never a caller-selected engine.
pub struct ProtectedStoreOwner {
    ready: StoreIoReady<PhysicalStore>,
    failure: Arc<FailureLatch>,
    limits: StoreLimits,
}

impl Clone for ProtectedStoreOwner {
    fn clone(&self) -> Self {
        Self {
            ready: self.ready.clone(),
            failure: Arc::clone(&self.failure),
            limits: self.limits,
        }
    }
}

impl ProtectedStoreOwner {
    /// Trusted namespace/command control operations use this same physical
    /// owner. Declare all retained payload/result bytes and the correct I/O
    /// class. Return bounded owned metadata; native read views use `open_view`
    /// and must not escape this callback. Guest execution never runs here.
    pub fn with_store<T: Send + 'static>(
        &self,
        kind: StoreIoKind,
        retained_payload_bytes: u64,
        operation: impl FnOnce(&crate::embedded::EmbeddedStore) -> Result<T, StoreError>
            + Send
            + 'static,
    ) -> Result<StoreIoJob<Result<T, ProtectedStoreError>>, ProtectedStoreError> {
        self.available()?;
        self.ready
            .submit(kind, retained_payload_bytes, move |store| {
                store.with_store(kind, operation)
            })
            .map_err(ProtectedStoreError::Io)
    }

    /// Reserve captured batch bytes and intermediate encoded rows before queue
    /// allocation. The immutable owned batch executes once if accepted.
    pub fn apply(
        &self,
        batch: AtomicBatch,
    ) -> Result<StoreIoJob<Result<(), ProtectedStoreError>>, ProtectedStoreError> {
        let bytes = batch_charge(&batch, self.limits)?;
        self.available()?;
        self.ready
            .submit(StoreIoKind::Write, bytes, move |store| store.apply(batch))
            .map_err(ProtectedStoreError::Io)
    }

    /// `fence` is the host's short no-I/O acceptance check while the actual
    /// engine writer is still abortable. Protected path checks occur outside it.
    pub fn apply_fenced<E: Send + 'static>(
        &self,
        batch: AtomicBatch,
        fence_retained_bytes: u64,
        fence: impl FnOnce() -> Result<(), E> + Send + 'static,
    ) -> Result<StoreIoJob<Result<(), ProtectedFencedStoreError<E>>>, ProtectedStoreError> {
        let bytes = batch_charge(&batch, self.limits)?
            .checked_add(fence_retained_bytes)
            .ok_or(ProtectedStoreError::InvalidConfiguration)?;
        self.available()?;
        self.ready
            .submit(StoreIoKind::Write, bytes, move |store| {
                store.apply_fenced(batch, fence)
            })
            .map_err(ProtectedStoreError::Io)
    }

    pub fn snapshot(&self) -> Result<StoreIoSnapshot, ProtectedStoreError> {
        self.ready.snapshot().map_err(ProtectedStoreError::Io)
    }

    #[must_use]
    pub fn failure(&self) -> Option<ProtectedStoreError> {
        self.failure.get()
    }

    pub fn close(&self) {
        self.ready.close();
    }

    pub fn quarantine(&self) {
        self.ready.quarantine();
    }

    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<ProtectedStoreDrain<F>, ProtectedStoreError> {
        self.ready
            .drain_async(deadline, wait)
            .map(ProtectedStoreDrain::new)
            .map_err(ProtectedStoreError::Io)
    }

    pub fn reap_retired_threads(&self) -> Result<usize, ProtectedStoreError> {
        self.ready
            .reap_retired_threads()
            .map_err(ProtectedStoreError::Io)
    }

    fn available(&self) -> Result<(), ProtectedStoreError> {
        self.failure.get().map_or(Ok(()), Err)
    }
}

fn batch_charge(batch: &AtomicBatch, limits: StoreLimits) -> Result<u64, ProtectedStoreError> {
    let invalid = || ProtectedStoreError::Store(StoreError::Capacity);
    if batch.expectations.len() > limits.maximum_batch_rows
        || batch.mutations.len() > limits.maximum_batch_rows
    {
        return Err(invalid());
    }
    let entries = batch
        .expectations
        .capacity()
        .checked_add(batch.mutations.capacity())
        .and_then(|entries| {
            entries.checked_mul(std::mem::size_of::<crate::embedded::ExpectedRow>())
        });
    let mut bytes = u64::try_from(entries.ok_or_else(invalid)?).map_err(|_| invalid())?;
    let values = batch
        .expectations
        .iter()
        .map(|row| (&row.key.key, &row.value))
        .chain(batch.mutations.iter().map(|row| (&row.key.key, &row.value)));
    for (key, value) in values {
        let amount = key
            .capacity()
            .checked_add(value.as_ref().map_or(0, Vec::capacity))
            .and_then(|bytes| bytes.checked_mul(2))
            .and_then(|bytes| bytes.checked_add(256))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(invalid)?;
        bytes = bytes.checked_add(amount).ok_or_else(invalid)?;
    }
    Ok(bytes)
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
