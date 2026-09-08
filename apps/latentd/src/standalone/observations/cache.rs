use std::sync::Arc;

use latent_core::PlatformError;
use latent_node::{CacheInventorySource, CacheInventoryWriter, NodeCacheSummary};
use latent_wasmtime::{PreparedCacheSnapshot, WasmtimeBackend};

pub(in crate::standalone) struct CacheSource {
    backend: Arc<WasmtimeBackend>,
}

impl CacheSource {
    pub(in crate::standalone) fn new(backend: Arc<WasmtimeBackend>) -> Self {
        Self { backend }
    }
}

impl CacheInventorySource for CacheSource {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError> {
        // One bounded aggregate read; no descriptors, keys, or release payloads
        // are enumerated or cloned even when the catalog is large.
        writer.set_summary(summary(&self.backend.cache_snapshot()))
    }
}

fn count(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

pub(super) fn summary(value: &PreparedCacheSnapshot) -> NodeCacheSummary {
    NodeCacheSummary {
        available: true,
        entries: count(value.entries),
        maximum_entries: count(value.maximum_entries),
        source_bytes: count(value.source_bytes),
        maximum_source_bytes: count(value.maximum_source_bytes),
        metadata_bytes: count(value.metadata_bytes),
        maximum_metadata_bytes: count(value.maximum_metadata_bytes),
        compiled_image_bytes: count(value.compiled_image_bytes),
        maximum_compiled_image_bytes: count(value.maximum_compiled_image_bytes),
        preparing: count(value.preparing),
        maximum_concurrent_preparations: count(value.maximum_concurrent_preparations),
        preparing_source_bytes: count(value.preparing_source_bytes),
        preparing_metadata_bytes: count(value.preparing_metadata_bytes),
        hits: value.hits,
        misses: value.misses,
        evictions: value.evictions,
        invalidations: value.invalidations,
    }
}
