use redb::{backends::FileBackend, BackendError, StorageBackend};
use std::fs::File;
use std::io;
use std::ops::Bound;
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::{Arc, Mutex};

use super::StoreError;
mod compaction;
use compaction::{IoKind, IoState};

/// Engine close observation only; worker retirement proves actual destruction.
#[derive(Clone, Debug)]
pub struct StoreFileStatus {
    close: Arc<AtomicU8>,
    io: Arc<Mutex<IoState>>,
    #[cfg(test)]
    fail_sync: Arc<std::sync::atomic::AtomicBool>,
    #[cfg(test)]
    delay_sync_millis: Arc<std::sync::atomic::AtomicU64>,
}

impl StoreFileStatus {
    #[must_use]
    pub fn close_failed(&self) -> bool {
        self.close.load(Ordering::Acquire) == 2
    }

    #[must_use]
    pub fn close_observed(&self) -> bool {
        self.close.load(Ordering::Acquire) != 0
    }

    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(crate) fn fail_next_sync(&self) {
        self.fail_sync.store(true, Ordering::Release);
    }

    #[cfg(test)]
    pub(crate) fn fail_next_compaction_sync(&self) {
        self.fail_sync.store(true, Ordering::Release);
    }

    #[cfg(test)]
    pub(crate) fn delay_next_compaction_sync(&self, millis: u64) {
        assert!(millis <= 2000);
        self.delay_sync_millis.store(millis, Ordering::Release);
    }
}

#[derive(Debug)]
pub(super) struct BoundedFile {
    inner: FileBackend,
    maximum: u64,
    status: StoreFileStatus,
}

impl BoundedFile {
    pub fn new(file: File, maximum: u64) -> Result<(Self, StoreFileStatus), StoreError> {
        if maximum == 0 || maximum > 1024 * 1024 * 1024 {
            return Err(StoreError::Invalid);
        }
        let file_bytes = file.metadata().map_err(|_| StoreError::Unavailable)?.len();
        if file_bytes > maximum {
            return Err(StoreError::Capacity);
        }
        let inner = FileBackend::new(file).map_err(|_| StoreError::Unavailable)?;
        let status = StoreFileStatus {
            close: Arc::new(AtomicU8::new(0)),
            io: Arc::new(Mutex::new(IoState {
                file_bytes,
                maximum_file_bytes: maximum,
                active: None,
                last: None,
            })),
            #[cfg(test)]
            fail_sync: Arc::default(),
            #[cfg(test)]
            delay_sync_millis: Arc::default(),
        };
        Ok((
            Self {
                inner,
                maximum,
                status: status.clone(),
            },
            status,
        ))
    }

    fn check(&self, end: Option<u64>) -> io::Result<()> {
        if end.is_none_or(|end| end > self.maximum) {
            Err(io::Error::new(
                io::ErrorKind::StorageFull,
                "transaction store physical byte limit",
            ))
        } else {
            Ok(())
        }
    }
}

impl StorageBackend for BoundedFile {
    fn len(&self) -> io::Result<u64> {
        self.status.charge(IoKind::Other, 0, None)?;
        let result = self.inner.len();
        self.status.observed(
            result.as_ref().ok().map(|length| (*length, true)),
            result.is_ok(),
        )?;
        result
    }

    fn read(&self, offset: u64, out: &mut [u8]) -> io::Result<()> {
        self.check(
            u64::try_from(out.len())
                .ok()
                .and_then(|len| offset.checked_add(len)),
        )?;
        self.status.charge(IoKind::Read, out.len(), None)?;
        let result = self.inner.read(offset, out);
        self.status.observed(None, result.is_ok())?;
        result
    }

    fn set_len(&self, len: u64) -> io::Result<()> {
        self.check(Some(len))?;
        self.status.charge(IoKind::Other, 0, Some(len))?;
        let result = self.inner.set_len(len);
        self.status.observed(Some((len, true)), result.is_ok())?;
        result
    }

    fn sync_data(&self) -> io::Result<()> {
        self.status.charge(IoKind::Other, 0, None)?;
        #[cfg(test)]
        {
            let millis = self.status.delay_sync_millis.swap(0, Ordering::AcqRel);
            if millis != 0 {
                std::thread::sleep(std::time::Duration::from_millis(millis));
            }
        }
        #[cfg(test)]
        if self.status.fail_sync.swap(false, Ordering::AcqRel) {
            return Err(io::Error::other("injected store sync failure"));
        }
        let result = self.inner.sync_data();
        self.status.observed(None, result.is_ok())?;
        result
    }

    fn write(&self, offset: u64, data: &[u8]) -> io::Result<()> {
        let end = u64::try_from(data.len())
            .ok()
            .and_then(|len| offset.checked_add(len));
        self.check(end)?;
        self.status.charge(IoKind::Write, data.len(), end)?;
        let result = self.inner.write(offset, data);
        self.status
            .observed(end.map(|end| (end, false)), result.is_ok())?;
        result
    }

    fn close(&self) -> io::Result<()> {
        let result = self.inner.close();
        self.status
            .close
            .store(if result.is_ok() { 1 } else { 2 }, Ordering::Release);
        result
    }

    fn try_lock_range(&self, start: Bound<u64>, end: Bound<u64>) -> Result<bool, BackendError> {
        self.inner.try_lock_range(start, end)
    }
    fn try_lock_shared_range(
        &self,
        start: Bound<u64>,
        end: Bound<u64>,
    ) -> Result<bool, BackendError> {
        self.inner.try_lock_shared_range(start, end)
    }
    fn lock_range(&self, start: Bound<u64>, end: Bound<u64>) -> Result<(), BackendError> {
        self.inner.lock_range(start, end)
    }
    fn lock_shared_range(&self, start: Bound<u64>, end: Bound<u64>) -> Result<(), BackendError> {
        self.inner.lock_shared_range(start, end)
    }
    fn unlock_range(&self, start: Bound<u64>, end: Bound<u64>) -> Result<(), BackendError> {
        self.inner.unlock_range(start, end)
    }
    fn query_lock_range(&self, start: Bound<u64>, end: Bound<u64>) -> Result<bool, BackendError> {
        self.inner.query_lock_range(start, end)
    }
}
