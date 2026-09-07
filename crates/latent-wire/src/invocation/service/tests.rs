use super::*;
use crate::invocation::InvocationInterruption;
use std::future::Future;
use std::pin::Pin;
use std::sync::Mutex;
use std::task::{Context, Poll};

struct ObservedFuture {
    cancellation: InvocationCancellation,
    observed: Arc<Mutex<Option<InvocationInterruption>>>,
    ready: bool,
}
impl Future for ObservedFuture {
    type Output = Result<InvocationResponse, PlatformError>;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        if self.ready {
            Poll::Ready(Err(super::super::boundary_error(
                latent_core::PlatformErrorCode::RouteUnavailable,
                "test completion",
            )))
        } else {
            Poll::Pending
        }
    }
}
impl Drop for ObservedFuture {
    fn drop(&mut self) {
        *self.observed.lock().unwrap() = self.cancellation.cause();
    }
}
fn owner(
    ready: bool,
) -> (
    PendingInvocation<'static>,
    Arc<Mutex<Option<InvocationInterruption>>>,
) {
    let cancellation = InvocationCancellation::new();
    let observed = Arc::new(Mutex::new(None));
    let future = ObservedFuture {
        cancellation: cancellation.clone(),
        observed: Arc::clone(&observed),
        ready,
    };
    (
        PendingInvocation {
            future: Some(Box::pin(future)),
            cancellation,
            armed: true,
        },
        observed,
    )
}

#[test]
fn disconnect_cause_is_visible_before_runtime_future_destruction() {
    let (invocation, observed) = owner(false);
    drop(invocation);
    assert_eq!(
        *observed.lock().unwrap(),
        Some(InvocationInterruption::Cancelled)
    );
}

#[tokio::test]
async fn borrowed_select_records_deadline_before_destruction_and_preserves_ready_completion() {
    for completed in [false, true] {
        let (mut invocation, observed) = owner(completed);
        let result_won = tokio::select! {
            biased;
            _ = invocation.future.as_mut().unwrap().as_mut() => true,
            () = std::future::ready(()) => {
                invocation.cancellation.expire();
                false
            }
        };
        invocation.armed = false;
        drop(invocation);
        assert_eq!(result_won, completed);
        assert_eq!(
            *observed.lock().unwrap(),
            if completed {
                None
            } else {
                Some(InvocationInterruption::DeadlineExceeded)
            }
        );
    }
}
