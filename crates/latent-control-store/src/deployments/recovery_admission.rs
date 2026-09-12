//! Startup alone may briefly yield to the existing authority lease renewer.
//!
//! Each read/check owns at most one timer and a five-second retry budget. No
//! complete catalog compilation, invocation, or mutation is retried here.

use std::time::Duration;

use latent_artifacts::{ArtifactRepository, ReleaseUseEligibility, VerifiedArtifactMetadata};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use tokio::time::Instant;

pub(super) struct Retry {
    deadline: Option<Instant>,
}

impl Retry {
    pub(super) fn new(recovery: bool) -> Self {
        Self {
            deadline: recovery.then(|| Instant::now() + Duration::from_secs(5)),
        }
    }

    pub(super) async fn pause(&self, failure: &PlatformError) -> bool {
        let Some(deadline) = self.deadline else {
            return false;
        };
        if failure.code != PlatformErrorCode::Unavailable
            || failure.message != "admission-authority-busy"
            || Instant::now() >= deadline
        {
            return false;
        }
        tokio::time::sleep_until((Instant::now() + Duration::from_millis(10)).min(deadline)).await;
        Instant::now() < deadline
    }
}

pub(super) async fn check<T>(
    recovery: bool,
    mut operation: impl FnMut() -> Result<T, PlatformError>,
) -> Result<T, PlatformError> {
    let retry = Retry::new(recovery);
    loop {
        match operation() {
            Err(failure) if retry.pause(&failure).await => {}
            result => return result,
        }
    }
}

pub(super) async fn metadata(
    artifacts: &dyn ArtifactRepository,
    release: &ReleaseDigest,
    recovery: bool,
) -> Result<VerifiedArtifactMetadata, PlatformError> {
    let retry = Retry::new(recovery);
    loop {
        match artifacts.fetch_verified_metadata(release).await {
            Err(failure) if retry.pause(&failure).await => {}
            result => return result,
        }
    }
}

pub(super) async fn eligibility(
    artifacts: &dyn ArtifactRepository,
    release: &ReleaseDigest,
    recovery: bool,
) -> Result<Option<ReleaseUseEligibility>, PlatformError> {
    check(recovery, || {
        let eligibility = artifacts.execution_eligibility(release)?;
        if let Some(grant) = &eligibility {
            grant.check_current()?;
        }
        Ok(eligibility)
    })
    .await
}

#[cfg(test)]
mod tests;
