//! A finite per-operation timer over an existing admitted I/O owner.
use latent_capabilities::broker::{io::IoStopHandle, streaming_http::HttpPhaseError};
use std::{
    future::Future,
    time::{Duration, Instant},
};

pub(super) struct Deadline {
    at: Option<Instant>,
    control: IoStopHandle,
}
impl Deadline {
    pub(super) fn new(control: IoStopHandle, millis: Option<u32>) -> Result<Self, HttpPhaseError> {
        let original = control.deadline()?;
        let at = millis
            .filter(|value| *value != 0)
            .map(|value| (Instant::now() + Duration::from_millis(u64::from(value))).min(original));
        Ok(Self { at, control })
    }
    /// Capture once at entry, retaining the caller's original deadline. The
    /// pending future is physically destroyed before a timeout is observable.
    pub(super) async fn wait<F: Future>(
        &self,
        future: F,
        timeout: HttpPhaseError,
    ) -> Result<F::Output, HttpPhaseError> {
        self.control.checkpoint()?;
        let mut future = Box::pin(future);
        let result = if let Some(at) = self.at {
            tokio::select! {
                biased;
                () = tokio::time::sleep_until(at.into()) => {
                    // Original cancellation/deadline wins, even if both clocks
                    // become ready together. A phase cannot relabel either.
                    self.control.checkpoint()?;
                    Err(timeout)
                },
                value = &mut future => {
                    self.control.checkpoint()?;
                    Ok(value)
                },
            }
        } else {
            Ok(future.as_mut().await)
        };
        drop(future);
        result
    }
}
