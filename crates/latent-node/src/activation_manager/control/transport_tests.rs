use std::sync::atomic::{AtomicBool, Ordering};

use latent_core::ActivationId;
use latent_executor::ExecutionCleanup;

use super::tests::{poll, Clock};
use super::*;
use crate::activation_manager::ActivationTransportInterruption as Cause;
use crate::ActivationCancellationRegistry;

#[tokio::test(start_paused = true)]
async fn explicit_then_deadline_then_transport_then_ready_work_is_the_stage_priority() {
    for explicit in [false, true] {
        for expired in [false, true] {
            let clock: Arc<dyn ActivationClock> = Arc::new(Clock::new(true));
            let registry = ActivationCancellationRegistry::default();
            let registration = registry.register(ActivationId("priority".into())).unwrap();
            let token = registration.token();
            let stop = TransportStop::default();
            stop.mark(Cause::Disconnected);
            if explicit {
                registration.handle().cancel("explicit winner");
            }
            let expiry = clock.monotonic_now()
                + if expired {
                    Duration::ZERO
                } else {
                    Duration::from_secs(1)
                };
            let failure = stage(async { Ok(7) }, &token, Some(expiry), &clock, &stop)
                .await
                .unwrap_err();
            assert_eq!(
                failure.code,
                if expired && !explicit {
                    PlatformErrorCode::DeadlineExceeded
                } else {
                    PlatformErrorCode::Cancelled
                }
            );
            assert_eq!(
                failure.message,
                if explicit {
                    "explicit winner"
                } else if expired {
                    "activation deadline exceeded"
                } else {
                    "activation transport disconnected"
                }
            );
        }
    }
}

#[tokio::test(start_paused = true)]
async fn trusted_transport_expiry_interrupts_an_injected_clock_without_changing_its_time() {
    let clock: Arc<dyn ActivationClock> = Arc::new(Clock::new(false));
    let original = clock.monotonic_now();
    let registry = ActivationCancellationRegistry::default();
    let registration = registry.register(ActivationId("injected".into())).unwrap();
    let token = registration.token();
    let stop = TransportStop::default();
    let mut waiting = Box::pin(stage(
        pending::<Result<(), PlatformError>>(),
        &token,
        Some(original + Duration::from_secs(1)),
        &clock,
        &stop,
    ));
    assert!(poll(waiting.as_mut()).is_pending());
    stop.mark(Cause::DeadlineExceeded);
    let Poll::Ready(Err(failure)) = poll(waiting.as_mut()) else {
        panic!("stop is ready");
    };
    assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
    assert_eq!(clock.monotonic_now(), original);
    assert!(!token.is_cancelled());
}

struct PendingOwner(Arc<AtomicBool>);
impl Future for PendingOwner {
    type Output = ExecutionReport;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        Poll::Pending
    }
}
impl Drop for PendingOwner {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

#[tokio::test(start_paused = true)]
async fn a_second_transport_cause_cannot_renew_an_acknowledgement_already_in_progress() {
    let clock: Arc<dyn ActivationClock> = Arc::new(Clock::new(true));
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("same-owner".into()))
        .unwrap();
    let token = registration.token();
    let stop = TransportStop::default();
    let dropped = Arc::new(AtomicBool::new(false));
    let mut work = Box::pin(execution(
        PendingOwner(dropped.clone()),
        &token,
        None,
        &clock,
        Duration::from_millis(100),
        &stop,
    ));
    assert!(poll(work.as_mut()).is_pending());
    stop.mark(Cause::Disconnected);
    assert!(poll(work.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(60)).await;
    stop.mark(Cause::DeadlineExceeded);
    assert!(poll(work.as_mut()).is_pending());
    assert!(!dropped.load(Ordering::Acquire));
    tokio::time::advance(Duration::from_millis(41)).await;
    let Poll::Ready(report) = poll(work.as_mut()) else {
        panic!("original grace expired");
    };
    assert!(matches!(
        report.cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert!(dropped.load(Ordering::Acquire));
    assert!(!token.is_cancelled());
}

#[tokio::test(start_paused = true)]
async fn disconnect_during_explicit_cleanup_keeps_its_original_grace() {
    let clock: Arc<dyn ActivationClock> = Arc::new(Clock::new(true));
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("existing-cleanup".into()))
        .unwrap();
    let token = registration.token();
    let stop = TransportStop::default();
    let dropped = Arc::new(AtomicBool::new(false));
    let mut work = Box::pin(execution(
        PendingOwner(dropped.clone()),
        &token,
        None,
        &clock,
        Duration::from_millis(100),
        &stop,
    ));
    assert!(poll(work.as_mut()).is_pending());
    registration.handle().cancel("original explicit cleanup");
    assert!(poll(work.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(60)).await;
    stop.mark(Cause::Disconnected);
    assert!(poll(work.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(41)).await;
    let Poll::Ready(report) = poll(work.as_mut()) else {
        panic!("original grace expired");
    };
    assert_eq!(
        report.outcome.unwrap_err().message,
        "original explicit cleanup"
    );
    assert!(dropped.load(Ordering::Acquire));
}
