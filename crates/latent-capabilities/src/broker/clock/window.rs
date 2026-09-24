use std::time::{Duration, Instant};

use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparationReadWait;

use super::WaitingCall;

pub(super) struct Window<'a> {
    wait: &'a dyn PreparationReadWait,
    until: Instant,
}

impl<'a> Window<'a> {
    pub(super) fn new(
        wait: &'a dyn PreparationReadWait,
        deadline: Option<Instant>,
    ) -> Result<Self, PlatformError> {
        let limit = wait
            .now()
            .checked_add(Duration::from_secs(5))
            .ok_or_else(super::super::capacity)?;
        Ok(Self {
            wait,
            until: deadline.map_or(limit, |deadline| deadline.min(limit)),
        })
    }

    pub(super) async fn pause(
        &self,
        failure: &PlatformError,
        waiting: &WaitingCall,
        call_deadline: Option<Instant>,
    ) -> Result<bool, PlatformError> {
        let until = call_deadline.map_or(self.until, |deadline| deadline.min(self.until));
        if !busy(failure) || self.wait.now() >= until {
            return Ok(false);
        }
        waiting.check()?;
        let next = self
            .wait
            .now()
            .checked_add(Duration::from_millis(10))
            .unwrap_or(until)
            .min(until);
        self.wait.wait_until(next).await;
        waiting.check()?;
        Ok(self.wait.now() < until)
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

#[cfg(test)]
mod tests;
