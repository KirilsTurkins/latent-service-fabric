//! Independent admission ownership; optimization stamps never grant execution.

use latent_artifacts::ReleaseUseEligibility;
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::ExecutionRequest;

use super::{PreparationContext, PreparedRuntime};
use crate::containment::platform_error;

#[cfg(test)]
mod tests;

/// Private, affine evidence of the final guarded activation-start decision.
/// The caller retains it until that one invocation completes.
pub(super) struct ExecutionEligibility(());

impl PreparationContext {
    pub(super) fn check_eligibility(
        &self,
        eligibility: Option<&ReleaseUseEligibility>,
        release: &ReleaseDigest,
    ) -> Result<(), PlatformError> {
        if let Some(owner) = &self.lifecycle {
            eligibility
                .ok_or_else(|| denied("prepared-lifecycle-required"))?
                .check_for_lifecycle(owner)?;
        }
        match (self.admission.as_ref(), eligibility) {
            (Some(authority), Some(eligibility)) => {
                if eligibility.release() != release {
                    return Err(denied("prepared-admission-release-mismatch"));
                }
                eligibility.check_for_authority(authority)
            }
            (Some(_), None) => Err(denied("prepared-admission-required")),
            (None, Some(eligibility)) => {
                if eligibility.release() != release {
                    return Err(denied("prepared-admission-release-mismatch"));
                }
                eligibility.check_current()
            }
            (None, None) => Ok(()),
        }
    }

    pub(super) fn check_runtime(&self, runtime: &PreparedRuntime) -> Result<(), PlatformError> {
        self.check_eligibility(
            runtime.eligibility.as_ref(),
            &runtime.descriptor.key.release,
        )
    }

    pub(super) fn start_execution(
        &self,
        runtime: &PreparedRuntime,
        request: &ExecutionRequest,
    ) -> Result<ExecutionEligibility, PlatformError> {
        self.check_runtime(runtime)?;
        if runtime.descriptor != request.prepared {
            return Err(denied("prepared-admission-descriptor-mismatch"));
        }
        let mut accepted = None;
        if let Some(eligibility) = &runtime.eligibility {
            eligibility.authorize_tenant(&request.activation.target.tenant)?;
            eligibility.with_current(&mut |checker| {
                checker.check()?;
                accepted = Some(ExecutionEligibility(()));
                Ok(())
            })?;
        } else {
            // Only an explicitly unmanaged trusted-local factory reaches here.
            accepted = Some(ExecutionEligibility(()));
        }
        accepted.ok_or_else(|| denied("prepared-admission-start-missing"))
    }
}

pub(super) fn scoped_handle(handle: String, eligibility: Option<&ReleaseUseEligibility>) -> String {
    if let Some(eligibility) = eligibility {
        let mut hash = blake3::Hasher::new();
        hash.update(b"lsf-admitted-preparation-v1\0");
        hash.update(handle.as_bytes());
        hash.update(&eligibility.cache_digest());
        format!("wasmtime-admitted:{}", hash.finalize().to_hex())
    } else {
        handle
    }
}

fn denied(reason: &'static str) -> PlatformError {
    platform_error(PlatformErrorCode::PermissionDenied, reason, false)
}
