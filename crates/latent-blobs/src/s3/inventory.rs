//! Private descriptor-anchored upload receipts. Durable transitions precede
//! network mutations; incomplete replies stay charged across process restart.
mod disk;
use super::{BlobError, Result, S3Config, RECORD_BYTES};
use crate::local::fs::Directory;
use latent_capabilities::broker::{
    blob::BlobReference,
    pools::{ProviderMetadata, ProviderPools},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::File,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex, MutexGuard,
    },
};

#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub struct S3Snapshot {
    pub sealed_objects: usize,
    pub unresolved_uploads: usize,
    pub remote_reserved_bytes: u64,
    pub stages: usize,
    pub reserved_staging_bytes: usize,
    pub handles: usize,
    pub active_uploads: usize,
    pub poisoned: bool,
    pub inventory_reserved_bytes: usize,
}
/// Opaque IDs for an authenticated operator; no remote locator or credentials.
pub struct S3PendingUpload {
    pub id: String,
    pub reserved_bytes: u64,
    pub active: bool,
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(super) enum Phase {
    Ready,
    Creating,
    Uploading,
    Completing,
    Sealed,
    Aborted,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Record {
    pub format: u8,
    pub namespace: String,
    pub tenant: String,
    pub digest: String,
    pub size: u64,
    pub media_type: String,
    pub nonce: String,
    pub parts: Vec<String>,
    pub phase: Phase,
    pub upload_id: Option<String>,
    pub version: Option<String>,
    /// False is conservative after a part write lost its response. Socket
    /// destruction alone cannot turn it true or authorize a quota refund.
    pub quiescent: bool,
}
impl Record {
    pub fn key(&self) -> String {
        key(&self.namespace, &self.tenant, &self.reference())
    }
    pub fn reference(&self) -> BlobReference {
        BlobReference {
            digest: self.digest.clone(),
            size: self.size,
            media_type: self.media_type.clone(),
        }
    }
    pub fn object_key(&self, config: &S3Config) -> String {
        format!("{}{}-{}", config.prefix, self.key(), self.nonce)
    }
    pub fn validate(&self, config: &S3Config) -> Result<()> {
        if self.format != 1
            || self.namespace != config.namespace
            || !super::text(&self.tenant, 128)
            || !super::text(&self.media_type, 128)
            || self.size > config.limits.maximum_object_bytes as u64
            || self.digest.len() != 71
            || !self.digest.starts_with("sha256:")
            || !super::hex(&self.digest[7..], 64)
            || !super::hex(&self.nonce, 32)
            || self.parts.len()
                != usize::try_from(self.size.div_ceil(super::PART_BYTES as u64))
                    .map_err(|_| BlobError::InvalidRange)?
            || self.parts.iter().any(|p| !super::hex(p, 64))
            || self
                .upload_id
                .as_ref()
                .is_some_and(|id| !super::text(id, 1024))
            || self
                .version
                .as_ref()
                .is_some_and(|id| !super::text(id, 1024) || id == "null")
            || (self.phase == Phase::Sealed && (self.version.is_none() || !self.quiescent))
            || (self.phase != Phase::Sealed && self.version.is_some())
            || (self.phase == Phase::Uploading && self.upload_id.is_none())
            || (self.size != 0 && self.phase == Phase::Completing && self.upload_id.is_none())
        {
            return Err(BlobError::ChecksumMismatch);
        }
        Ok(())
    }
}
pub(super) fn key(namespace: &str, tenant: &str, reference: &BlobReference) -> String {
    let mut hash = Sha256::new();
    hash.update(b"LSF S3 immutable reference v1\0");
    for text in [namespace, tenant, &reference.digest, &reference.media_type] {
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    hash.update(reference.size.to_le_bytes());
    format!("{:x}", hash.finalize())
}
pub struct S3Inventory {
    config: S3Config,
    directory: Arc<Directory>,
    state: Mutex<State>,
    poisoned: AtomicBool,
    stages: AtomicUsize,
    staging: AtomicUsize,
    handles: AtomicUsize,
    _lock: File,
    _metadata: Vec<ProviderMetadata>,
}
#[derive(Default)]
struct State {
    records: BTreeMap<String, Entry>,
}
struct Entry {
    record: Record,
    active: Arc<AtomicBool>,
}
pub(super) struct Activity {
    active: Arc<AtomicBool>,
}
impl Drop for Activity {
    fn drop(&mut self) {
        self.active.store(false, Ordering::Release);
    }
}
pub(super) struct Stage {
    inventory: Arc<S3Inventory>,
    pub maximum: usize,
}
impl Drop for Stage {
    fn drop(&mut self) {
        self.inventory
            .staging
            .fetch_sub(self.maximum, Ordering::AcqRel);
        self.inventory.stages.fetch_sub(1, Ordering::AcqRel);
    }
}
pub(super) struct Handle {
    inventory: Arc<S3Inventory>,
}
impl Drop for Handle {
    fn drop(&mut self) {
        self.inventory.handles.fetch_sub(1, Ordering::AcqRel);
    }
}
impl S3Inventory {
    /// Trusted synchronous bootstrap. Runtime filesystem transitions use the
    /// shared bounded blocking owner, never a node execution thread.
    pub fn open(root: &Path, pools: &ProviderPools, config: S3Config) -> Result<Arc<Self>> {
        config.validate()?;
        disk::open(root, pools, config)
    }
    pub fn snapshot(&self) -> Result<S3Snapshot> {
        let state = self.state.try_lock().map_err(|_| BlobError::Unavailable)?;
        Ok(S3Snapshot {
            sealed_objects: state
                .records
                .values()
                .filter(|e| e.record.phase == Phase::Sealed)
                .count(),
            unresolved_uploads: state
                .records
                .values()
                .filter(|e| e.record.phase != Phase::Sealed)
                .count(),
            remote_reserved_bytes: state.records.values().map(|e| e.record.size).sum(),
            stages: self.stages.load(Ordering::Acquire),
            reserved_staging_bytes: self.staging.load(Ordering::Acquire),
            handles: self.handles.load(Ordering::Acquire),
            active_uploads: state
                .records
                .values()
                .filter(|e| e.active.load(Ordering::Acquire))
                .count(),
            poisoned: self.poisoned.load(Ordering::Acquire),
            inventory_reserved_bytes: (2 * self.config.limits.maximum_records + 1) * RECORD_BYTES,
        })
    }
    pub(super) fn config(&self) -> &S3Config {
        &self.config
    }
    pub fn pending(&self) -> Result<Vec<S3PendingUpload>> {
        let state = self.state()?;
        Ok(state
            .records
            .iter()
            .filter(|(_, e)| e.record.phase != Phase::Sealed)
            .map(|(key, e)| S3PendingUpload {
                id: key.clone(),
                reserved_bytes: e.record.size,
                active: e.active.load(Ordering::Acquire),
            })
            .collect())
    }
    fn state(&self) -> Result<MutexGuard<'_, State>> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(BlobError::Uncertain);
        }
        self.state.try_lock().map_err(|_| BlobError::Unavailable)
    }
    pub(super) fn stage(self: &Arc<Self>, expected: Option<u64>) -> Result<Stage> {
        let maximum =
            usize::try_from(expected.unwrap_or(self.config.limits.maximum_object_bytes as u64))
                .map_err(|_| BlobError::InvalidRange)?;
        let limits = self.config.limits;
        if self.poisoned.load(Ordering::Acquire) {
            return Err(BlobError::Uncertain);
        }
        if maximum > limits.maximum_object_bytes {
            return Err(BlobError::BudgetExhausted);
        }
        increment(&self.stages, 1, limits.maximum_stages)?;
        if let Err(error) = increment(&self.staging, maximum, limits.maximum_staging_bytes) {
            self.stages.fetch_sub(1, Ordering::AcqRel);
            return Err(error);
        }
        Ok(Stage {
            inventory: self.clone(),
            maximum,
        })
    }
    pub(super) fn handle(self: &Arc<Self>) -> Result<Handle> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(BlobError::Uncertain);
        }
        increment(&self.handles, 1, self.config.limits.maximum_handles)?;
        Ok(Handle {
            inventory: self.clone(),
        })
    }
    pub(super) fn lookup(&self, tenant: &str, reference: &BlobReference) -> Result<Record> {
        let state = self.state()?;
        let entry = state
            .records
            .get(&key(&self.config.namespace, tenant, reference))
            .ok_or(BlobError::NotFound)?;
        if entry.record.phase != Phase::Sealed {
            return Err(BlobError::Uncertain);
        }
        Ok(entry.record.clone())
    }
    pub(super) fn acquire(&self, key: &str) -> Result<(Record, Activity)> {
        let state = self.state()?;
        let entry = state.records.get(key).ok_or(BlobError::NotFound)?;
        entry
            .active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| BlobError::Unavailable)?;
        Ok((
            entry.record.clone(),
            Activity {
                active: entry.active.clone(),
            },
        ))
    }
    /// Invoked under the finite blocking owner. A pending tuple cannot be
    /// recreated even if its last client disappeared before receiving a receipt.
    pub(super) fn insert(&self, record: Record) -> Result<(Record, Activity)> {
        record.validate(&self.config)?;
        let mut state = self.state()?;
        let key = record.key();
        if state.records.contains_key(&key) {
            return Err(BlobError::Uncertain);
        }
        if state.records.len() >= self.config.limits.maximum_records
            || state.records.values().map(|v| v.record.size).sum::<u64>() + record.size
                > self.config.limits.maximum_remote_bytes
        {
            return Err(BlobError::BudgetExhausted);
        }
        self.persist(&record)?;
        let active = Arc::new(AtomicBool::new(true));
        state.records.insert(
            key,
            Entry {
                record: record.clone(),
                active: active.clone(),
            },
        );
        Ok((record, Activity { active }))
    }
    pub(super) fn update(&self, record: &Record, activity: &Activity) -> Result<()> {
        record.validate(&self.config)?;
        let mut state = self.state()?;
        let entry = state
            .records
            .get_mut(&record.key())
            .ok_or(BlobError::NotFound)?;
        if !Arc::ptr_eq(&entry.active, &activity.active)
            || !entry.active.load(Ordering::Acquire)
            || entry.record.nonce != record.nonce
            || entry.record.parts != record.parts
        {
            return Err(BlobError::PermissionDenied);
        }
        self.persist(record)?;
        entry.record = record.clone();
        Ok(())
    }
    pub(super) fn remove_aborted(&self, record: &Record, activity: &Activity) -> Result<()> {
        if record.phase != Phase::Aborted || !record.quiescent {
            return Err(BlobError::Uncertain);
        }
        self.update(record, activity)?;
        let mut state = self.state()?;
        self.directory
            .unlink(&format!("{}.json", record.key()), false)
            .map_err(|_| self.poison())?;
        self.directory.sync().map_err(|_| self.poison())?;
        state.records.remove(&record.key());
        Ok(())
    }
    fn poison(&self) -> BlobError {
        self.poisoned.store(true, Ordering::Release);
        BlobError::Uncertain
    }
    fn persist(&self, record: &Record) -> Result<()> {
        let bytes = serde_json::to_vec(record).map_err(|_| self.poison())?;
        if bytes.len() > RECORD_BYTES {
            return Err(self.poison());
        }
        let pending = format!("{}.pending", record.key());
        let target = format!("{}.json", record.key());
        self.directory
            .write_new(&pending, &bytes)
            .map_err(|_| self.poison())?;
        self.directory
            .replace(&pending, &target, RECORD_BYTES as u64)
            .map_err(|_| self.poison())?;
        self.directory.sync().map_err(|_| self.poison())
    }
}

fn increment(counter: &AtomicUsize, amount: usize, maximum: usize) -> Result<()> {
    let mut previous = counter.load(Ordering::Acquire);
    for _ in 0..16 {
        let next = previous
            .checked_add(amount)
            .filter(|n| *n <= maximum)
            .ok_or(BlobError::BudgetExhausted)?;
        match counter.compare_exchange_weak(previous, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return Ok(()),
            Err(value) => previous = value,
        }
    }
    Err(BlobError::Unavailable)
}

#[cfg(test)]
mod tests;
