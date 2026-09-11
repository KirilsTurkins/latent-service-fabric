//! Fixed per-repository diagnostic counters for fresh verification work.

use std::sync::atomic::{AtomicU64, Ordering};

/// Cumulative operational observations, sampled independently. Attempts include
/// failures; hashed bytes include prefixes before later failures, excluding a
/// rejected over-limit sentinel. Counters saturate and never wrap. Publication
/// caller-buffer hashing is outside these disk-read verification counters.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ArtifactVerificationSnapshot {
    pub full_fetch_attempts: u64,
    pub metadata_fetch_attempts: u64,
    pub component_verification_attempts: u64,
    pub component_bytes_hashed: u64,
    pub metadata_fingerprint_attempts: u64,
}

#[derive(Default)]
pub(crate) struct VerificationStatistics {
    pub(crate) full_fetch_attempts: AtomicU64,
    pub(crate) metadata_fetch_attempts: AtomicU64,
    pub(crate) component_verification_attempts: AtomicU64,
    pub(crate) component_bytes_hashed: AtomicU64,
    pub(crate) metadata_fingerprint_attempts: AtomicU64,
}

impl VerificationStatistics {
    pub(crate) fn snapshot(&self) -> ArtifactVerificationSnapshot {
        ArtifactVerificationSnapshot {
            full_fetch_attempts: self.full_fetch_attempts.load(Ordering::Relaxed),
            metadata_fetch_attempts: self.metadata_fetch_attempts.load(Ordering::Relaxed),
            component_verification_attempts: self
                .component_verification_attempts
                .load(Ordering::Relaxed),
            component_bytes_hashed: self.component_bytes_hashed.load(Ordering::Relaxed),
            metadata_fingerprint_attempts: self
                .metadata_fingerprint_attempts
                .load(Ordering::Relaxed),
        }
    }
}

pub(crate) fn add(counter: &AtomicU64, amount: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(amount))
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counters_saturate_without_wrapping() {
        let counter = AtomicU64::new(u64::MAX - 1);
        add(&counter, 3);
        add(&counter, 1);
        assert_eq!(counter.load(Ordering::Relaxed), u64::MAX);
    }
}
