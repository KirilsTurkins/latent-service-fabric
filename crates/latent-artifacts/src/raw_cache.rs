//! Bounded, replaceable raw bytes. Cache residency never grants release authority.
//!
//! Opening, reading, publishing and reclaiming perform synchronous filesystem
//! work and belong on a bounded blocking owner. Reservations and pins only use
//! short nonblocking bookkeeping. Drop never performs filesystem work.

mod io;
mod model;
mod ownership;
mod recovery;
mod work;

#[cfg(test)]
mod tests;

pub use model::{
    RawArtifactCacheLimits, RawArtifactCacheSnapshot, RawArtifactEviction, RawArtifactKey,
    RawArtifactReclamation,
};
pub use ownership::{RawArtifactBytes, RawArtifactPin, RawArtifactRead};
pub use work::{RawArtifactReclaim, RawArtifactWrite};

use latent_core::{PlatformError, PlatformErrorCode};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};

type Result<T> = std::result::Result<T, PlatformError>;
const OWNER_METADATA: usize = 8192;
const ENTRY_METADATA: usize = 768;
const HANDLE_METADATA: usize = 256;

/// One shared durable cache owner. Its root must be separate from catalog roots.
pub struct RawArtifactCache {
    root: PathBuf,
    limits: RawArtifactCacheLimits,
    state: Mutex<State>,
    memory: Arc<ownership::Memory>,
    _lock: OwnerLock,
}

#[derive(Default)]
struct State {
    entries: BTreeMap<RawArtifactKey, Entry>,
    pending: BTreeMap<RawArtifactKey, Pending>,
    recency: BTreeSet<(u64, RawArtifactKey)>,
    sequence: u64,
    resident: u64,
    reserved: u64,
    work: usize,
    pins: usize,
    pinned_bytes: u64,
    deletion_pending: u64,
    owner_metadata: usize,
    hits: u64,
    misses: u64,
    evictions: u64,
    corruptions: u64,
    pressure: u64,
}

struct Entry {
    size: u64,
    incarnation: u64,
    recency: u64,
    pins: usize,
    valid: bool,
    deleting: bool,
}

struct Pending {
    maximum: u64,
    incarnation: u64,
    active: bool,
    touched: bool,
}

fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.into(),
        retryable: matches!(
            code,
            PlatformErrorCode::Unavailable | PlatformErrorCode::ResourceExhausted
        ),
        details: Vec::new(),
    }
}
fn invalid(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, reason)
}
fn corrupt(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, reason)
}
fn capacity() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "raw-cache-capacity")
}
fn busy() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "raw-cache-busy")
}

struct OwnerLock(File);
impl Drop for OwnerLock {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

impl RawArtifactCache {
    /// Opens and recovers one bounded owned root. Performs synchronous I/O.
    /// Directory durability currently requires the Unix standalone profile.
    pub fn open(root: impl Into<PathBuf>, limits: RawArtifactCacheLimits) -> Result<Arc<Self>> {
        limits.validate()?;
        recovery::open(root.into(), limits)
    }

    /// Copies one fixed aggregate; neither scans files nor enumerates releases.
    pub fn snapshot(&self) -> Result<RawArtifactCacheSnapshot> {
        let state = self.state()?;
        let memory = self.memory.snapshot()?;
        Ok(RawArtifactCacheSnapshot {
            limits: self.limits,
            entries: state.entries.len(),
            resident_disk_bytes: state.resident,
            reserved_disk_bytes: state.reserved,
            pinned_disk_bytes: state.pinned_bytes,
            metadata_bytes: state.metadata_bytes()?,
            staging_entries: state.pending.len(),
            active_reads: memory.2,
            reserved_read_bytes: memory.0,
            retained_read_bytes: memory.1,
            active_work: state.work,
            pins: state.pins,
            deletion_pending_bytes: state.deletion_pending,
            hits: state.hits,
            misses: state.misses,
            evictions: state.evictions,
            corruptions: state.corruptions,
            pressure_rejections: state.pressure,
        })
    }

    #[must_use]
    pub fn limits(&self) -> RawArtifactCacheLimits {
        self.limits
    }

    fn state(&self) -> Result<MutexGuard<'_, State>> {
        self.state.try_lock().map_err(|failure| match failure {
            std::sync::TryLockError::WouldBlock => busy(),
            std::sync::TryLockError::Poisoned(_) => {
                error(PlatformErrorCode::Internal, "raw-cache-owner-poisoned")
            }
        })
    }

    fn metadata_room(&self, state: &State, extra: usize) -> Result<()> {
        if state
            .metadata_bytes()?
            .checked_add(extra)
            .is_none_or(|bytes| bytes > self.limits.maximum_metadata_bytes)
        {
            return Err(capacity());
        }
        Ok(())
    }
}

impl State {
    fn next(&mut self) -> Result<u64> {
        self.sequence = self.sequence.checked_add(1).ok_or_else(capacity)?;
        Ok(self.sequence)
    }
    fn metadata_bytes(&self) -> Result<usize> {
        self.entries
            .len()
            .checked_add(self.pending.len())
            .and_then(|entries| entries.checked_mul(ENTRY_METADATA))
            .and_then(|bytes| {
                self.pins
                    .checked_mul(HANDLE_METADATA)
                    .and_then(|handles| bytes.checked_add(handles))
            })
            .and_then(|bytes| bytes.checked_add(self.owner_metadata))
            .ok_or_else(capacity)
    }
}

macro_rules! opaque_debug {
    ($($ty:ty),+ $(,)?) => { $(impl std::fmt::Debug for $ty {
        fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.debug_struct(stringify!($ty)).finish_non_exhaustive()
        }
    })+ };
}
opaque_debug!(
    RawArtifactCache,
    RawArtifactPin,
    RawArtifactRead,
    RawArtifactBytes,
    RawArtifactWrite,
    RawArtifactReclaim
);
