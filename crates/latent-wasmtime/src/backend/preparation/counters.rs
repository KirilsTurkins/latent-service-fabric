//! Fixed factory-owned observations of preparation work, including failed attempts.

use std::sync::atomic::{AtomicU64, Ordering};

/// Cumulative preparation activity. Individual counters are sampled separately.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PreparationActivitySnapshot {
    pub repository_acquisitions: u64,
    pub authenticated_hits: u64,
    pub authenticated_misses: u64,
    pub repository_fetches: u64,
    pub component_hashes: u64,
    pub component_bytes_hashed: u64,
    pub metadata_fingerprints: u64,
}

#[derive(Default)]
pub(in crate::backend) struct PreparationCounters {
    pub(super) repository_acquisitions: AtomicU64,
    pub(super) authenticated_hits: AtomicU64,
    pub(super) authenticated_misses: AtomicU64,
    pub(super) repository_fetches: AtomicU64,
    pub(super) component_hashes: AtomicU64,
    pub(super) component_bytes_hashed: AtomicU64,
    pub(super) metadata_fingerprints: AtomicU64,
}

impl PreparationCounters {
    pub(super) fn snapshot(&self) -> PreparationActivitySnapshot {
        PreparationActivitySnapshot {
            repository_acquisitions: self.repository_acquisitions.load(Ordering::Relaxed),
            authenticated_hits: self.authenticated_hits.load(Ordering::Relaxed),
            authenticated_misses: self.authenticated_misses.load(Ordering::Relaxed),
            repository_fetches: self.repository_fetches.load(Ordering::Relaxed),
            component_hashes: self.component_hashes.load(Ordering::Relaxed),
            component_bytes_hashed: self.component_bytes_hashed.load(Ordering::Relaxed),
            metadata_fingerprints: self.metadata_fingerprints.load(Ordering::Relaxed),
        }
    }
}

pub(super) fn add(counter: &AtomicU64, value: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(value))
    });
}
