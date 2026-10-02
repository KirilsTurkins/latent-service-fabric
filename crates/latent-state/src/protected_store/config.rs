use std::path::PathBuf;
use std::time::Duration;

use super::ProtectedStoreError;
use crate::embedded::StoreLimits;
use crate::store_io::{StoreIoLimits, StoreIoRecoveryLimits};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreFilesystemProfile {
    /// Operator-selected Linux local ext4 profile. Descriptor statfs must agree
    /// with its ext-family magic; network, tmpfs and overlay roots fail closed.
    LinuxExt4,
}

#[derive(Clone, Debug)]
pub struct ProtectedStoreConfig {
    pub root: PathBuf,
    pub file_name: String,
    pub filesystem: StoreFilesystemProfile,
    pub maximum_file_bytes: u64,
    pub create_if_missing: bool,
    pub engine: StoreLimits,
    pub io: StoreIoLimits,
}

impl ProtectedStoreConfig {
    #[must_use]
    pub fn bounded_linux(root: PathBuf) -> Self {
        Self {
            root,
            file_name: "transaction-state.redb".into(),
            filesystem: StoreFilesystemProfile::LinuxExt4,
            maximum_file_bytes: 256 * 1024 * 1024,
            create_if_missing: false,
            engine: StoreLimits {
                cache_bytes: 8 * 1024 * 1024,
                maximum_rows: 16_384,
                maximum_logical_bytes: 32 * 1024 * 1024,
                maximum_key_bytes: 4096,
                maximum_value_bytes: 2 * 1024 * 1024,
                maximum_batch_rows: 1024,
                maximum_read_views: 8,
                maximum_view_age: Duration::from_secs(30),
            },
            io: StoreIoLimits {
                recovery: Some(StoreIoRecoveryLimits {
                    workers: 1,
                    queued_jobs: 4,
                    accepted_jobs: 8,
                    retained_bytes: 16 * 1024 * 1024,
                    job_bytes: 8 * 1024 * 1024 + 8 * 1024,
                }),
                workers: 4,
                queued_jobs: 8,
                accepted_jobs: 32,
                active_reads: 2,
                active_writes: 1,
                retained_bytes: 128 * 1024 * 1024,
                job_bytes: 40 * 1024 * 1024,
                resident_bytes: 8 * 1024 * 1024 + 64 * 1024,
            },
        }
    }

    pub(super) fn validate(&self) -> Result<u64, ProtectedStoreError> {
        let invalid = || ProtectedStoreError::InvalidConfiguration;
        let name = &self.file_name;
        if !self.root.is_absolute()
            || self.root.as_os_str().len() > 4096
            || name.is_empty()
            || name.len() > 255
            || name == "."
            || name == ".."
            || name == "transaction-owner.lock"
            || !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
            || self.maximum_file_bytes < 2 * 1024 * 1024
            || self.maximum_file_bytes > 1024 * 1024 * 1024
            || self.io.active_writes != 1
        {
            return Err(invalid());
        }
        self.engine.validate().map_err(|_| invalid())?;
        self.io.validate().map_err(|_| invalid())?;
        let minimum_resident = self
            .engine
            .cache_bytes
            .checked_add(32 * 1024)
            .and_then(|bytes| {
                self.io
                    .queued_jobs
                    .checked_add(self.io.recovery.map_or(0, |r| r.queued_jobs))
                    .and_then(usize::checked_next_power_of_two)
                    .and_then(|slots| slots.checked_mul(32))
                    .and_then(|queued| bytes.checked_add(queued))
            })
            .and_then(|bytes| {
                self.io
                    .accepted_jobs
                    .checked_add(self.io.recovery.map_or(0, |r| r.accepted_jobs))
                    .and_then(usize::checked_next_power_of_two)
                    .and_then(|slots| slots.checked_mul(16))
                    .and_then(|retirements| bytes.checked_add(retirements))
            })
            .and_then(|bytes| {
                self.io
                    .workers
                    .checked_next_power_of_two()
                    .and_then(|workers| workers.checked_mul(256))
                    .and_then(|workers| bytes.checked_add(workers))
            })
            .ok_or_else(invalid)?;
        if self.io.resident_bytes < u64::try_from(minimum_resident).map_err(|_| invalid())? {
            return Err(invalid());
        }
        let paths = self
            .root
            .capacity()
            .checked_add(name.capacity())
            .ok_or_else(invalid)?;
        let bytes = u64::try_from(paths)
            .map_err(|_| invalid())?
            .checked_add(32 * 1024)
            .ok_or_else(invalid)?;
        // Initialization is admitted before any descriptor or engine allocation.
        if bytes
            .checked_add(4096)
            .is_none_or(|job| job > self.io.job_bytes)
            || bytes
                .checked_add(self.io.resident_bytes)
                .and_then(|bytes| bytes.checked_add(4096))
                .is_none_or(|bytes| bytes > self.io.retained_bytes)
        {
            return Err(invalid());
        }
        Ok(bytes)
    }
}
