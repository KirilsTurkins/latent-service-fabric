//! Explicit original offline-snapshot/v1 recovery profile.
//!
//! Retained v1 bytes are never relabelled as protected snapshot/v2, migration/v2
//! or migration-resume/v1. This adapter preserves original decoding and logical
//! plans; its offline facade uses the same `ProtectedStoreOwner` and fixed workers.
//! Descriptions and historical grants do not establish current authority.

pub mod migration;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub mod offline;
pub mod restore;
pub mod resume;
pub mod snapshot;

pub use super::{guard_key, require_namespace_ready, require_ready, RecoveryGuard, RecoveryStatus};

/// Original v1 plans do not rewrite the protected v2 tenant accounting or
/// migration formats. Switching profiles requires explicit supported recovery;
/// neither a new boot nor an absent ordinary command makes that upgrade safe.
pub(crate) fn require_profile(
    view: &crate::embedded::ReadView,
) -> Result<(), crate::embedded::StoreError> {
    use crate::embedded::{Family, StoreError};
    if view.contains_prefix(Family::Maintenance, &crate::tenant::guard_key().key)?
        || view.contains_prefix(Family::Maintenance, super::migration::PROGRESS_PREFIX)?
        || view.contains_prefix(Family::Maintenance, super::resume::RECEIPT_PREFIX)?
    {
        return Err(StoreError::UnsupportedFormat);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
