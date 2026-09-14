//! Durable immutable data under one explicitly configured, privately owned root.
//! These synchronous primitives belong on a bounded shared blocking owner.
//! Public references are data; capability adapters supply current tenant authority.
pub(crate) mod fs;
mod model;
mod read;
mod reclaim;
mod recovery;
mod write;

use latent_core::TenantId;
pub use model::{LocalBlobError, LocalBlobLimits, LocalBlobSnapshot};
use model::{ReferenceRecord, Result};
pub use read::LocalBlobReader;
pub use reclaim::LocalBlobReclamation;
use std::{
    collections::BTreeMap,
    fs::File,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex, MutexGuard,
    },
};
pub use write::LocalBlobWriter;

const OWNER_BYTES: usize = 65536;
const OBJECT_BYTES: usize = 2048;
const STAGE_BYTES: usize = 4096;
const HANDLE_BYTES: usize = 2048;
const RECORD_BYTES: usize = 4096;
const DISK_ROOT_BYTES: u64 = RECORD_BYTES as u64;
const DISK_ENTRY_BYTES: u64 = 2 * RECORD_BYTES as u64 + 64;

pub struct LocalBlobStore {
    inner: Arc<Inner>,
}
struct Inner {
    root: Arc<fs::Directory>,
    objects: Arc<fs::Directory>,
    staging: Arc<fs::Directory>,
    namespace: String,
    limits: LocalBlobLimits,
    state: Mutex<State>,
    handles: AtomicUsize,
    work: AtomicUsize,
    publishing: AtomicBool,
    pending_objects: AtomicUsize,
    poisoned: AtomicBool,
    closed: AtomicBool,
    _lock: File,
}
#[derive(Default)]
struct State {
    objects: BTreeMap<String, Arc<Object>>,
    stages: BTreeMap<u64, Stage>,
    next: u64,
    resident: u64,
    reserved: u64,
    referenced: usize,
}
struct Object {
    record: Option<ReferenceRecord>,
    bytes: u64,
    pins: AtomicUsize,
    referenced: AtomicBool,
    identity: Option<fs::Identity>,
}
struct Stage {
    maximum: u64,
    active: Arc<AtomicBool>,
}
struct Work {
    inner: Arc<Inner>,
}
impl Drop for Work {
    fn drop(&mut self) {
        self.inner.work.fetch_sub(1, Ordering::AcqRel);
    }
}
struct Publication {
    inner: Arc<Inner>,
}
impl Drop for Publication {
    fn drop(&mut self) {
        self.inner.publishing.store(false, Ordering::Release);
    }
}
struct Handle {
    inner: Arc<Inner>,
}
impl Drop for Handle {
    fn drop(&mut self) {
        self.inner.handles.fetch_sub(1, Ordering::AcqRel);
    }
}

