mod mutation;

use super::{
    capacity, corrupt, failure, io, recovery, uncertain, AotReceiptCacheLimits,
    AotReceiptCacheSnapshot, ReadAllowance, ReceiptBytes, Result, BASE_METADATA, ENTRY_METADATA,
};
use latent_core::{ArtifactBlobDigest, PlatformErrorCode};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard, TryLockError};

pub(crate) struct ReceiptCache {
    root: File,
    limits: AotReceiptCacheLimits,
    state: Mutex<State>,
    statistics: Arc<Mutex<AotReceiptCacheSnapshot>>,
    _lock: File,
}

pub(super) type Key = [u8; 32];

#[derive(Clone, Copy)]
pub(super) struct Entry {
    size: u64,
    sequence: u64,
    invalid: bool,
}

#[derive(Clone, Copy)]
struct Pending {
    key: Key,
    size: u64,
    renamed: bool,
}

#[derive(Default)]
pub(super) struct State {
    pub(super) entries: BTreeMap<Key, Entry>,
    recency: BTreeSet<(bool, u64, Key)>,
    sequence: u64,
    pub(super) resident: u64,
    pending: Option<Pending>,
    deletion_pending: u64,
}

impl State {
    pub(super) fn insert(&mut self, key: Key, size: u64) {
        self.remove(&key);
        self.sequence = self.sequence.saturating_add(1);
        let entry = Entry {
            size,
            sequence: self.sequence,
            invalid: false,
        };
        self.entries.insert(key, entry);
        self.recency.insert((true, entry.sequence, key));
        self.resident += size;
    }

    fn remove(&mut self, key: &Key) -> Option<Entry> {
        let entry = self.entries.remove(key)?;
        self.recency.remove(&(!entry.invalid, entry.sequence, *key));
        self.resident -= entry.size;
        if entry.invalid {
            self.deletion_pending -= entry.size;
        }
        Some(entry)
    }

    fn invalidate(&mut self, key: &Key) {
        if let Some(entry) = self.entries.get_mut(key) {
            if !entry.invalid {
                self.recency.remove(&(true, entry.sequence, *key));
                entry.invalid = true;
                self.deletion_pending += entry.size;
                self.recency.insert((false, entry.sequence, *key));
            }
        }
    }
}

impl ReceiptCache {
    pub(crate) fn open(path: &Path, limits: AotReceiptCacheLimits) -> Result<Arc<Self>> {
        recovery::open(path, limits.validate()?)
    }

    pub(super) fn recovered(
        root: File,
        lock: File,
        limits: AotReceiptCacheLimits,
        state: State,
    ) -> Arc<Self> {
        let value = Arc::new(Self {
            root,
            limits,
            state: Mutex::new(state),
            statistics: Arc::new(Mutex::new(AotReceiptCacheSnapshot::new(limits))),
            _lock: lock,
        });
        {
            let work = value.work().expect("new cache mutex");
            work.synchronize();
        }
        value
    }

    pub(crate) fn limits(&self) -> AotReceiptCacheLimits {
        self.limits
    }

    pub(crate) fn snapshot(&self) -> AotReceiptCacheSnapshot {
        *self.statistics()
    }

    #[cfg(test)]
    pub(super) fn with_test_work(&self, callback: impl FnOnce()) {
        let _work = self.work().expect("test work owner");
        callback();
    }

