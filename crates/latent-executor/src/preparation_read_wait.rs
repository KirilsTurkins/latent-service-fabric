//! An explicitly supplied caller timer, never preparation or execution authority.

use std::time::Instant;

use latent_core::BoxFuture;

/// Executor-neutral timing for a bounded currentness-read wait. Implementations
/// must use one monotonic time domain for both methods. A wait belongs only to
/// the returned future: dropping it must retire its registration without a
/// detached task, worker or retained preparation. This interface cannot renew
/// a grant, extend the caller's deadline or authorize replaying owned work.
pub trait PreparationReadWait: Send + Sync {
    fn now(&self) -> Instant;

    /// Completes only once `now()` reaches the supplied deadline. Polling an
    /// unexpired wait must yield to the caller's executor rather than spin.
    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()>;
}

#[cfg(test)]
mod tests;