impl LocalBlobStore {
    /// Opens/reconciles a bounded inventory synchronously. Unknown entries and
    /// unsafe files are preserved and reject opening. No guest chooses this path.
    pub fn open(root: &Path, namespace: &str, limits: LocalBlobLimits) -> Result<Arc<Self>> {
        limits.validate()?;
        model::text(namespace)?;
        recovery::open(root, namespace, limits)
    }
    #[must_use]
    pub fn limits(&self) -> LocalBlobLimits {
        self.inner.limits
    }
    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.inner.namespace
    }
    pub(crate) fn configuration_digest(&self) -> Result<String> {
        use sha2::{Digest, Sha256};
        self.inner.check()?;
        self.inner.root.validate()?;
        let identity = fs::Identity::of(&self.inner.root.file)?;
        let mut hash = Sha256::new();
        hash.update(b"LSF local blob configuration v1\0");
        hash.update(identity.device.to_le_bytes());
        hash.update(identity.inode.to_le_bytes());
        hash.update((self.namespace().len() as u64).to_le_bytes());
        hash.update(self.namespace().as_bytes());
        hash.update(record(&self.limits())?);
        Ok(format!("sha256:{:x}", hash.finalize()))
    }
    pub fn snapshot(&self) -> Result<LocalBlobSnapshot> {
        let state = self.inner.state()?;
        Ok(LocalBlobSnapshot {
            objects: state.objects.len(),
            referenced_objects: state.referenced,
            resident_disk_bytes: state.resident,
            accounted_disk_bytes: Inner::disk(&state, 0, 0)?,
            stages: state.stages.len(),
            reserved_stage_bytes: state.reserved,
            handles: self.inner.handles.load(Ordering::Acquire),
            active_work: self.inner.work.load(Ordering::Acquire),
            metadata_bytes: self.inner.metadata(&state)?,
            poisoned: self.inner.poisoned.load(Ordering::Acquire),
            closed: self.inner.closed.load(Ordering::Acquire),
        })
    }
    /// Stops later operations; actual workers/handles must retire before the
    /// embedding reports a clean shutdown. Persistent data survives owner Drop.
    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::Release);
    }
}
impl Inner {
    fn check(&self) -> Result<()> {
        if self.closed.load(Ordering::Acquire) {
            return Err(LocalBlobError::Closed);
        }
        if self.poisoned.load(Ordering::Acquire) {
            return Err(LocalBlobError::Uncertain);
        }
        Ok(())
    }
    fn state(&self) -> Result<MutexGuard<'_, State>> {
        self.state.try_lock().map_err(|_| LocalBlobError::Busy)
    }
    // Critical sections contain bounded bookkeeping only, never filesystem I/O
    // or external callbacks. Finish an accepted mutation even if a snapshot or
    // another finite admission briefly owns the state mutex.
    fn committed_state(&self) -> Result<MutexGuard<'_, State>> {
        self.state.lock().map_err(|_| self.uncertain())
    }
    fn work(self: &Arc<Self>) -> Result<Work> {
        self.check()?;
        increment(&self.work, self.limits.maximum_work)?;
        let work = Work {
            inner: self.clone(),
        };
        self.check()?;
        self.root.validate()?;
        Ok(work)
    }
    fn publication(self: &Arc<Self>) -> Result<Publication> {
        self.check()?;
        self.publishing
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| LocalBlobError::Busy)?;
        Ok(Publication {
            inner: self.clone(),
        })
    }
    fn handle(self: &Arc<Self>, state: &State) -> Result<Handle> {
        self.room(state, HANDLE_BYTES)?;
        increment(&self.handles, self.limits.maximum_handles)?;
        Ok(Handle {
            inner: self.clone(),
        })
    }
    // Upper bounds every regular-file byte, including incomplete sidecars and
    // release markers. Filesystem block/inode overhead is separately bounded by
    // finite inventory and belongs to the backing filesystem's physical quota.
    fn disk(state: &State, entries: usize, payload: u64) -> Result<u64> {
        state
            .objects
            .len()
            .checked_add(state.stages.len())
            .and_then(|n| n.checked_add(entries))
            .and_then(|n| u64::try_from(n).ok())
            .and_then(|n| n.checked_mul(DISK_ENTRY_BYTES))
            .and_then(|n| n.checked_add(DISK_ROOT_BYTES))
            .and_then(|n| n.checked_add(state.resident))
            .and_then(|n| n.checked_add(state.reserved))
            .and_then(|n| n.checked_add(payload))
            .ok_or(LocalBlobError::Capacity)
    }
    fn disk_room(&self, state: &State, entries: usize, payload: u64) -> Result<()> {
        if Self::disk(state, entries, payload)? > self.limits.maximum_disk_bytes {
            return Err(LocalBlobError::Capacity);
        }
        Ok(())
    }
    fn metadata(&self, state: &State) -> Result<usize> {
        state
            .objects
            .len()
            .checked_add(self.pending_objects.load(Ordering::Acquire))
            .and_then(|n| n.checked_mul(OBJECT_BYTES))
            .and_then(|n| n.checked_add(state.stages.len().checked_mul(STAGE_BYTES)?))
            .and_then(|n| {
                n.checked_add(
                    self.handles
                        .load(Ordering::Acquire)
                        .checked_mul(HANDLE_BYTES)?,
                )
            })
            .and_then(|n| n.checked_add(OWNER_BYTES))
            .ok_or(LocalBlobError::Capacity)
    }
    fn room(&self, state: &State, extra: usize) -> Result<()> {
        if self
            .metadata(state)?
            .checked_add(extra)
            .is_none_or(|n| n > self.limits.maximum_metadata_bytes)
        {
            return Err(LocalBlobError::Capacity);
        }
        Ok(())
    }
    fn uncertain(&self) -> LocalBlobError {
        self.poisoned.store(true, Ordering::Release);
        LocalBlobError::Uncertain
    }
}
fn increment(counter: &AtomicUsize, maximum: usize) -> Result<()> {
    let mut before = counter.load(Ordering::Acquire);
    for _ in 0..16 {
        let next = before
            .checked_add(1)
            .filter(|n| *n <= maximum)
            .ok_or(LocalBlobError::Capacity)?;
        match counter.compare_exchange_weak(before, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return Ok(()),
            Err(actual) => before = actual,
        }
    }
    Err(LocalBlobError::Busy)
}
fn tenant(tenant: &TenantId) -> Result<()> {
    model::text(&tenant.0)
}
fn record<T: serde::Serialize>(record: &T) -> Result<Vec<u8>> {
    let value = serde_json::to_vec(record).map_err(|_| LocalBlobError::Invalid)?;
    if value.len() > RECORD_BYTES {
        return Err(LocalBlobError::Capacity);
    }
    Ok(value)
}
fn parse<T: serde::de::DeserializeOwned>(directory: &fs::Directory, name: &str) -> Result<T> {
    serde_json::from_slice(&directory.small(name, RECORD_BYTES)?)
        .map_err(|_| LocalBlobError::Corrupt)
}

#[cfg(test)]
mod tests;
