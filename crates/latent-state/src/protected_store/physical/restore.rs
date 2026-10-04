//! Private Fresh producer: no current-engine replacement or caller freshness.

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use super::FailureLatch;
use super::PhysicalStore;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use crate::embedded::{EmbeddedStore, FencedStoreError};
use crate::{
    embedded::StoreError,
    protected_store::{ProtectedStoreConfig, ProtectedStoreError},
    store_identity::StoreIdentity,
};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use std::sync::{Arc, Mutex};

impl PhysicalStore {
    /// The admitted SAME Recovery worker owns all native allocation/destruction.
    /// `current` is the installed original role/audit/control/clock fence, not
    /// an optional callback or a descriptive restore-window acknowledgement.
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub(in crate::protected_store) fn initialize_restore_destination(
        config: &ProtectedStoreConfig,
        source: &Self,
        snapshot: &crate::protected_store::snapshot::SnapshotFile,
        identity: StoreIdentity,
        mut current: impl FnMut() -> Result<(), StoreError>,
        accept: impl FnOnce() -> Result<(), StoreError>,
    ) -> Result<Self, ProtectedStoreError> {
        use latent_protected_files::ProtectedRoot;
        current().map_err(ProtectedStoreError::Store)?;
        source.check()?;
        let root =
            ProtectedRoot::open(&config.root).map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        if !source.is_separate_root(&root)?
            || !snapshot
                .is_separate_root(&root)
                .map_err(ProtectedStoreError::Store)?
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        if root
            .filesystem_type()
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?
            != 0xef53
        {
            return Err(ProtectedStoreError::UnsupportedFilesystem);
        }
        root.check_empty()
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        current().map_err(ProtectedStoreError::Store)?;
        let (root_lock, lock_fence) = root
            .create_mutable_file("transaction-owner.lock", 1)
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        root_lock
            .try_lock()
            .map_err(|_| ProtectedStoreError::Store(StoreError::Conflict))?;
        root.check_exact_mutable_files(&[&lock_fence])
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        current().map_err(ProtectedStoreError::Store)?;
        let (file, fence) = root
            .create_mutable_file(&config.file_name, config.maximum_file_bytes)
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        root.check_exact_mutable_files(&[&lock_fence, &fence])
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        current().map_err(ProtectedStoreError::Store)?;
        let (engine, status) =
            EmbeddedStore::open_bounded_file(file, config.engine, config.maximum_file_bytes)
                .map_err(ProtectedStoreError::Store)?;
        let view = engine.snapshot().map_err(ProtectedStoreError::Store)?;
        let batch = identity
            .prepare_initialization(&view)
            .map_err(ProtectedStoreError::Store)?
            .ok_or(ProtectedStoreError::InvalidConfiguration)?;
        drop(view);
        root.check_exact_mutable_files(&[&lock_fence, &fence])
            .map_err(|_| ProtectedStoreError::UnsafeRoot)?;
        source.check()?;
        engine
            .apply_fenced(batch, accept)
            .map_err(|error| match error {
                FencedStoreError::Store(error) | FencedStoreError::Fence(error) => {
                    ProtectedStoreError::Store(error)
                }
            })?;
        // Failure after actual identity commit leaves the private created files
        // in place. No reopen/empty-file fallback can mint a replacement Fresh.
        root.check_exact_mutable_files(&[&lock_fence, &fence])
            .map_err(|_| ProtectedStoreError::CommitUncertain)?;
        source.check()?;
        current().map_err(ProtectedStoreError::Store)?;
        let fresh_root = root.identity();
        Ok(Self {
            engine: Some(engine),
            status,
            failure: Arc::new(FailureLatch::default()),
            dispatcher: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            fresh_identity: Mutex::new(Some(identity)),
            fresh_root: Some(fresh_root),
            root,
            fence,
            root_lock,
            lock_fence,
        })
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    pub(in crate::protected_store) fn initialize_restore_destination(
        _: &ProtectedStoreConfig,
        _: &Self,
        _: &crate::protected_store::snapshot::SnapshotFile,
        _: StoreIdentity,
        _: impl FnMut() -> Result<(), StoreError>,
        _: impl FnOnce() -> Result<(), StoreError>,
    ) -> Result<Self, ProtectedStoreError> {
        Err(ProtectedStoreError::UnsupportedPlatform)
    }
}
