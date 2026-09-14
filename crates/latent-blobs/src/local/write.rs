use super::model::StageRecord;
use super::{
    fs, model, read, tenant, Arc, AtomicBool, AtomicUsize, File, Handle, Inner, LocalBlobError,
    LocalBlobStore, Object, Ordering, ReferenceRecord, Result, Stage, TenantId, HANDLE_BYTES,
    OBJECT_BYTES, STAGE_BYTES,
};
use crate::BlobReference;
use sha2::{Digest, Sha256};
use std::{io::Read, os::unix::fs::FileExt};

pub struct LocalBlobWriter {
    data: File,
    directory: Arc<fs::Directory>,
    record: StageRecord,
    written: u64,
    failed: bool,
    lease: StageLease,
}
struct StageLease {
    id: u64,
    active: Arc<AtomicBool>,
    handle: Handle,
}
impl Drop for StageLease {
    fn drop(&mut self) {
        self.active.store(false, Ordering::Release);
    }
}
struct PendingObject {
    inner: Arc<Inner>,
    reserved: bool,
}
impl PendingObject {
    fn release(&mut self) {
        if self.reserved {
            self.inner.pending_objects.fetch_sub(1, Ordering::AcqRel);
            self.reserved = false;
        }
    }
}
impl Drop for PendingObject {
    fn drop(&mut self) {
        self.release();
    }
}
impl LocalBlobStore {
    pub fn create(
        &self,
        scope: &TenantId,
        media_type: &str,
        expected_size: Option<u64>,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalBlobWriter> {
        tenant(scope)?;
        model::text(media_type)?;
        let _work = self.inner.work()?;
        checkpoint()?;
        let maximum = expected_size.unwrap_or(self.inner.limits.maximum_object_bytes);
        if maximum > self.inner.limits.maximum_object_bytes {
            return Err(LocalBlobError::Capacity);
        }
        let lease = {
            let mut state = self.inner.state()?;
            if state.stages.len() == self.inner.limits.maximum_stages {
                return Err(LocalBlobError::Capacity);
            }
            let reserved = state
                .reserved
                .checked_add(maximum)
                .filter(|n| *n <= self.inner.limits.maximum_stage_bytes)
                .ok_or(LocalBlobError::Capacity)?;
            self.inner.disk_room(&state, 1, maximum)?;
            self.inner.room(&state, STAGE_BYTES + HANDLE_BYTES)?;
            let handle = self.inner.handle(&state)?;
            let id = state.next.checked_add(1).ok_or(LocalBlobError::Capacity)?;
            let active = Arc::new(AtomicBool::new(true));
            state.stages.insert(
                id,
                Stage {
                    maximum,
                    active: active.clone(),
                },
            );
            state.reserved = reserved;
            state.next = id;
            StageLease { id, active, handle }
        };
        let record = StageRecord {
            version: 1,
            id: lease.id,
            tenant: scope.0.clone(),
            media_type: media_type.into(),
            expected_size,
            maximum_size: maximum,
        };
        let directory = self
            .inner
            .staging
            .child(&format!("{:016x}", lease.id), true)
            .map_err(|_| self.inner.uncertain())?;
        directory.write_new("STAGE.json", &super::record(&record)?)?;
        let data = directory.open_file("data", true, true, maximum)?;
        directory.sync()?;
        checkpoint()?;
        Ok(LocalBlobWriter {
            data,
            directory,
            record,
            written: 0,
            failed: false,
            lease,
        })
    }
}
impl LocalBlobWriter {
    #[must_use]
    pub fn maximum_size(&self) -> u64 {
        self.record.maximum_size
    }
    #[must_use]
    pub fn written(&self) -> u64 {
        self.written
    }
    /// Writes are strictly sequential. Invalid ranges do no I/O; a partial or
    /// cancelled physical write abandons the stage and cannot be replayed.
    pub fn write(
        &mut self,
        offset: u64,
        bytes: &[u8],
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<u64> {
        let inner = &self.lease.handle.inner;
        let _work = inner.work()?;
        checkpoint()?;
        if self.failed {
            return Err(LocalBlobError::Closed);
        }
        if offset != self.written || bytes.len() > inner.limits.maximum_chunk_bytes {
            return Err(LocalBlobError::Invalid);
        }
        let next = offset
            .checked_add(bytes.len() as u64)
            .filter(|n| *n <= self.record.maximum_size)
            .ok_or(LocalBlobError::Capacity)?;
        self.directory
            .file_matches("data", &self.data, self.record.maximum_size)?;
        if fs::Identity::of(&self.data)?.size != self.written {
            self.failed = true;
            return Err(LocalBlobError::Corrupt);
        }
        let result = (|| {
            self.data
                .write_all_at(bytes, offset)
                .map_err(|_| LocalBlobError::Uncertain)?;
            self.directory
                .file_matches("data", &self.data, self.record.maximum_size)?;
            if fs::Identity::of(&self.data)?.size != next {
                return Err(LocalBlobError::Corrupt);
            }
            self.written = next;
            checkpoint()?;
            Ok(bytes.len() as u64)
        })();
        if result.is_err() {
            self.failed = true;
        }
        result
    }
    pub fn seal(self, checkpoint: &dyn Fn() -> Result<()>) -> Result<BlobReference> {
        let inner = Arc::clone(&self.lease.handle.inner);
        let _work = inner.work()?;
        let _publication = inner.publication()?;
        checkpoint()?;
        if self.failed {
            return Err(LocalBlobError::Closed);
        }
        if self.record.expected_size.is_some_and(|n| n != self.written) {
            return Err(LocalBlobError::Invalid);
        }
        self.directory
            .file_matches("data", &self.data, self.written)?;
        self.data.sync_all().map_err(fs::failure)?;
        let (digest, identity) = self.digest(checkpoint)?;
        let reference = ReferenceRecord {
            version: 1,
            namespace: inner.namespace.clone(),
            tenant: self.record.tenant.clone(),
            digest,
            size: self.written,
            media_type: self.record.media_type.clone(),
        };
        let key = reference.key();
        let existing = { inner.state()?.objects.get(&key).cloned() };
        if let Some(existing) = existing {
            if !existing.referenced.load(Ordering::Acquire) {
                return Err(LocalBlobError::Busy);
            }
            let directory = inner.objects.child(&key, false)?;
            let (_, identity) = read::verify(&directory, &reference, checkpoint)?;
            if existing.identity != Some(identity) {
                return Err(LocalBlobError::Corrupt);
            }
            let result = reference.reference();
            drop(self); // Close real FDs before allowing stage reclamation.
            return Ok(result);
        }
        let mut pending = {
            let state = inner.state()?;
            if state.objects.len() == inner.limits.maximum_objects {
                return Err(LocalBlobError::Capacity);
            }
            inner.room(&state, OBJECT_BYTES)?;
            inner.pending_objects.fetch_add(1, Ordering::AcqRel);
            PendingObject {
                inner: inner.clone(),
                reserved: true,
            }
        };
        self.directory
            .write_new("REFERENCE.json", &super::record(&reference)?)?;
        self.directory.sync()?;
        checkpoint()?;
        inner
            .staging
            .rename(&format!("{:016x}", self.lease.id), &inner.objects, &key)
            .map_err(|_| inner.uncertain())?;
        // After rename, finish the accepted durability boundary even if the
        // response waiter has stopped. The physical worker retains all owners.
        inner.objects.sync().map_err(|_| inner.uncertain())?;
        inner.staging.sync().map_err(|_| inner.uncertain())?;
        if fs::Identity::of(&self.data).map_err(|_| inner.uncertain())? != identity {
            return Err(inner.uncertain());
        }
        let result = reference.reference();
        let object = Arc::new(Object {
            bytes: reference.size,
            record: Some(reference),
            pins: AtomicUsize::new(0),
            referenced: AtomicBool::new(true),
            identity: Some(identity),
        });
        {
            let mut state = inner.committed_state()?;
            let reservation = state
                .stages
                .remove(&self.lease.id)
                .ok_or_else(|| inner.uncertain())?;
            state.reserved -= reservation.maximum;
            state.resident += object.bytes;
            state.referenced += 1;
            state.objects.insert(key, object);
            pending.release();
        }
        drop(self); // No uncharged FD survives the publication permit.
        Ok(result)
    }
    fn digest(&self, checkpoint: &dyn Fn() -> Result<()>) -> Result<(String, fs::Identity)> {
        let mut data = self
            .directory
            .open_file("data", false, false, self.written)?;
        let identity = fs::Identity::of(&data)?;
        if identity.size != self.written {
            return Err(LocalBlobError::Corrupt);
        }
        let mut hash = Sha256::new();
        let mut scratch = [0u8; 8192];
        let mut remaining = self.written;
        while remaining != 0 {
            checkpoint()?;
            let count =
                usize::try_from(remaining.min(scratch.len() as u64)).expect("scratch bound");
            data.read_exact(&mut scratch[..count])
                .map_err(fs::failure)?;
            hash.update(&scratch[..count]);
            remaining -= count as u64;
        }
        if data.read(&mut [0]).map_err(fs::failure)? != 0 || fs::Identity::of(&data)? != identity {
            return Err(LocalBlobError::Corrupt);
        }
        self.directory.file_matches("data", &data, self.written)?;
        Ok((format!("sha256:{:x}", hash.finalize()), identity))
    }
}