    fn statistics(&self) -> MutexGuard<'_, AotReceiptCacheSnapshot> {
        self.statistics
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn work(&self) -> Result<Work<'_>> {
        let state = self.state.try_lock().map_err(|value| match value {
            TryLockError::WouldBlock => {
                failure(PlatformErrorCode::Unavailable, "native-receipt-cache-busy")
            }
            TryLockError::Poisoned(_) => failure(
                PlatformErrorCode::Internal,
                "native-receipt-cache-owner-poisoned",
            ),
        })?;
        self.statistics().active_work = 1;
        Ok(Work { cache: self, state })
    }

    fn allowance(&self, size: usize) -> Result<ReadAllowance> {
        let mut statistics = self.statistics();
        if statistics.read_owners >= self.limits.maximum_read_owners
            || size
                > self
                    .limits
                    .maximum_retained_read_bytes
                    .saturating_sub(statistics.retained_read_bytes)
        {
            statistics.pressure_rejections = statistics.pressure_rejections.saturating_add(1);
            return Err(capacity());
        }
        statistics.read_owners += 1;
        statistics.retained_read_bytes += size;
        Ok(ReadAllowance {
            statistics: Arc::clone(&self.statistics),
            size,
        })
    }

    pub(crate) fn lookup(&self, digest: &ArtifactBlobDigest) -> Result<Option<ReceiptBytes>> {
        let key = key(digest);
        let mut work = self.work()?;
        if work
            .state
            .pending
            .is_some_and(|pending| pending.renamed && pending.key == key)
        {
            return Err(uncertain());
        }
        let Some(entry) = work.state.entries.get(&key).copied() else {
            work.miss();
            return Ok(None);
        };
        if entry.invalid {
            return Err(corrupt());
        }
        let allowance = self.allowance(usize::try_from(entry.size).map_err(|_| corrupt())?)?;
        let name = name(&key);
        let result = io::size(&self.root, &name).and_then(|size| match size {
            None => Ok(None),
            Some(size) if size == entry.size => {
                io::read(&self.root, &name, allowance.size).map(Some)
            }
            Some(_) => Err(corrupt()),
        });
        match result {
            Ok(Some(bytes)) => {
                work.state.recency.remove(&(true, entry.sequence, key));
                work.state.sequence = work.state.sequence.saturating_add(1);
                let sequence = work.state.sequence;
                work.state
                    .entries
                    .get_mut(&key)
                    .expect("indexed row")
                    .sequence = sequence;
                work.state.recency.insert((true, sequence, key));
                let mut statistics = self.statistics();
                statistics.lookup_hits = statistics.lookup_hits.saturating_add(1);
                Ok(Some(ReceiptBytes {
                    bytes,
                    _allowance: allowance,
                }))
            }
            Ok(None) => {
                work.state.invalidate(&key);
                work.miss();
                Ok(None)
            }
            Err(error) => {
                work.state.invalidate(&key);
                let mut statistics = self.statistics();
                statistics.corruptions = statistics.corruptions.saturating_add(1);
                Err(error)
            }
        }
    }
}

struct Work<'a> {
    cache: &'a ReceiptCache,
    state: MutexGuard<'a, State>,
}

impl Work<'_> {
    fn synchronize(&self) {
        let mut statistics = self.cache.statistics();
        statistics.entries = self.state.entries.len();
        statistics.resident_disk_bytes = self.state.resident;
        statistics.reserved_disk_bytes = self.state.pending.map_or(0, |pending| pending.size);
        statistics.staging_bytes = self
            .state
            .pending
            .filter(|pending| !pending.renamed)
            .map_or(0, |pending| pending.size);
        statistics.deletion_pending_bytes = self.state.deletion_pending;
        let pending_entry = usize::from(
            self.state
                .pending
                .is_some_and(|pending| !self.state.entries.contains_key(&pending.key)),
        );
        statistics.metadata_bytes =
            BASE_METADATA + (self.state.entries.len() + pending_entry) * ENTRY_METADATA;
    }

    fn miss(&self) {
        let mut statistics = self.cache.statistics();
        statistics.lookup_misses = statistics.lookup_misses.saturating_add(1);
    }
}

impl Drop for Work<'_> {
    fn drop(&mut self) {
        self.synchronize();
        self.cache.statistics().active_work = 0;
    }
}

pub(super) fn key(digest: &ArtifactBlobDigest) -> Key {
    let text = &digest.as_str().as_bytes()[7..];
    let mut result = [0; 32];
    for (output, input) in result.iter_mut().zip(text.chunks_exact(2)) {
        let digit = |value| {
            if value <= b'9' {
                value - b'0'
            } else {
                value - b'a' + 10
            }
        };
        *output = digit(input[0]) * 16 + digit(input[1]);
    }
    result
}

pub(super) fn name(key: &Key) -> String {
    use std::fmt::Write;
    let mut output = String::with_capacity(71);
    output.push_str("r-");
    for byte in key {
        write!(&mut output, "{byte:02x}").expect("writing to string");
    }
    output.push_str(".json");
    output
}
