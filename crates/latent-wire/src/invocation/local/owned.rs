use super::super::cleanup::CleanupSlot;
use super::super::{
    InvocationCancellation, InvocationInterruption, InvocationReceipt, InvocationResponse,
    InvocationRevision,
};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use latent_node::{ActivationHandle, ActivationReceipt, ActivationTransportInterruption};
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};

pub(super) struct LocalInvocation {
    handle: Option<ActivationHandle>,
    cancellation: InvocationCancellation,
    interrupted: BoxFuture<'static, ()>,
    cleanup: Option<CleanupSlot>,
}
impl LocalInvocation {
    pub(super) fn new(
        handle: ActivationHandle,
        cancellation: InvocationCancellation,
        cleanup: Option<CleanupSlot>,
    ) -> Self {
        let notification = cancellation.clone();
        Self {
            handle: Some(handle),
            cancellation,
            interrupted: Box::pin(async move { notification.cancelled().await }),
            cleanup,
        }
    }
    fn abandon(&mut self) {
        if let Some(handle) = self.handle.take() {
            if let Some(slot) = self.cleanup.take() {
                let cause = match self.cancellation.cause() {
                    Some(InvocationInterruption::DeadlineExceeded) => {
                        ActivationTransportInterruption::DeadlineExceeded
                    }
                    _ => ActivationTransportInterruption::Disconnected,
                };
                slot.continue_after_interruption(handle, cause);
            } else if self.cancellation.cause() == Some(InvocationInterruption::DeadlineExceeded) {
                handle.abort_due_to_deadline();
            } else {
                drop(handle);
            }
        }
    }
    fn interruption(&mut self) -> Option<PlatformError> {
        let cause = self.cancellation.cause()?;
        // An opted-in node retains the original owner through cooperative
        // cleanup. The interrupted transport does not await that continuation.
        self.abandon();
        Some(PlatformError {
            code: match cause {
                InvocationInterruption::Cancelled => PlatformErrorCode::Cancelled,
                InvocationInterruption::DeadlineExceeded => PlatformErrorCode::DeadlineExceeded,
            },
            message: match cause {
                InvocationInterruption::Cancelled => "invocation transport cancelled",
                InvocationInterruption::DeadlineExceeded => {
                    "invocation transport deadline exceeded"
                }
            }
            .to_owned(),
            retryable: false,
            details: Vec::new(),
        })
    }
}
impl Future for LocalInvocation {
    type Output = Result<InvocationResponse, PlatformError>;
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        if let Some(error) = this.interruption() {
            return Poll::Ready(Err(error));
        }
        let handle = this.handle.as_mut().expect("live local invocation");
        if let Poll::Ready(receipt) = Pin::new(handle).poll(context) {
            // No await follows the manager's terminal publication. The adapter's
            // biased result branch can therefore observe the same winner.
            drop(this.handle.take());
            drop(this.cleanup.take());
            return Poll::Ready(Ok(response(receipt)));
        }
        if this.interrupted.as_mut().poll(context).is_ready() {
            return Poll::Ready(Err(this.interruption().expect("sticky interruption cause")));
        }
        Poll::Pending
    }
}
impl Drop for LocalInvocation {
    fn drop(&mut self) {
        // The RPC deadline branch marks the cause before dropping this future;
        // there need not be another poll after the timer or disconnect fires.
        self.abandon();
    }
}
fn response(receipt: ActivationReceipt) -> InvocationResponse {
    InvocationResponse {
        receipt: InvocationReceipt {
            activation_id: receipt.activation_id,
            resolved_revision: receipt
                .resolved_revision
                .map(|revision| InvocationRevision {
                    revision_id: revision.revision,
                    release_digest: revision.release,
                    route_generation: revision.route_generation,
                }),
        },
        outcome: receipt.outcome,
    }
}
