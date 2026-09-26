//! Only failed currentness reads may wait; owned preparation work is never replayed.
use std::time::{Duration, Instant};

use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparationReadWait;

pub(in crate::backend) struct Window<'a> {
    wait: Option<&'a dyn PreparationReadWait>,
    until: Option<Instant>,
}

impl<'a> Window<'a> {
    pub(in crate::backend) fn new(wait: Option<&'a dyn PreparationReadWait>) -> Self {
        Self {
            wait,
            until: wait.and_then(|wait| wait.now().checked_add(Duration::from_secs(5))),
        }
    }

    /// Call only around sealed source observations or a pure eligibility check.
    /// The caller retains its original activation deadline and cancellation by
    /// owning this future. A failed read drops every currentness guard before
    /// this one timer is awaited. All checkpoints share the original window.
    pub(in crate::backend) async fn check<T>(
        &self,
        mut read: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        loop {
            let failure = match read() {
                Err(failure) if busy(&failure) => failure,
                result => return result,
            };
            let (Some(wait), Some(until)) = (self.wait, self.until) else {
                // The original executor-neutral API remains nonblocking.
                return Err(failure);
            };
            if wait.now() >= until {
                return Err(failure);
            }
            wait.wait_until(
                wait.now()
                    .checked_add(Duration::from_millis(10))
                    .unwrap_or(until)
                    .min(until),
            )
            .await;
            if wait.now() >= until {
                return Err(failure);
            }
        }
    }
}

pub(super) fn busy(error: &PlatformError) -> bool {
    let [detail] = error.details.as_slice() else {
        return false;
    };
    error.code == PlatformErrorCode::Unavailable
        && error.retryable
        && detail.kind == "admission.currentness"
        && detail.fields.len() == 1
        && detail.fields.get("reason").map(String::as_str) == Some("admission-authority-busy")
}

#[cfg(test)]
mod tests;
