use std::time::Duration;

use latent_state::store_io::StoreIoLimits;

use super::DispatcherError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchOrdering {
    Unordered,
    Ordered,
}

#[derive(Debug, Clone)]
pub struct DispatcherConfig {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub per_tenant_jobs: usize,
    pub retained_bytes: u64,
    pub page_rows: usize,
    pub page_bytes: usize,
    pub scan_pages_per_tick: usize,
    pub poll_interval: Duration,
    pub ordering: DispatchOrdering,
    pub start_paused: bool,
    /// Set by an admitted restore plan, before exposing dispatch readiness.
    /// Generic resume cannot clear this sticky review fence.
    pub start_in_restore_review: bool,
}

impl Default for DispatcherConfig {
    fn default() -> Self {
        Self {
            workers: 2,
            queued_jobs: 4,
            accepted_jobs: 16,
            per_tenant_jobs: 1,
            retained_bytes: 80 * 1024 * 1024,
            page_rows: 16,
            page_bytes: 1024 * 1024,
            scan_pages_per_tick: 4,
            poll_interval: Duration::from_millis(100),
            ordering: DispatchOrdering::Unordered,
            start_paused: false,
            start_in_restore_review: false,
        }
    }
}

impl DispatcherConfig {
    pub(super) const ATTEMPT_BYTES: u64 = 4 * 1024 * 1024;

    pub(super) fn validate(&self) -> Result<(), DispatcherError> {
        if self.ordering != DispatchOrdering::Unordered {
            return Err(DispatcherError::UnsupportedOrdering);
        }
        if !(1..=16).contains(&self.workers)
            || !(1..=64).contains(&self.queued_jobs)
            || !(1..=128).contains(&self.accepted_jobs)
            || !(1..=self.workers).contains(&self.per_tenant_jobs)
            || self.queued_jobs > self.accepted_jobs
            || self.workers > self.accepted_jobs
            || !(Self::ATTEMPT_BYTES + 512 * 1024..=512 * 1024 * 1024)
                .contains(&self.retained_bytes)
            || !(1..=64).contains(&self.page_rows)
            || !(4096..=4 * 1024 * 1024).contains(&self.page_bytes)
            || !(1..=16).contains(&self.scan_pages_per_tick)
            || !(Duration::from_millis(1)..=Duration::new(60, 0)).contains(&self.poll_interval)
        {
            return Err(DispatcherError::InvalidConfiguration);
        }
        Ok(())
    }

    pub(super) fn worker_limits(&self) -> StoreIoLimits {
        StoreIoLimits {
            workers: self.workers,
            queued_jobs: self.queued_jobs,
            accepted_jobs: self.accepted_jobs,
            active_reads: self.workers,
            active_writes: 1,
            retained_bytes: self.retained_bytes,
            job_bytes: Self::ATTEMPT_BYTES + 4096,
            resident_bytes: 128 * 1024,
        }
    }
}
