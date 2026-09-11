use latent_artifacts::CacheEntryDescriptor;
use latent_core::PlatformError;
use latent_scheduler::{CellClass, LocalScheduler, SchedulerSnapshot};

use super::{bounds::Cost, exhausted, invalid, NodeCacheSummary, NodeTopologyEntry};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SchedulerInventorySnapshot {
    pub queue_capacity: u32,
    pub observations: SchedulerSnapshot,
}

/// Each call inspects one fixed class, never per-service or tenant history.
pub trait SchedulerInventorySource: Send + Sync {
    fn snapshot(&self, class: CellClass) -> Result<SchedulerInventorySnapshot, PlatformError>;
}

impl SchedulerInventorySource for LocalScheduler {
    fn snapshot(&self, class: CellClass) -> Result<SchedulerInventorySnapshot, PlatformError> {
        Ok(SchedulerInventorySnapshot {
            queue_capacity: self.queue_capacity(class).unwrap_or(0),
            observations: self.observations(class),
        })
    }
}

/// A node-owned implementation returns constant-time aggregates and optionally
/// selects at most `writer.remaining()` cached descriptors. It must not enumerate
/// a release catalog or build an intermediate unbounded descriptor vector.
pub trait CacheInventorySource: Send + Sync {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError>;
}

pub struct CacheInventoryWriter<'a> {
    pub(super) summary: Option<NodeCacheSummary>,
    pub(super) entries: &'a mut Vec<CacheEntryDescriptor>,
    pub(super) cost: &'a mut Cost,
    pub(super) maximum: usize,
    pub(super) failed: bool,
}

impl CacheInventoryWriter<'_> {
    /// Publish the aggregate once. Preparing costs have separate reservation
    /// ceilings; resident totals cannot exceed their independently named limits.
    pub fn set_summary(&mut self, summary: NodeCacheSummary) -> Result<(), PlatformError> {
        if self.summary.is_some()
            || summary.entries > summary.maximum_entries
            || summary.source_bytes > summary.maximum_source_bytes
            || summary.metadata_bytes > summary.maximum_metadata_bytes
            || summary.compiled_image_bytes > summary.maximum_compiled_image_bytes
            || summary.preparing > summary.maximum_concurrent_preparations
            || u128::from(summary.preparing_source_bytes)
                > u128::from(summary.preparing) * u128::from(summary.maximum_source_bytes)
            || u128::from(summary.preparing_metadata_bytes)
                > u128::from(summary.preparing) * u128::from(summary.maximum_metadata_bytes)
        {
            self.failed = true;
            return Err(invalid("invalid-inventory-cache-summary"));
        }
        self.summary = Some(summary);
        Ok(())
    }

    #[must_use]
    pub fn remaining(&self) -> usize {
        self.maximum - self.entries.len()
    }

    /// False means the sample is full; no descriptor field is visited or cloned.
    /// A failed validation remains visible even if the source ignores the error.
    pub fn push_descriptor(&mut self, entry: &CacheEntryDescriptor) -> Result<bool, PlatformError> {
        if self.failed {
            return Err(exhausted());
        }
        if self.remaining() == 0 {
            return Ok(false);
        }
        if let Err(error) = self.cost.cache_entry(entry) {
            self.failed = true;
            return Err(error);
        }
        self.entries.push(entry.clone());
        Ok(true)
    }
}

/// A bounded topology source visits fixed runtime resources, never all services.
/// Return true only if every known row fits the selection. Unknown observations
/// use `active_count=None`; a configured count alone is not a live measurement.
pub trait NodeTopologySource: Send + Sync {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError>;
}

pub struct NodeTopologyWriter<'a> {
    pub(super) entries: &'a mut Vec<NodeTopologyEntry>,
    pub(super) cost: &'a mut Cost,
    pub(super) maximum: usize,
    pub(super) failed: bool,
    pub(super) truncated: bool,
}

impl NodeTopologyWriter<'_> {
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.maximum - self.entries.len()
    }

    /// Validate before cloning; false means no remaining row allowance.
    pub fn push(&mut self, entry: &NodeTopologyEntry) -> Result<bool, PlatformError> {
        if self.failed {
            return Err(exhausted());
        }
        if self.remaining() == 0 {
            self.truncated = true;
            return Ok(false);
        }
        if let Err(error) = self.cost.topology(entry) {
            self.failed = true;
            return Err(error);
        }
        self.entries.push(entry.clone());
        Ok(true)
    }
}

/// Explicitly configured absence of a prepared cache, useful for embeddings
/// without Wasmtime. An unavailable configured cache must return an error.
#[derive(Debug, Default)]
pub struct EmptyCacheInventorySource;

impl CacheInventorySource for EmptyCacheInventorySource {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError> {
        writer.set_summary(NodeCacheSummary {
            available: true,
            ..NodeCacheSummary::default()
        })
    }
}

/// Supplies no topology rows; it does not claim that unobserved resources are zero.
#[derive(Debug, Default)]
pub struct EmptyNodeTopologySource;

impl NodeTopologySource for EmptyNodeTopologySource {
    fn snapshot(&self, _writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        Ok(false)
    }
}
