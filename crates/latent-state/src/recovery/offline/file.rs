use super::{OfflineRecoveryError, SnapshotFile};
use crate::recovery::snapshot::SNAPSHOT_FILE_BYTES;
use latent_protected_files::{ProtectedMutableFile, ProtectedRoot};
use std::{
    fs::File,
    io::{self, Read, Seek, Write},
};

pub(super) struct ProtectedSnapshotFile {
    root: ProtectedRoot,
    fence: ProtectedMutableFile,
    file: File,
}

impl ProtectedSnapshotFile {
    pub fn validate(path: &SnapshotFile) -> Result<u64, OfflineRecoveryError> {
        if !path.root.is_absolute()
            || path.root.as_os_str().len() > 4096
            || path.file_name.is_empty()
            || path.file_name.len() > 255
            || path.file_name == "."
            || path.file_name == ".."
            || !path
                .file_name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
        {
            return Err(OfflineRecoveryError::InvalidConfiguration);
        }
        u64::try_from(
            path.root
                .capacity()
                .checked_add(path.file_name.capacity())
                .ok_or(OfflineRecoveryError::InvalidConfiguration)?,
        )
        .map_err(|_| OfflineRecoveryError::InvalidConfiguration)
    }

    pub fn open(
        path: &SnapshotFile,
        source_root: (u64, u64),
        create: bool,
    ) -> Result<Self, OfflineRecoveryError> {
        let root =
            ProtectedRoot::open(&path.root).map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        if root.identity() == source_root
            || root
                .filesystem_type()
                .map_err(|_| OfflineRecoveryError::UnsafeDestination)?
                != 0xef53
        {
            return Err(OfflineRecoveryError::UnsafeDestination);
        }
        let (file, fence) = if create {
            root.create_mutable_file(&path.file_name, SNAPSHOT_FILE_BYTES)
        } else {
            root.open_mutable_file(&path.file_name, SNAPSHOT_FILE_BYTES, false)
        }
        .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        file.try_lock()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        Ok(Self { root, fence, file })
    }

    pub fn identity(&self) -> (u64, u64) {
        self.root.identity()
    }
    pub fn rewind(&mut self) -> Result<(), OfflineRecoveryError> {
        self.check()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        self.file
            .rewind()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)
    }
    pub fn sync(&self) -> Result<(), OfflineRecoveryError> {
        self.file
            .sync_all()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        self.check()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)
    }
    pub(super) fn check(&self) -> io::Result<()> {
        self.root.check_mutable_file(&self.fence).map_err(|_| {
            io::Error::new(io::ErrorKind::PermissionDenied, "protected snapshot fence")
        })
    }
}

impl Read for ProtectedSnapshotFile {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.check()?;
        let count = self.file.read(output)?;
        self.check()?;
        Ok(count)
    }
}
impl Write for ProtectedSnapshotFile {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        self.check()?;
        let count = self.file.write(input)?;
        self.check()?;
        Ok(count)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.file.flush()?;
        self.check()
    }
}
