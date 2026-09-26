use super::state::CleanupSlot;
use latent_node::{ActivationHandle, ActivationReceipt, ActivationTransportInterruption};
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};

/// One slot in the existing fixed cleanup driver, reserved before acceptance.
/// Retention is host-owned and must have its own finite resource reservation.
pub struct ActivationCleanupReservation(pub(super) CleanupSlot);

impl ActivationCleanupReservation {
    pub fn own<R: Send + Unpin + 'static>(
        self,
        handle: ActivationHandle,
        retention: R,
    ) -> RetainedActivation<R> {
        RetainedActivation {
            handle: Some(handle),
            retention: Some(retention),
            slot: Some(self.0),
            cause: ActivationTransportInterruption::Disconnected,
        }
    }
}

/// Dropping a request task transfers this exact activation and its retained
/// adapter state to the bounded driver. No new task or useful-work budget exists.
#[must_use = "await or transfer this owner through cancellation cleanup"]
pub struct RetainedActivation<R: Send + Unpin + 'static> {
    handle: Option<ActivationHandle>,
    retention: Option<R>,
    slot: Option<CleanupSlot>,
    cause: ActivationTransportInterruption,
}
impl<R: Send + Unpin + 'static> RetainedActivation<R> {
    /// Explicit timeout has a distinct terminal cause from disconnect/drop.
    pub fn interrupt(mut self, cause: ActivationTransportInterruption) {
        self.cause = cause;
        drop(self);
    }
}
impl<R: Send + Unpin + 'static> Future for RetainedActivation<R> {
    type Output = (ActivationReceipt, R);
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let receipt =
            std::task::ready!(Pin::new(this.handle.as_mut().expect("live activation")).poll(cx));
        drop(this.handle.take());
        drop(this.slot.take());
        Poll::Ready((
            receipt,
            this.retention.take().expect("retained adapter state"),
        ))
    }
}
impl<R: Send + Unpin + 'static> Drop for RetainedActivation<R> {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            self.slot
                .take()
                .expect("reserved cleanup")
                .continue_with_retention(
                    handle,
                    self.cause,
                    self.retention.take().expect("retained adapter state"),
                );
        }
    }
}
