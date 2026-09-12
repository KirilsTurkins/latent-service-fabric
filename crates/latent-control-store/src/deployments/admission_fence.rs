//! Live release eligibility is separate from immutable route generations.

use std::sync::Arc;

use latent_artifacts::{AdmissionAuthority, AdmissionRecheck, ReleaseEligibility};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{compiler::CompiledCatalog, error};

impl CompiledCatalog {
    pub(super) fn eligibility_for(&self, release: &ReleaseDigest) -> Option<&ReleaseEligibility> {
        self.eligibility
            .binary_search_by(|entry| entry.release().cmp(release))
            .ok()
            .map(|position| &self.eligibility[position])
    }

    pub(super) fn check_admission_mode(
        &self,
        authority: Option<&Arc<dyn AdmissionAuthority>>,
    ) -> Result<(), PlatformError> {
        if let Some(authority) = authority {
            if self.local_releases != 0 {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "route-admission-required",
                ));
            }
            for entry in &self.eligibility {
                entry.check_for_authority(authority)?;
            }
        }
        Ok(())
    }

    pub(super) fn with_current_admission(
        &self,
        action: &mut dyn FnMut(Option<&dyn AdmissionRecheck>) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if self.eligibility.is_empty() {
            // After enforced-mode validation this means the catalog is empty;
            // an empty generation cannot confer release execution authority.
            action(None)
        } else {
            ReleaseEligibility::with_all_current(&self.eligibility, &mut |checker| {
                action(Some(checker))
            })
        }
    }
}

pub(super) fn check_selected(
    eligibility: Option<&ReleaseEligibility>,
    tenant: &TenantId,
) -> Result<(), PlatformError> {
    if let Some(eligibility) = eligibility {
        if eligibility.tenant() != tenant {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "route-admission-tenant-mismatch",
            ));
        }
        eligibility.check_current()?;
    }
    Ok(())
}
