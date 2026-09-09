use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;

use crate::containment::platform_error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[expect(
    clippy::struct_field_names,
    reason = "Independent cache ceilings share a consistent maximum_ naming convention."
)]
pub(crate) struct CacheLimits {
    pub maximum_entries: usize,
    pub maximum_source_bytes: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_compiled_image_bytes: usize,
    pub maximum_concurrent_preparations: usize,
}

impl CacheLimits {
    pub(crate) fn validate(&self) -> Result<(), PlatformError> {
        if [
            self.maximum_entries,
            self.maximum_source_bytes,
            self.maximum_metadata_bytes,
            self.maximum_compiled_image_bytes,
            self.maximum_concurrent_preparations,
        ]
        .contains(&0)
            || self
                .maximum_source_bytes
                .checked_mul(self.maximum_concurrent_preparations)
                .is_none()
            || self
                .maximum_metadata_bytes
                .checked_mul(self.maximum_concurrent_preparations)
                .is_none()
        {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "invalid prepared-cache limits",
                false,
            ));
        }
        Ok(())
    }
}

/// Resident prepared-cache accounting; no store or running instance is cached.
///
/// An invocation can pin an evicted value until its instance permit is released.
/// Compiled image bytes exclude compiler heap, temporary compilation work and
/// process RSS. Preparing bytes are separately bounded by the admitted slots.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparedCacheSnapshot {
    pub entries: usize,
    pub source_bytes: usize,
    pub maximum_entries: usize,
    pub maximum_source_bytes: usize,
    pub metadata_bytes: usize,
    pub maximum_metadata_bytes: usize,
    pub compiled_image_bytes: usize,
    pub maximum_compiled_image_bytes: usize,
    pub preparing: usize,
    pub maximum_concurrent_preparations: usize,
    pub preparing_source_bytes: usize,
    pub preparing_metadata_bytes: usize,
    /// Successful resident lookups, including preparation and legacy invocation.
    pub hits: u64,
    /// Valid lookups with no resident entry; these may later fail preparation.
    pub misses: u64,
    pub evictions: u64,
    /// Explicit matching-release removals, separate from capacity eviction.
    pub invalidations: u64,
}
