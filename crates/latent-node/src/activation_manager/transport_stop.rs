use std::sync::atomic::{AtomicU8, Ordering};

use latent_core::{PlatformError, PlatformErrorCode};
use tokio::sync::Notify;

use super::control::{deadline_error, error};

/// A trusted local transport's interruption of one exact activation owner.
/// This is separate from an accepted explicit cancellation request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationTransportInterruption {
    Disconnected,
    DeadlineExceeded,
}

/// Only the affine handle can mark this state. Probes and the lifecycle hold
/// read-only views; no completion, manager, ledger or runtime is retained here.
#[derive(Default)]
pub(super) struct TransportStop {
    cause: AtomicU8,
    changed: Notify,
}

impl TransportStop {
    pub(super) fn mark(&self, cause: ActivationTransportInterruption) {
        let value = match cause {
            ActivationTransportInterruption::Disconnected => 1,
            ActivationTransportInterruption::DeadlineExceeded => 2,
        };
        if self
            .cause
            .compare_exchange(0, value, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            // The consuming handle port must be called outside owner-table locks.
            self.changed.notify_waiters();
        }
    }

    pub(super) fn cause(&self) -> Option<ActivationTransportInterruption> {
        match self.cause.load(Ordering::Acquire) {
            1 => Some(ActivationTransportInterruption::Disconnected),
            2 => Some(ActivationTransportInterruption::DeadlineExceeded),
            _ => None,
        }
    }

    pub(super) fn disconnected(&self) -> bool {
        self.cause() == Some(ActivationTransportInterruption::Disconnected)
    }

    pub(super) fn failure(&self) -> Option<PlatformError> {
        self.cause().map(|cause| match cause {
            ActivationTransportInterruption::Disconnected => error(
                PlatformErrorCode::Cancelled,
                "activation transport disconnected",
            ),
            ActivationTransportInterruption::DeadlineExceeded => deadline_error(),
        })
    }

    pub(super) async fn interrupted(&self) {
        loop {
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.cause().is_some() {
                return;
            }
            changed.await;
        }
    }

    pub(super) async fn disconnect(&self) {
        self.interrupted().await;
        if !self.disconnected() {
            // First-wins deadline marks cannot later become cancellation. Do
            // not repeatedly wake a cancellation probe for a deadline signal.
            std::future::pending::<()>().await;
        }
    }
}

#[cfg(test)]
mod tests;
