use super::*;
use std::future::{poll_fn, Future};
use std::task::Poll;

#[tokio::test]
async fn transport_cause_is_first_wins_and_visible_before_waiting() {
    let cancelled = InvocationCancellation::new();
    cancelled.cancel();
    cancelled.expire();
    cancelled.cancel();
    assert_eq!(cancelled.cause(), Some(InvocationInterruption::Cancelled));
    cancelled.cancelled().await;
    let expired = InvocationCancellation::new();
    expired.expire();
    expired.cancel();
    expired.expire();
    assert_eq!(
        expired.cause(),
        Some(InvocationInterruption::DeadlineExceeded)
    );
    expired.cancelled().await;
}

#[tokio::test]
async fn all_registered_waiters_observe_the_same_sticky_cause() {
    let signal = InvocationCancellation::new();
    let first = signal.cancelled();
    let second = signal.cancelled();
    tokio::pin!(first, second);
    poll_fn(|context| {
        assert!(first.as_mut().poll(context).is_pending());
        assert!(second.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    signal.expire();
    first.await;
    second.await;
    assert_eq!(
        signal.cause(),
        Some(InvocationInterruption::DeadlineExceeded)
    );
}
