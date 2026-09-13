use super::{
    busy, capacity, corrupt, Entry, RawArtifactCache, RawArtifactKey, Result, HANDLE_METADATA,
};
use std::sync::{Arc, Mutex};

pub(super) struct Memory {
    limit: u64,
    maximum: usize,
    state: Mutex<MemoryState>,
}
#[derive(Default)]
struct MemoryState {
    reserved: u64,
    retained: u64,
    owners: usize,
}

impl Memory {
    pub(super) fn new(limit: u64, maximum: usize) -> Self {
        Self {
            limit,
            maximum,
            state: Mutex::new(MemoryState::default()),
        }
    }
    fn reserve(self: &Arc<Self>, bytes: u64) -> Result<MemoryPermit> {
        let mut state = self.state.try_lock().map_err(|_| busy())?;
        if state.owners == self.maximum
            || state
                .reserved
                .checked_add(state.retained)
                .and_then(|used| used.checked_add(bytes))
                .is_none_or(|used| used > self.limit)
        {
            return Err(capacity());
        }
        state.reserved += bytes;
        state.owners += 1;
        Ok(MemoryPermit {
            owner: self.clone(),
            bytes,
            retained: false,
        })
    }
    pub(super) fn snapshot(&self) -> Result<(u64, u64, usize)> {
        let state = self.state.try_lock().map_err(|_| busy())?;
        Ok((state.reserved, state.retained, state.owners))
    }
}

struct MemoryPermit {
    owner: Arc<Memory>,
    bytes: u64,
    retained: bool,
}
impl MemoryPermit {
    fn retain(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.reserved -= self.bytes;
        state.retained += self.bytes;
        self.retained = true;
    }
}
impl Drop for MemoryPermit {
    fn drop(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.retained {
            state.retained -= self.bytes;
        } else {
            state.reserved -= self.bytes;
        }
        state.owners -= 1;
    }
}

/// Affine storage pin for one exact cache entry incarnation, not release trust.
pub struct RawArtifactPin {
    pub(super) owner: Arc<RawArtifactCache>,
    pub(super) key: RawArtifactKey,
    pub(super) incarnation: u64,
    pub(super) size: u64,
}
impl RawArtifactPin {
    #[must_use]
    pub fn key(&self) -> &RawArtifactKey {
        &self.key
    }
    #[must_use]
    pub fn size_bytes(&self) -> u64 {
        self.size
    }

    /// Reserves exact read bytes and work before a blocking task is submitted.
    /// Consumes this pin; no filesystem operation occurs here.
    pub fn reserve_read(self, maximum_bytes: u64) -> Result<RawArtifactRead> {
        if self.size > maximum_bytes {
            return Err(capacity());
        }
        let work = WorkPermit::reserve(&self.owner)?;
        let memory = self.owner.memory.reserve(self.size)?;
        self.check()?;
        Ok(RawArtifactRead {
            pin: self,
            _work: work,
            memory: Some(memory),
        })
    }

    pub(super) fn check(&self) -> Result<()> {
        let state = self.owner.state()?;
        let entry = state
            .entries
            .get(&self.key)
            .ok_or_else(|| corrupt("raw-cache-pin-invalid"))?;
        if entry.incarnation != self.incarnation || !entry.valid || entry.deleting {
            return Err(corrupt("raw-cache-pin-invalid"));
        }
        Ok(())
    }
    fn invalidate(&self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(entry) = state.entries.get_mut(&self.key) {
            if entry.incarnation == self.incarnation && entry.valid {
                entry.valid = false;
                state.corruptions = state.corruptions.saturating_add(1);
                state.deletion_pending += self.size;
            }
        }
    }
}
impl Drop for RawArtifactPin {
    fn drop(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(entry) = state.entries.get_mut(&self.key) {
            if entry.incarnation == self.incarnation {
                entry.pins -= 1;
                if entry.pins == 0 {
                    state.pinned_bytes -= self.size;
                }
                state.pins -= 1;
            }
        }
    }
}

