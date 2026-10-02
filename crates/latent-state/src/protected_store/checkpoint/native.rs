use latent_core::native_capacity::NativeReservation;
use std::sync::Arc;

use super::{CheckpointInspection, ProtectedCheckpointConfig, StoreInitializationWitness};
use crate::embedded::{ReadView, StoreError};
use crate::protected_store::physical::{FailureLatch, PhysicalStore};
use crate::store_identity::{ExternalCheckpoint, StoreIdentity};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use latent_protected_files::{ProtectedMutableFile, ProtectedRoot};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use std::os::unix::fs::{FileExt, MetadataExt};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
const FILE_NAME: &str = "transaction-checkpoint.v1";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
const LOCK_NAME: &str = "transaction-checkpoint-owner.lock";

pub(super) struct CheckpointFile {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    root: ProtectedRoot,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fence: ProtectedMutableFile,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    lock_fence: ProtectedMutableFile,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    file: Option<std::fs::File>,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    root_lock: Option<std::fs::File>,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    current: std::sync::Mutex<Option<ExternalCheckpoint>>,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    created_here: bool,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    identity: StoreIdentity,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    failure: Arc<FailureLatch>,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    original: Arc<NativeReservation>,
}

impl CheckpointFile {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn open(
        store: &PhysicalStore,
        config: ProtectedCheckpointConfig,
        identity: StoreIdentity,
        fresh: Option<StoreInitializationWitness>,
        dispatch: Option<(u64, u64)>,
        failure: Arc<FailureLatch>,
        original: Arc<NativeReservation>,
    ) -> Result<Self, StoreError> {
        original
            .with_live(|| ())
            .map_err(|_| StoreError::Conflict)?;
        let business_root = store.root_identity().map_err(|_| StoreError::Unavailable)?;
        let root = ProtectedRoot::open(&config.root).map_err(|_| StoreError::Unavailable)?;
        if root.identity() == business_root
            || !store
                .is_separate_root(&root)
                .map_err(|_| StoreError::Unavailable)?
            || root
                .filesystem_type()
                .map_err(|_| StoreError::Unavailable)?
                != 0xef53
        {
            return Err(StoreError::Invalid);
        }
        let (root_lock, lock_fence) = root
            .open_mutable_file(LOCK_NAME, 1, true)
            .map_err(|_| StoreError::Unavailable)?;
        root_lock.try_lock().map_err(|_| StoreError::Conflict)?;
        let maximum = u64::try_from(ExternalCheckpoint::MAXIMUM_ENCODED_BYTES)
            .expect("bounded checkpoint length");
        let (file, fence, created_here) = if fresh.is_some() {
            match root.create_mutable_file(FILE_NAME, maximum) {
                Ok((file, fence)) => (file, fence, true),
                // An existing entry, including one created by interrupted
                // initialization, is never assumed fresh or overwritten.
                Err(_) => {
                    let (file, fence) = root
                        .open_mutable_file(FILE_NAME, maximum, false)
                        .map_err(|_| StoreError::Unavailable)?;
                    (file, fence, false)
                }
            }
        } else {
            let (file, fence) = root
                .open_mutable_file(FILE_NAME, maximum, false)
                .map_err(|_| StoreError::Unavailable)?;
            (file, fence, false)
        };
        let current = if created_here {
            if file.metadata().map_err(|_| StoreError::Unavailable)?.len() != 0 {
                return Err(StoreError::Corrupt);
            }
            None
        } else {
            let current = read_record(&file)?;
            if current.identity() != &identity {
                return Err(StoreError::Corrupt);
            }
            let (epoch, floor) = dispatch.ok_or(StoreError::Conflict)?;
            current.check_store(&identity, epoch, floor)?;
            Some(current)
        };
        root.check_mutable_file(&lock_fence)
            .map_err(|_| StoreError::Unavailable)?;
        root.check_mutable_file(&fence)
            .map_err(|_| StoreError::Unavailable)?;
        Ok(Self {
            root,
            fence,
            lock_fence,
            file: Some(file),
            root_lock: Some(root_lock),
            current: std::sync::Mutex::new(current),
            created_here,
            identity,
            failure,
            original,
        })
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    pub(super) fn open(
        _: &PhysicalStore,
        _: ProtectedCheckpointConfig,
        _: StoreIdentity,
        _: Option<StoreInitializationWitness>,
        _: Option<(u64, u64)>,
        _: Arc<FailureLatch>,
        _: Arc<NativeReservation>,
    ) -> Result<Self, StoreError> {
        Err(StoreError::UnsupportedFormat)
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fn check(&self) -> Result<(), StoreError> {
        self.root
            .check_mutable_file(&self.lock_fence)
            .map_err(|_| StoreError::Unavailable)?;
        self.root
            .check_mutable_file(&self.fence)
            .map_err(|_| StoreError::Unavailable)
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fn exact_current(&self, cached: &Option<ExternalCheckpoint>) -> Result<(), StoreError> {
        self.check()?;
        let file = self.file.as_ref().expect("worker-owned checkpoint file");
        if let Some(expected) = cached {
            if read_record(file)?.encode() != expected.encode() {
                return Err(StoreError::Corrupt);
            }
        } else if !self.created_here
            || file.metadata().map_err(|_| StoreError::Unavailable)?.len() != 0
        {
            return Err(StoreError::Corrupt);
        }
        self.check()
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fn check_identity(&self, view: &ReadView) -> Result<(), StoreError> {
        if StoreIdentity::inspect(view)?.as_ref() == Some(&self.identity) {
            Ok(())
        } else {
            Err(StoreError::Corrupt)
        }
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn inspect(
        &self,
        view: &ReadView,
        dispatch: Option<(u64, u64)>,
    ) -> Result<CheckpointInspection, StoreError> {
        self.original
            .with_live(|| ())
            .map_err(|_| StoreError::Conflict)?;
        self.check_identity(view)?;
        let current = self.current.lock().map_err(|_| StoreError::Unavailable)?;
        self.exact_current(&current)?;
        if let Some(checkpoint) = current.as_ref() {
            let (epoch, floor) = dispatch.ok_or(StoreError::Conflict)?;
            checkpoint.check_store(&self.identity, epoch, floor)?;
        }
        Ok(CheckpointInspection {
            checkpoint: current.clone(),
            dispatch_owner: dispatch,
        })
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    #[allow(clippy::unused_self)]
    pub(super) fn inspect(
        &self,
        _: &ReadView,
        _: Option<(u64, u64)>,
    ) -> Result<CheckpointInspection, StoreError> {
        Err(StoreError::UnsupportedFormat)
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn advance(
        &self,
        view: &ReadView,
        expected: Option<&ExternalCheckpoint>,
        protected_clock_epoch: u64,
        dispatch: Option<(u64, u64)>,
    ) -> Result<ExternalCheckpoint, StoreError> {
        self.advance_inner(view, expected, protected_clock_epoch, dispatch, || {})
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fn advance_inner(
        &self,
        view: &ReadView,
        expected: Option<&ExternalCheckpoint>,
        protected_clock_epoch: u64,
        dispatch: Option<(u64, u64)>,
        after_write: impl FnOnce(),
    ) -> Result<ExternalCheckpoint, StoreError> {
        self.original
            .with_live(|| ())
            .map_err(|_| StoreError::Conflict)?;
        self.check_identity(view)?;
        let mut current = self.current.lock().map_err(|_| StoreError::Unavailable)?;
        self.exact_current(&current)?;
        if current.as_ref() != expected {
            return Err(StoreError::Conflict);
        }
        let (epoch, floor) = dispatch.ok_or(StoreError::Conflict)?;
        let next = if let Some(original) = current.as_ref() {
            original.advance(protected_clock_epoch, epoch, floor)?
        } else {
            if !self.created_here {
                return Err(StoreError::Corrupt);
            }
            ExternalCheckpoint::initial(self.identity.clone(), protected_clock_epoch, epoch, floor)?
        };
        let encoded = next.encode();
        let file = self.file.as_ref().expect("worker-owned checkpoint file");
        // From this point every error may follow a partial write. Never report
        // abort, recreate the file or authorize a later unsafe retry.
        file.write_all_at(&encoded, 0)
            .map_err(|_| StoreError::CommitUncertain)?;
        file.set_len(u64::try_from(encoded.len()).expect("bounded checkpoint length"))
            .map_err(|_| StoreError::CommitUncertain)?;
        after_write();
        file.sync_all().map_err(|_| StoreError::CommitUncertain)?;
        self.check().map_err(|_| StoreError::CommitUncertain)?;
        if read_record(file).map_err(|_| StoreError::CommitUncertain)? != next {
            return Err(StoreError::CommitUncertain);
        }
        *current = Some(next.clone());
        Ok(next)
    }

    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn advance_for_test(
        &self,
        view: &ReadView,
        expected: Option<&ExternalCheckpoint>,
        protected_clock_epoch: u64,
        dispatch: Option<(u64, u64)>,
        after_write: impl FnOnce(),
    ) -> Result<ExternalCheckpoint, StoreError> {
        self.advance_inner(view, expected, protected_clock_epoch, dispatch, after_write)
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    #[allow(clippy::unused_self)]
    pub(super) fn advance(
        &self,
        _: &ReadView,
        _: Option<&ExternalCheckpoint>,
        _: u64,
        _: Option<(u64, u64)>,
    ) -> Result<ExternalCheckpoint, StoreError> {
        Err(StoreError::UnsupportedFormat)
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn read_record(file: &std::fs::File) -> Result<ExternalCheckpoint, StoreError> {
    let before = file.metadata().map_err(|_| StoreError::Unavailable)?;
    let length = usize::try_from(before.len()).map_err(|_| StoreError::Corrupt)?;
    if length == 0 || length > ExternalCheckpoint::MAXIMUM_ENCODED_BYTES {
        return Err(StoreError::Corrupt);
    }
    let mut bytes = [0; ExternalCheckpoint::MAXIMUM_ENCODED_BYTES];
    file.read_exact_at(&mut bytes[..length], 0)
        .map_err(|_| StoreError::Unavailable)?;
    let after = file.metadata().map_err(|_| StoreError::Unavailable)?;
    if before.len() != after.len()
        || before.mtime() != after.mtime()
        || before.mtime_nsec() != after.mtime_nsec()
        || before.ctime() != after.ctime()
        || before.ctime_nsec() != after.ctime_nsec()
    {
        return Err(StoreError::Unavailable);
    }
    ExternalCheckpoint::decode(&bytes[..length])
}

impl Drop for CheckpointFile {
    fn drop(&mut self) {
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            // These native destructors execute through the resource's existing
            // pre-reserved recovery retirement. Global keeper refund and the
            // physical witness follow actual file/lock/root destruction.
            drop(self.file.take());
            if self
                .root_lock
                .as_ref()
                .is_some_and(|lock| lock.unlock().is_err())
            {
                self.failure
                    .record(crate::protected_store::ProtectedStoreError::Io(
                        crate::store_io::StoreIoError::FinalizationFailed,
                    ));
            }
            drop(self.root_lock.take());
        }
    }
}
