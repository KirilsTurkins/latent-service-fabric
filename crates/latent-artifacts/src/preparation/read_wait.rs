//! A scheduler cannot supply a successful authority check or verified bytes.
use crate::ReleaseUseEligibility;
use latent_core::{PlatformError, PlatformErrorCode};

/// Optional scheduling after a sealed source has returned the exact transient
/// admission-currentness busy error. Called on a bounded blocking worker, after
/// every read guard is released. `true` requests another pure check; it never
/// authorizes access or repeats a file read. Implementations must use a finite
/// non-renewing window, yield the worker, and honor its owner cancellation.
pub trait ArtifactPreparationReadWait: Send + Sync {
    fn wait_after_busy(&self) -> bool;
}

pub(crate) struct ReadControl<'a> {
    pub(crate) original: &'a ReleaseUseEligibility,
    pub(crate) wait: &'a dyn ArtifactPreparationReadWait,
}

impl ReadControl<'_> {
    pub(crate) fn check<T>(
        &self,
        mut read: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        loop {
            let result = (|| {
                self.original.check_current()?;
                let result = read()?;
                // Catalog renewal must not upgrade the captured grant.
                self.original.check_current()?;
                Ok(result)
            })();
            match result {
                Err(error) if busy(&error) && self.wait.wait_after_busy() => {}
                result => return result,
            }
        }
    }
}

fn busy(error: &PlatformError) -> bool {
    let [detail] = error.details.as_slice() else {
        return false;
    };
    error.code == PlatformErrorCode::Unavailable
        && error.retryable
        && detail.kind == "admission.currentness"
        && detail.fields.len() == 1
        && detail.fields.get("reason").map(String::as_str) == Some("admission-authority-busy")
}
