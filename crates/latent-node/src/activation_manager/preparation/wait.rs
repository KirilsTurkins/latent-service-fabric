//! Readiness uses the existing node executor, inside the original stage owner.

use std::time::Instant;

use latent_core::BoxFuture;
use latent_executor::PreparationReadWait;

pub(super) struct Timer;

impl PreparationReadWait for Timer {
    fn now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }

    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()> {
        Box::pin(tokio::time::sleep_until(deadline.into()))
    }
}

#[cfg(test)]
mod tests;
