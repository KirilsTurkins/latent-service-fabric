use super::{invalid, Result, BASE_METADATA};

/// Independent logical storage and read-memory ceilings for untrusted receipts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotReceiptCacheLimits {
    pub maximum_entries: usize,
    pub maximum_disk_bytes: u64,
    pub maximum_metadata_bytes: usize,
    pub maximum_receipt_bytes: usize,
    pub maximum_retained_read_bytes: usize,
    pub maximum_read_owners: usize,
    pub maximum_recovery_entries: usize,
}

impl Default for AotReceiptCacheLimits {
    fn default() -> Self {
        Self {
            maximum_entries: 1024,
            maximum_disk_bytes: 16 * 1024 * 1024,
            maximum_metadata_bytes: 2 * 1024 * 1024,
            maximum_receipt_bytes: 8192,
            maximum_retained_read_bytes: 64 * 1024,
            maximum_read_owners: 8,
            maximum_recovery_entries: 2048,
        }
    }
}

impl AotReceiptCacheLimits {
    /// Validates positive bounded settings before filesystem mutation.
    pub fn validate(self) -> Result<Self> {
        let valid = (1..=16_384).contains(&self.maximum_entries)
            && (1..=128 * 1024 * 1024).contains(&self.maximum_disk_bytes)
            && (1..=16 * 1024 * 1024).contains(&self.maximum_metadata_bytes)
            && (1..=8192).contains(&self.maximum_receipt_bytes)
            && (1..=1024 * 1024).contains(&self.maximum_retained_read_bytes)
            && (1..=64).contains(&self.maximum_read_owners)
            && (1..=32_768).contains(&self.maximum_recovery_entries);
        if valid {
            Ok(self)
        } else {
            Err(invalid())
        }
    }
}

/// Fixed-cost logical counters. Hits count returned bytes, never authenticated code.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotReceiptCacheSnapshot {
    pub limits: AotReceiptCacheLimits,
    pub entries: usize,
    pub resident_disk_bytes: u64,
    pub reserved_disk_bytes: u64,
    pub staging_bytes: u64,
    pub deletion_pending_bytes: u64,
    pub metadata_bytes: usize,
    pub active_work: usize,
    pub read_owners: usize,
    pub retained_read_bytes: usize,
    pub lookup_hits: u64,
    pub lookup_misses: u64,
    pub publications: u64,
    pub evictions: u64,
    pub corruptions: u64,
    pub pressure_rejections: u64,
}

impl AotReceiptCacheSnapshot {
    pub(super) fn new(limits: AotReceiptCacheLimits) -> Self {
        Self {
            limits,
            entries: 0,
            resident_disk_bytes: 0,
            reserved_disk_bytes: 0,
            staging_bytes: 0,
            deletion_pending_bytes: 0,
            metadata_bytes: BASE_METADATA,
            active_work: 0,
            read_owners: 0,
            retained_read_bytes: 0,
            lookup_hits: 0,
            lookup_misses: 0,
            publications: 0,
            evictions: 0,
            corruptions: 0,
            pressure_rejections: 0,
        }
    }
}
