use std::sync::{Arc, Mutex, OnceLock};

use super::{ProtectedFencedStoreError, ProtectedStoreConfig, ProtectedStoreError};
use crate::embedded::{
    AtomicBatch, EmbeddedStore, Family, FencedStoreError, ReadView, RowKey, StoreError,
    StoreFileStatus,
};
use crate::store_io::{StoreIoError, StoreIoKind};

#[derive(Default)]
pub(super) struct FailureLatch {
    error: Mutex<Option<ProtectedStoreError>>,
    gate: OnceLock<Box<dyn Fn(StoreIoError) + Send + Sync>>,
}

impl FailureLatch {
    pub fn get(&self) -> Option<ProtectedStoreError> {
        *self
            .error
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn install(&self, gate: impl Fn(StoreIoError) + Send + Sync + 'static) {
        let _ = self.gate.set(Box::new(gate));
    }

    pub fn record(&self, error: ProtectedStoreError) {
        {
            let mut first = self
                .error
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            first.get_or_insert(error);
        }
        if let Some(gate) = self.gate.get() {
            gate(StoreIoError::RecoveryRequired);
        }
    }
}

pub(super) struct PhysicalStore {
    engine: Option<EmbeddedStore>,
    pub(super) status: StoreFileStatus,
    failure: Arc<FailureLatch>,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    root: latent_protected_files::ProtectedRoot,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fence: latent_protected_files::ProtectedMutableFile,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    root_lock: std::fs::File,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    lock_fence: latent_protected_files::ProtectedMutableFile,
}

impl PhysicalStore {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub fn initialize(
        config: &ProtectedStoreConfig,
        failure: Arc<FailureLatch>,
        validator: impl FnOnce(&ReadView) -> Result<(), StoreError>,
    ) -> Result<Self, ProtectedStoreError> {
        use latent_protected_files::ProtectedRoot;
        let root =
            ProtectedRoot::open(&config.root).map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        if root
            .filesystem_type()
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?
            != 0xef53
        {
            return Err(ProtectedStoreError::UnsupportedFilesystem);
        }
        // Engine-file locking alone would allow two configured leaf names to
        // establish distinct databases in one supposedly exclusive node root.
        let (root_lock, lock_fence) = root
            .open_mutable_file("transaction-owner.lock", 1, true)
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        root_lock
            .try_lock()
            .map_err(|_| ProtectedStoreError::Store(StoreError::Unavailable))?;
        let (file, fence) = root
            .open_mutable_file(
                &config.file_name,
                config.maximum_file_bytes,
                config.create_if_missing,
            )
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        let (engine, status) =
            EmbeddedStore::open_bounded_file(file, config.engine, config.maximum_file_bytes)
                .map_err(ProtectedStoreError::Store)?;
        {
            let view = engine.snapshot().map_err(ProtectedStoreError::Store)?;
            validator(&view).map_err(ProtectedStoreError::Store)?;
        }
        root.check_mutable_file(&lock_fence)
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        root.check_mutable_file(&fence)
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        Ok(Self {
            engine: Some(engine),
            status,
            failure,
            root,
            fence,
            root_lock,
            lock_fence,
        })
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    pub fn initialize(
        _: &ProtectedStoreConfig,
        _: Arc<FailureLatch>,
        _: impl FnOnce(&ReadView) -> Result<(), StoreError>,
    ) -> Result<Self, ProtectedStoreError> {
        Err(ProtectedStoreError::UnsupportedPlatform)
    }

    pub fn engine(&self) -> &EmbeddedStore {
        self.engine.as_ref().expect("worker-owned live engine")
    }

    pub fn check(&self) -> Result<(), ProtectedStoreError> {
        if let Some(error) = self.failure.get() {
            return Err(error);
        }
        self.check_root()
            .inspect_err(|error| self.failure.record(*error))
    }

    #[cfg_attr(
        not(all(target_os = "linux", target_arch = "x86_64")),
        allow(clippy::unused_self)
    )]
    fn check_root(&self) -> Result<(), ProtectedStoreError> {
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            self.root
                .check_mutable_file(&self.lock_fence)
                .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
            self.root
                .check_mutable_file(&self.fence)
                .map_err(|_| ProtectedStoreError::UnsafeRoot)
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            Err(ProtectedStoreError::UnsupportedPlatform)
        }
    }

    pub fn classify<T>(&self, result: Result<T, StoreError>) -> Result<T, ProtectedStoreError> {
        result.map_err(|error| {
            let error = ProtectedStoreError::Store(error);
            if matches!(
                error,
                ProtectedStoreError::Store(
                    StoreError::Corrupt
                        | StoreError::UnsupportedFormat
                        | StoreError::Unavailable
                        | StoreError::CommitUncertain
                )
            ) {
                self.failure.record(error);
            }
            error
        })
    }

    pub fn apply(&self, batch: AtomicBatch) -> Result<(), ProtectedStoreError> {
        match self.apply_fenced(batch, || Ok::<(), std::convert::Infallible>(())) {
            Ok(()) => Ok(()),
            Err(ProtectedFencedStoreError::Store(error)) => Err(error),
            Err(ProtectedFencedStoreError::Fence(impossible)) => match impossible {},
        }
    }

    pub fn with_store<T>(
        &self,
        kind: StoreIoKind,
        operation: impl FnOnce(&EmbeddedStore) -> Result<T, StoreError>,
    ) -> Result<T, ProtectedStoreError> {
        self.check()?;
        let result = self.classify(operation(self.engine()));
        if self.check_root().is_err() {
            let error = if kind == StoreIoKind::Write && result.is_ok() {
                ProtectedStoreError::CommitUncertain
            } else {
                ProtectedStoreError::UnsafeRoot
            };
            self.failure.record(error);
            return Err(error);
        }
        result
    }

    pub fn apply_fenced<E>(
        &self,
        batch: AtomicBatch,
        fence: impl FnOnce() -> Result<(), E>,
    ) -> Result<(), ProtectedFencedStoreError<E>> {
        self.check().map_err(ProtectedFencedStoreError::Store)?;
        match self.engine().apply_fenced(batch, fence) {
            Ok(()) => {
                if self.check_root().is_err() {
                    self.failure.record(ProtectedStoreError::CommitUncertain);
                    return Err(ProtectedFencedStoreError::Store(
                        ProtectedStoreError::CommitUncertain,
                    ));
                }
                Ok(())
            }
            Err(FencedStoreError::Store(error)) => Err(ProtectedFencedStoreError::Store(
                self.classify::<()>(Err(error)).unwrap_err(),
            )),
            Err(FencedStoreError::Fence(error)) => {
                self.check().map_err(ProtectedFencedStoreError::Store)?;
                Err(ProtectedFencedStoreError::Fence(error))
            }
        }
    }

    pub fn finalize(&self) -> Result<(), StoreIoError> {
        if self.engine().live_views() != 0 {
            self.failure
                .record(ProtectedStoreError::Io(StoreIoError::RecoveryRequired));
            return Err(StoreIoError::FinalizationFailed);
        }
        // An immediate empty transaction is a flush barrier after all jobs.
        self.apply(AtomicBatch::default())
            .map_err(|_| StoreIoError::FinalizationFailed)
    }
}

pub(super) fn validate_records(
    view: &ReadView,
    validator: &mut impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        let mut resume = None;
        loop {
            let page = view.scan_after(family, &[], resume.as_deref(), 256, 4 * 1024 * 1024)?;
            for (key, value) in &page.rows {
                validator(key, value)?;
            }
            resume = page.resume;
            if resume.is_none() {
                break;
            }
        }
    }
    Ok(())
}

impl Drop for PhysicalStore {
    fn drop(&mut self) {
        drop(self.engine.take());
        // The root lock outlives actual engine destruction, including its final
        // native flush. Release failure cannot be reported as a clean drain.
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        if self.root_lock.unlock().is_err() {
            self.failure
                .record(ProtectedStoreError::Io(StoreIoError::FinalizationFailed));
        }
        if self.status.close_failed() || !self.status.close_observed() {
            self.failure
                .record(ProtectedStoreError::Io(StoreIoError::FinalizationFailed));
        }
    }
}
