//! Live release eligibility is separate from immutable route generations.

use std::sync::Arc;

use latent_artifacts::{
    AdmissionAuthority, LifecycleAuthorityHandle, ReleaseUseEligibility, ReleaseUseRecheck,
};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::compiler::execution::InactiveRelease;
use super::{compiler::CompiledCatalog, error};

#[derive(Clone)]
pub(super) enum SelectedEligibility {
    Eligible(ReleaseUseEligibility),
    Inactive(InactiveRelease),
}

impl CompiledCatalog {
    pub(super) fn selected_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Option<SelectedEligibility> {
        if let Some(positive) = self.eligibility_for(release) {
            return Some(SelectedEligibility::Eligible(positive.clone()));
        }
        self.inactive
            .binary_search_by(|entry| entry.release().cmp(release))
            .ok()
            .map(|index| SelectedEligibility::Inactive(self.inactive[index].clone()))
    }
    pub(super) fn eligibility_for(
        &self,
        release: &ReleaseDigest,
    ) -> Option<&ReleaseUseEligibility> {
        self.eligibility
            .binary_search_by(|entry| entry.release().cmp(release))
            .ok()
            .map(|position| &self.eligibility[position])
    }

    pub(super) fn check_admission_mode(
        &self,
        authority: Option<&Arc<dyn AdmissionAuthority>>,
        lifecycle: Option<&LifecycleAuthorityHandle>,
    ) -> Result<(), PlatformError> {
        if let Some(owner) = lifecycle {
            if self.local_releases != 0 {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "route-lifecycle-required",
                ));
            }
            for entry in &self.eligibility {
                entry.check_for_lifecycle(owner)?;
            }
            for entry in &self.inactive {
                entry.check_owner(owner)?;
            }
        } else if !self.inactive.is_empty() {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "inactive-route-catalog-required",
            ));
        }
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
        action: &mut dyn FnMut(Option<&dyn ReleaseUseRecheck>) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if self.eligibility.is_empty() {
            // Empty and wholly inactive generations confer no release authority.
            action(None)
        } else {
            ReleaseUseEligibility::with_all_current(&self.eligibility, &mut |checker| {
                action(Some(checker))
            })
        }
    }
}

pub(super) fn check_selected(
    eligibility: Option<&SelectedEligibility>,
    tenant: &TenantId,
) -> Result<(), PlatformError> {
    match eligibility {
        Some(SelectedEligibility::Eligible(eligibility)) => {
            eligibility.authorize_tenant(tenant)?;
            eligibility.check_current()?;
        }
        Some(SelectedEligibility::Inactive(denied)) => {
            denied.authorize_tenant(tenant)?;
            return Err(denied.error());
        }
        None => {}
    }
    Ok(())
}