/// Reserved synchronous read. Move this value into the actual blocking job.
pub struct RawArtifactRead {
    pin: RawArtifactPin,
    _work: WorkPermit,
    memory: Option<MemoryPermit>,
}
impl RawArtifactRead {
    /// Allocates only under the reserved byte lease and hashes the returned bytes.
    pub fn read_verified(mut self) -> Result<RawArtifactBytes> {
        let len = usize::try_from(self.pin.size).map_err(|_| capacity())?;
        let mut bytes = vec![0; len];
        self.read(&mut bytes)?;
        let mut memory = self.memory.take().expect("read owns memory reservation");
        memory.retain();
        Ok(RawArtifactBytes {
            bytes,
            _memory: memory,
        })
    }

    /// Reads into an exact-size caller-owned buffer without allocating another
    /// payload. The caller accounts that buffer. Discard it on any error.
    pub fn read_into(self, output: &mut [u8]) -> Result<()> {
        self.read(output)
    }

    fn read(&self, output: &mut [u8]) -> Result<()> {
        if output.len() as u64 != self.pin.size {
            return Err(super::invalid("raw-cache-read-size"));
        }
        self.pin.check()?;
        let result = super::io::read_data(
            &self
                .pin
                .owner
                .root
                .join("objects")
                .join(self.pin.key.name()),
            &self.pin.key,
            output,
        );
        if result.is_err() {
            self.pin.invalidate();
        }
        result?;
        self.pin.check()
    }
}

/// Verified owned bytes retaining their memory charge. This object does not
/// retain the root lock, index, file pin or any release/admission capability.
pub struct RawArtifactBytes {
    bytes: Vec<u8>,
    _memory: MemoryPermit,
}
impl RawArtifactBytes {
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }
}

pub(super) struct WorkPermit {
    pub(super) owner: Arc<RawArtifactCache>,
}
impl WorkPermit {
    pub(super) fn reserve(owner: &Arc<RawArtifactCache>) -> Result<Self> {
        let mut state = owner.state()?;
        if state.work == owner.limits.maximum_work {
            state.pressure = state.pressure.saturating_add(1);
            return Err(capacity());
        }
        // Work-handle capacity is prepaid at open, so a metadata-full cache can
        // always admit a reclamation job when an actual work slot is free.
        owner.metadata_room(&state, 0)?;
        state.work += 1;
        Ok(Self {
            owner: owner.clone(),
        })
    }
}
impl Drop for WorkPermit {
    fn drop(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.work -= 1;
    }
}

impl RawArtifactCache {
    /// Acquires a bounded file pin using bookkeeping only; no implicit read or
    /// eviction occurs. Invalid/missing entries are misses until reconciliation.
    pub fn try_pin(self: &Arc<Self>, key: &RawArtifactKey) -> Result<Option<RawArtifactPin>> {
        let mut state = self.state()?;
        if !state
            .entries
            .get(key)
            .is_some_and(|entry| entry.valid && !entry.deleting)
        {
            state.misses = state.misses.saturating_add(1);
            return Ok(None);
        }
        if state.pins == self.limits.maximum_pins {
            state.pressure = state.pressure.saturating_add(1);
            return Err(capacity());
        }
        self.metadata_room(&state, HANDLE_METADATA)?;
        let recency = state.next()?;
        let entry = state.entries.get_mut(key).expect("checked entry");
        let previous = entry.recency;
        entry.recency = recency;
        let first = entry.pins == 0;
        entry.pins += 1;
        let pin = pin(self, key, entry);
        state.recency.remove(&(previous, key.clone()));
        state.recency.insert((recency, key.clone()));
        if first {
            state.pinned_bytes += pin.size;
        }
        state.pins += 1;
        state.hits = state.hits.saturating_add(1);
        Ok(Some(pin))
    }
}

pub(super) fn pin(
    owner: &Arc<RawArtifactCache>,
    key: &RawArtifactKey,
    entry: &Entry,
) -> RawArtifactPin {
    RawArtifactPin {
        owner: owner.clone(),
        key: key.clone(),
        incarnation: entry.incarnation,
        size: entry.size,
    }
}
