//! Independent admission and response-owner bounds for one shared coordinator.

use crate::{invalid, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoordinatorLimits {
    pub maximum_queued_commands: usize,
    pub maximum_queued_bytes: usize,
    pub maximum_request_bytes: usize,
    pub maximum_query_owners: usize,
    pub maximum_page_bytes: usize,
    pub maximum_total_page_bytes: usize,
}

impl Default for CoordinatorLimits {
    fn default() -> Self {
        Self {
            maximum_queued_commands: 8,
            maximum_queued_bytes: 512 * 1024,
            maximum_request_bytes: 64 * 1024,
            maximum_query_owners: 4,
            maximum_page_bytes: 64 * 1024,
            maximum_total_page_bytes: 1024 * 1024,
        }
    }
}

impl CoordinatorLimits {
    pub fn validate(self) -> Result<Self> {
        let valid = [
            (self.maximum_queued_commands, 64),
            (self.maximum_queued_bytes, 4 * 1024 * 1024),
            (self.maximum_request_bytes, 64 * 1024),
            (self.maximum_query_owners, 16),
            (self.maximum_page_bytes, 64 * 1024),
            (self.maximum_total_page_bytes, 4 * 1024 * 1024),
        ]
        .into_iter()
        .all(|(value, maximum)| value > 0 && value <= maximum);
        if !valid
            || self.maximum_page_bytes < 4096
            || self.maximum_queued_bytes < self.maximum_request_bytes
            || self.maximum_total_page_bytes < self.maximum_page_bytes * 4
        {
            return Err(invalid("rollout-coordinator-limits"));
        }
        Ok(self)
    }
}
