use serde::Serialize;

use crate::PreparedCacheSnapshot;

/// Existing measured cache residency and optional unique-runtime accounting.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparedCacheAccountingSnapshot {
    pub resident: PreparedCacheSnapshot,
    /// `None` denotes unavailable accounting, not an empty population.
    pub runtimes: Option<PreparedRuntimeSnapshot>,
}

/// Costs counted once for each distinct prepared runtime in a population.
///
/// Source bytes describe associated component content, usually no longer held
/// as source bytes. Metadata is the backend's immutable metadata charge. Image
/// bytes describe compiled image spans, not process RSS or physical page use.
/// No live guest store or instance belongs to these populations.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct PreparedRuntimePopulation {
    pub runtimes: u64,
    pub source_bytes: u64,
    pub metadata_bytes: u64,
    pub compiled_image_bytes: u64,
}

/// Unique runtime ownership, independent of conservative per-ready-owner
/// admission charges. Moving a ready owner into an active owner retains the
/// same unique runtime. These fields do not measure allocator overhead or RSS.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct PreparedRuntimeSnapshot {
    /// Sum of the three disjoint live populations below.
    pub live: PreparedRuntimePopulation,
    /// Constructed runtimes not admitted to the cache, including uncached uses.
    pub unpublished: PreparedRuntimePopulation,
    pub resident: PreparedRuntimePopulation,
    /// Former residents still held by affine uses, ready owners, or temporary
    /// compiler/deferred-eviction owners. This is not an active-invocation count.
    pub evicted_live: PreparedRuntimePopulation,
}
