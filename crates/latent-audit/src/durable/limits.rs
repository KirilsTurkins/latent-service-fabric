use super::{invalid, Result};
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AuditLimits {
    pub maximum_records: usize,
    pub maximum_record_bytes: usize,
    pub maximum_disk_bytes: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_queued_operations: usize,
    pub maximum_queued_bytes: usize,
    pub maximum_query_events: usize,
    pub maximum_page_bytes: usize,
    pub maximum_query_owners: usize,
    pub maximum_total_page_bytes: usize,
    pub maximum_scan_entries: usize,
}
impl Default for AuditLimits {
    fn default() -> Self {
        Self {
            maximum_records: 4096,
            maximum_record_bytes: 16384,
            maximum_disk_bytes: 64 * 1024 * 1024,
            maximum_metadata_bytes: 8 * 1024 * 1024,
            maximum_queued_operations: 64,
            maximum_queued_bytes: 256 * 1024,
            maximum_query_events: 128,
            maximum_page_bytes: 256 * 1024,
            maximum_query_owners: 4,
            maximum_total_page_bytes: 1024 * 1024,
            maximum_scan_entries: 1024,
        }
    }
}
impl AuditLimits {
    pub fn validate(self) -> Result<Self> {
        let values = [
            (self.maximum_records, 16384),
            (self.maximum_record_bytes, 16384),
            (self.maximum_disk_bytes, 256 * 1024 * 1024),
            (self.maximum_metadata_bytes, 32 * 1024 * 1024),
            (self.maximum_queued_operations, 256),
            (self.maximum_queued_bytes, 1024 * 1024),
            (self.maximum_query_events, 256),
            (self.maximum_page_bytes, 1024 * 1024),
            (self.maximum_query_owners, 16),
            (self.maximum_total_page_bytes, 4 * 1024 * 1024),
            (self.maximum_scan_entries, 4096),
        ];
        if values.iter().any(|(v, max)| *v == 0 || v > max)
            || self.maximum_records < 2
            || self.maximum_record_bytes < 4096
            || self.maximum_disk_bytes < 2 * self.maximum_record_bytes
            || self.maximum_queued_bytes < 16384
            || self.maximum_metadata_bytes < 128 * 1024 + self.maximum_records * 1536
            || self.maximum_page_bytes < 32768
            || self.maximum_total_page_bytes < 4 * 32768
        {
            return Err(invalid());
        }
        Ok(self)
    }
}
