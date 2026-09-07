//! A first-wins transport interruption cause, separate from lifecycle ownership.
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::Arc;
use tokio::sync::Notify;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InvocationInterruption {
    Cancelled,
    DeadlineExceeded,
}
#[derive(Default)]
struct State {
    cause: AtomicU8,
    notification: Notify,
}
/// Cloning this signal does not clone or detach an activation. The runtime
/// future retains its affine owner and inspects the cause before dropping it.
#[derive(Clone, Default)]
pub struct InvocationCancellation {
    inner: Arc<State>,
}
impl std::fmt::Debug for InvocationCancellation {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("InvocationCancellation")
            .field("cause", &self.cause())
            .finish_non_exhaustive()
    }
}
impl InvocationCancellation {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
    #[must_use]
    pub fn cause(&self) -> Option<InvocationInterruption> {
        match self.inner.cause.load(Ordering::Acquire) {
            1 => Some(InvocationInterruption::Cancelled),
            2 => Some(InvocationInterruption::DeadlineExceeded),
            _ => None,
        }
    }
    pub fn cancel(&self) {
        self.interrupt(1);
    }
    pub fn expire(&self) {
        self.interrupt(2);
    }
    /// Compatibility observation: either transport cause interrupts the call.
    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.cause().is_some()
    }
    pub async fn cancelled(&self) {
        loop {
            let notification = self.inner.notification.notified();
            tokio::pin!(notification);
            notification.as_mut().enable();
            if self.is_cancelled() {
                return;
            }
            notification.await;
        }
    }
    fn interrupt(&self, cause: u8) {
        if self
            .inner
            .cause
            .compare_exchange(0, cause, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            self.inner.notification.notify_waiters();
        }
    }
}
#[cfg(test)]
mod tests;
