use super::state::CleanupSlot;
use latent_node::{ActivationHandle, ActivationReceipt, ActivationTransportInterruption};
use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
    time::Instant,
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
            shared: None,
        }
    }

    /// The same pre-reserved slot may continue an already-sponsored command
    /// through its original deadline, without creating another task or quota.
    pub fn own_shared<R: Send + Unpin + 'static>(
        self,
        handle: ActivationHandle,
        retention: R,
        owner: Arc<latent_node::transaction_runtime::SharedCommandOwner>,
        deadline: Instant,
    ) -> RetainedActivation<R> {
        let mut retained = self.own(handle, retention);
        retained.shared = Some(SharedRetention { owner, deadline });
        retained
    }
}

struct SharedRetention {
    owner: Arc<latent_node::transaction_runtime::SharedCommandOwner>,
    deadline: Instant,
}

/// Dropping a request task transfers this exact activation and its retained
/// adapter state to the bounded driver. No new task or useful-work budget is created.
#[must_use = "await or transfer this owner through cancellation cleanup"]
pub struct RetainedActivation<R: Send + Unpin + 'static> {
    handle: Option<ActivationHandle>,
    retention: Option<R>,
    slot: Option<CleanupSlot>,
    cause: ActivationTransportInterruption,
    shared: Option<SharedRetention>,
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
        if let Some(shared) = this.shared.take() {
            shared.owner.close();
        }
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
            let slot = self.slot.take().expect("reserved cleanup");
            let retention = self.retention.take().expect("retained adapter state");
            if let Some(shared) = self.shared.take() {
                if self.cause == ActivationTransportInterruption::Disconnected
                    && shared.owner.close_for_disconnect()
                {
                    slot.continue_shared_with_retention(handle, retention, shared.deadline);
                    return;
                }
                shared.owner.close();
            }
            slot.continue_with_retention(handle, self.cause, retention);
        }
    }
}
