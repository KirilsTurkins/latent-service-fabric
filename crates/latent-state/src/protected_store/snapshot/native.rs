use std::io::{self, Read, Seek, SeekFrom, Write};
use std::sync::Arc;
use std::time::Instant;

use latent_core::native_capacity::NativeReservation;

use super::ProtectedSnapshotConfig;
use crate::embedded::{RowKey, StoreError};
use crate::protected_store::physical::PhysicalStore;
use crate::recovery::snapshot::{
    inspect_snapshot, SnapshotError, SnapshotReceipt, SNAPSHOT_FILE_BYTES,
};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use latent_protected_files::{ProtectedMutableFile, ProtectedRoot};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
use std::os::unix::fs::FileExt;

pub(super) struct SnapshotFile {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    file: std::fs::File,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    fence: ProtectedMutableFile,
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    root: ProtectedRoot,
    current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    original: Arc<NativeReservation>,
}

impl SnapshotFile {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn create(
        store: &PhysicalStore,
        config: ProtectedSnapshotConfig,
        original: Arc<NativeReservation>,
        current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<Self, SnapshotError> {
        original
            .with_live(|| ())
            .map_err(|_| SnapshotError::Deadline)?;
        current().map_err(SnapshotError::Review)?;
        let root = ProtectedRoot::open(&config.root).map_err(|_| SnapshotError::Output)?;
        if !store
            .is_separate_root(&root)
            .map_err(|_| SnapshotError::Source(StoreError::Unavailable))?
            || root.filesystem_type().map_err(|_| SnapshotError::Output)? != 0xef53
        {
            return Err(SnapshotError::Review(StoreError::Invalid));
        }
        // No overwrite or reclassification of an interrupted prior export.
        // A partial file remains private and cannot pass complete readback.
        let (file, fence) = root
            .create_mutable_file(&config.file_name, SNAPSHOT_FILE_BYTES)
            .map_err(|_| SnapshotError::Output)?;
        file.try_lock().map_err(|_| SnapshotError::Output)?;
        let result = Self {
            file,
            fence,
            root,
            current,
            original,
        };
        result.check().map_err(|_| SnapshotError::Output)?;
        Ok(result)
    }

    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    pub(super) fn create(
        _: &PhysicalStore,
        _: ProtectedSnapshotConfig,
        _: Arc<NativeReservation>,
        _: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<Self, SnapshotError> {
        Err(SnapshotError::Review(StoreError::UnsupportedFormat))
    }

    pub(super) fn deadline(&self) -> Instant {
        self.original.original_deadline()
    }

    pub(super) fn cursor(&self) -> SnapshotCursor<'_> {
        SnapshotCursor {
            file: self,
            offset: 0,
        }
    }

    fn check(&self) -> io::Result<()> {
        self.original
            .with_live(|| ())
            .map_err(|_| io::Error::other("original snapshot deadline/currentness refused"))?;
        (self.current)().map_err(|_| io::Error::other("current snapshot read/audit refused"))?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        self.root
            .check_mutable_file(&self.fence)
            .map_err(|_| io::Error::other("snapshot file ownership refused"))?;
        Ok(())
    }

    pub(super) fn verify(
        &self,
        expected: SnapshotReceipt,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
    ) -> Result<SnapshotReceipt, SnapshotError> {
        self.check().map_err(|_| SnapshotError::Output)?;
        let actual = inspect_snapshot(&mut self.cursor(), self.deadline(), validate_row)
            .map_err(SnapshotError::Review)?;
        self.check().map_err(|_| SnapshotError::Output)?;
        if actual != expected {
            return Err(SnapshotError::Review(StoreError::Corrupt));
        }
        Ok(actual)
    }
}

pub(super) struct SnapshotCursor<'a> {
    file: &'a SnapshotFile,
    offset: u64,
}

impl Seek for SnapshotCursor<'_> {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        self.file.check()?;
        let offset = match position {
            SeekFrom::Start(offset) if offset <= SNAPSHOT_FILE_BYTES => offset,
            // The closed reader only rewinds the SAME immutable file. Other
            // seeks cannot create sparse output or silently change its scope.
            _ => return Err(io::Error::other("unsupported snapshot seek")),
        };
        self.offset = offset;
        self.file.check()?;
        Ok(offset)
    }
}

impl Read for SnapshotCursor<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        self.file.check()?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            let amount = self.file.file.read_at(bytes, self.offset)?;
            self.offset = self
                .offset
                .checked_add(amount as u64)
                .ok_or_else(|| io::Error::other("snapshot cursor exhausted"))?;
            self.file.check()?;
            Ok(amount)
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            let _ = bytes;
            Err(io::Error::other("unsupported snapshot platform"))
        }
    }
}

impl Write for SnapshotCursor<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.file.check()?;
        let end = self
            .offset
            .checked_add(bytes.len() as u64)
            .filter(|end| *end <= SNAPSHOT_FILE_BYTES)
            .ok_or_else(|| io::Error::other("snapshot stream bound exceeded"))?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            let amount = self.file.file.write_at(bytes, self.offset)?;
            self.offset = self
                .offset
                .checked_add(amount as u64)
                .filter(|offset| *offset <= end)
                .ok_or_else(|| io::Error::other("snapshot cursor exhausted"))?;
            self.file.check()?;
            Ok(amount)
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            let _ = end;
            Err(io::Error::other("unsupported snapshot platform"))
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        self.file.check()?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        self.file.file.sync_all()?;
        self.file.check()
    }
}
