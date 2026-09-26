use super::{
    fs, increment, model, tenant, Arc, File, Handle, LocalBlobError, LocalBlobStore, Object,
    Ordering, ReferenceRecord, Result, TenantId,
};
use crate::{BlobRange, BlobReference};
use sha2::{Digest, Sha256};
use std::{io::Read, os::unix::fs::FileExt};

pub struct LocalBlobReader {
    data: File,
    directory: Arc<fs::Directory>,
    reference: BlobReference,
    identity: fs::Identity,
    pin: Pin,
}
struct Pin {
    object: Arc<Object>,
    handle: Handle,
}
impl Drop for Pin {
    fn drop(&mut self) {
        self.object.pins.fetch_sub(1, Ordering::AcqRel);
    }
}
impl LocalBlobStore {
    pub fn open_read(
        &self,
        scope: &TenantId,
        reference: &BlobReference,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalBlobReader> {
        tenant(scope)?;
        let _work = self.inner.work()?;
        checkpoint()?;
        let record = ReferenceRecord::requested(
            &self.inner.namespace,
            scope,
            reference,
            self.inner.limits.maximum_object_bytes,
        )?;
        let key = record.key();
        let pin = {
            let state = self.inner.state()?;
            let object = state
                .objects
                .get(&key)
                .filter(|o| o.referenced.load(Ordering::Acquire))
                .ok_or(LocalBlobError::NotFound)?;
            if object.record.as_ref() != Some(&record) {
                return Err(LocalBlobError::Corrupt);
            }
            let handle = self.inner.handle(&state)?;
            increment(&object.pins, self.inner.limits.maximum_handles)?;
            Pin {
                object: object.clone(),
                handle,
            }
        };
        let directory = self.inner.objects.child(&key, false)?;
        let (data, identity) = verify(&directory, &record, checkpoint)?;
        if pin.object.identity != Some(identity) {
            return Err(LocalBlobError::Corrupt);
        }
        Ok(LocalBlobReader {
            data,
            directory,
            reference: record.reference(),
            identity,
            pin,
        })
    }
}
impl LocalBlobReader {
    #[must_use]
    pub fn reference(&self) -> &BlobReference {
        &self.reference
    }
    /// Exact ranges only, including an empty range at EOF. The caller reserves
    /// its output buffer before dispatching this actual filesystem operation.
    pub fn read(
        &self,
        range: &BlobRange,
        output: &mut [u8],
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<usize> {
        let inner = &self.pin.handle.inner;
        let _work = inner.work()?;
        let length = model::range(
            range,
            self.reference.size_bytes,
            inner.limits.maximum_chunk_bytes,
        )?;
        if output.len() != length {
            return Err(LocalBlobError::Invalid);
        }
        checkpoint()?;
        self.unchanged()?;
        self.data
            .read_exact_at(output, range.offset)
            .map_err(fs::failure)?;
        self.unchanged()?;
        checkpoint()?;
        Ok(length)
    }
    fn unchanged(&self) -> Result<()> {
        self.directory
            .file_matches("data", &self.data, self.identity.size)?;
        if fs::Identity::of(&self.data)? != self.identity {
            return Err(LocalBlobError::Corrupt);
        }
        Ok(())
    }
}
pub(super) fn verify(
    directory: &fs::Directory,
    reference: &ReferenceRecord,
    checkpoint: &dyn Fn() -> Result<()>,
) -> Result<(File, fs::Identity)> {
    let mut data = directory.open_file("data", false, false, reference.size)?;
    let before = fs::Identity::of(&data)?;
    if before.size != reference.size {
        return Err(LocalBlobError::Corrupt);
    }
    let mut hash = Sha256::new();
    let mut scratch = [0u8; 8192];
    let mut remaining = reference.size;
    while remaining != 0 {
        checkpoint()?;
        let count = usize::try_from(remaining.min(scratch.len() as u64)).expect("scratch bound");
        data.read_exact(&mut scratch[..count])
            .map_err(fs::failure)?;
        hash.update(&scratch[..count]);
        remaining -= count as u64;
    }
    checkpoint()?;
    if data.read(&mut [0]).map_err(fs::failure)? != 0
        || fs::Identity::of(&data)? != before
        || reference.digest != format!("sha256:{:x}", hash.finalize())
    {
        return Err(LocalBlobError::Corrupt);
    }
    directory.file_matches("data", &data, reference.size)?;
    Ok((data, before))
}
