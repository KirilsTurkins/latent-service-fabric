use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::task::Waker;

use latent_core::{ActivationId, ClockSample, DeadlineWaitObserver};
use latent_executor::ExecutionCleanup;

use super::*;
use crate::ActivationCancellationRegistry;

struct Clock {
    observer: DeadlineWaitObserver,
    origin: Instant,
    elapsed_millis: AtomicU64,
    system: bool,
}

impl Clock {
    fn new(system: bool) -> Self {
        Self {
            observer: DeadlineWaitObserver::new(),
            origin: tokio::time::Instant::now().into_std(),
            elapsed_millis: AtomicU64::new(0),
            system,
        }
    }
}

impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1_000, self.monotonic_now())
    }

    fn monotonic_now(&self) -> Instant {
        if self.system {
            // Tokio's controlled test clock supplies the same domain as its
            // sleep_until. Production SystemActivationClock uses real Instant.
            tokio::time::Instant::now().into_std()
        } else {
            self.origin + Duration::from_millis(self.elapsed_millis.load(Ordering::Relaxed))
        }
    }

    fn uses_system_monotonic(&self) -> bool {
        self.system
    }

    fn deadline_wait_observer(&self) -> Option<&DeadlineWaitObserver> {
        Some(&self.observer)
    }
}

fn poll<F: Future>(future: Pin<&mut F>) -> Poll<F::Output> {
    future.poll(&mut Context::from_waker(Waker::noop()))
}

#[tokio::test(start_paused = true)]
async fn system_deadline_preserves_the_controls_repeated_five_millisecond_waits() {
    let clock = Clock::new(true);
    let expiry = clock.monotonic_now() + Duration::from_millis(21);
    let mut waiting = Box::pin(deadline(Some(expiry), &clock));
    assert!(poll(waiting.as_mut()).is_pending());
    assert_eq!(clock.observer.snapshot().live, 1);
    for expected in 2..=4 {
        tokio::time::advance(Duration::from_millis(6)).await;
        assert!(poll(waiting.as_mut()).is_pending());
        assert_eq!(clock.observer.snapshot().armed, expected);
    }
    tokio::time::advance(Duration::from_millis(4)).await;
    assert!(poll(waiting.as_mut()).is_ready());
    let observed = clock.observer.snapshot();
    assert_eq!(
        (observed.armed, observed.completed, observed.dropped),
        (4, 4, 0)
    );
    assert_eq!((observed.live, observed.rechecks), (0, 4));
}

#[tokio::test(start_paused = true)]
async fn injected_clock_rechecks_with_bounded_sleeps_until_its_own_expiry() {
    let clock = Clock::new(false);
    let expiry = clock.origin + Duration::from_millis(20);
    let mut waiting = Box::pin(deadline(Some(expiry), &clock));
    assert!(poll(waiting.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(6)).await;
    assert!(poll(waiting.as_mut()).is_pending());
    let observed = clock.observer.snapshot();
    assert_eq!(
        (observed.armed, observed.completed, observed.live),
        (2, 1, 1)
    );
    assert_eq!(observed.rechecks, 1);
    clock.elapsed_millis.store(20, Ordering::Relaxed);
    tokio::time::advance(Duration::from_millis(6)).await;
    assert!(poll(waiting.as_mut()).is_ready());
    let observed = clock.observer.snapshot();
    assert_eq!(
        (observed.armed, observed.completed, observed.live),
        (2, 2, 0)
    );
    assert_eq!(observed.rechecks, 2);
}

#[tokio::test(start_paused = true)]
async fn absent_and_already_expired_deadlines_never_arm_a_sleep() {
    let clock = Clock::new(true);
    let mut absent = Box::pin(deadline(None, &clock));
    assert!(poll(absent.as_mut()).is_pending());
    drop(absent);
    let mut expired = Box::pin(deadline(Some(clock.monotonic_now()), &clock));
    assert!(poll(expired.as_mut()).is_ready());
    assert_eq!(clock.observer.snapshot().armed, 0);
    assert_eq!(clock.observer.snapshot().live, 0);
}

#[tokio::test(start_paused = true)]
async fn dropping_a_pending_wait_refunds_its_only_live_guard() {
    let clock = Clock::new(true);
    let mut waiting = Box::pin(deadline(
        Some(clock.monotonic_now() + Duration::from_secs(1)),
        &clock,
    ));
    assert!(poll(waiting.as_mut()).is_pending());
    drop(waiting);
    let observed = clock.observer.snapshot();
    assert_eq!((observed.armed, observed.dropped, observed.live), (1, 1, 0));
}

#[tokio::test(start_paused = true)]
async fn ready_work_drops_its_wait_and_preexisting_cancellation_keeps_precedence() {
    let source = Arc::new(Clock::new(true));
    let clock: Arc<dyn ActivationClock> = source.clone();
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("ready-stage".to_owned()))
        .unwrap();
    let token = registration.token();
    let expiry = source.monotonic_now() + Duration::from_secs(1);
    assert_eq!(
        stage(async { Ok(7) }, &token, Some(expiry), &clock)
            .await
            .unwrap(),
        7
    );
    let observed = source.observer.snapshot();
    assert_eq!((observed.armed, observed.dropped, observed.live), (1, 1, 0));
    assert!(registration.handle().cancel("cancelled before poll"));
    let failure = stage(
        async { Ok(8) },
        &token,
        Some(source.monotonic_now()),
        &clock,
    )
    .await
    .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Cancelled);
    assert_eq!(source.observer.snapshot(), observed);
}

struct PendingReport(Arc<AtomicBool>);

#[tokio::test(start_paused = true)]
async fn cancelling_a_pending_stage_drops_its_sleep_without_a_deadline_wakeup() {
    let source = Arc::new(Clock::new(true));
    let clock: Arc<dyn ActivationClock> = source.clone();
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("cancel-stage".to_owned()))
        .unwrap();
    let token = registration.token();
    let mut pending = Box::pin(stage(
        pending::<Result<(), PlatformError>>(),
        &token,
        Some(source.monotonic_now() + Duration::from_secs(1)),
        &clock,
    ));
    assert!(poll(pending.as_mut()).is_pending());
    assert_eq!(source.observer.snapshot().live, 1);
    assert!(registration.handle().cancel("cancel the owned stage"));
    let Poll::Ready(Err(error)) = poll(pending.as_mut()) else {
        panic!("cancellation must finish the stage");
    };
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    let observed = source.observer.snapshot();
    assert_eq!((observed.armed, observed.dropped, observed.live), (1, 1, 0));
    assert_eq!((observed.completed, observed.rechecks), (0, 0));
}

#[tokio::test(start_paused = true)]
async fn panicking_stage_drops_the_sleep_before_catch_returns() {
    let source = Arc::new(Clock::new(true));
    let clock: Arc<dyn ActivationClock> = source.clone();
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("panic-stage".to_owned()))
        .unwrap();
    let token = registration.token();
    let failing = std::future::poll_fn(|_| -> Poll<Result<(), PlatformError>> {
        panic!("injected stage panic");
    });
    let outcome = CatchPanic::new(stage(
        failing,
        &token,
        Some(source.monotonic_now() + Duration::from_secs(1)),
        &clock,
    ))
    .await;
    assert!(outcome.is_err());
    let observed = source.observer.snapshot();
    assert_eq!((observed.armed, observed.dropped, observed.live), (1, 1, 0));
}

impl Future for PendingReport {
    type Output = ExecutionReport;

    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        Poll::Pending
    }
}

impl Drop for PendingReport {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[tokio::test(start_paused = true)]
async fn execution_deadline_keeps_the_existing_cleanup_grace_and_drops_inner_work() {
    let source = Arc::new(Clock::new(true));
    let clock: Arc<dyn ActivationClock> = source.clone();
    let registry = ActivationCancellationRegistry::default();
    let registration = registry
        .register(ActivationId("cleanup-stage".to_owned()))
        .unwrap();
    let token = registration.token();
    let dropped = Arc::new(AtomicBool::new(false));
    let expiry = source.monotonic_now() + Duration::from_millis(10);
    let mut running = Box::pin(execution(
        PendingReport(dropped.clone()),
        &token,
        Some(expiry),
        &clock,
        Duration::from_millis(5),
    ));
    assert!(poll(running.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(11)).await;
    assert!(poll(running.as_mut()).is_pending());
    assert!(!dropped.load(Ordering::SeqCst));
    assert_eq!(source.observer.snapshot().live, 0);
    tokio::time::advance(Duration::from_millis(6)).await;
    let Poll::Ready(report) = poll(running.as_mut()) else {
        panic!("cleanup grace must finish");
    };
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert!(matches!(
        report.cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
    assert!(dropped.load(Ordering::SeqCst));
    let observed = source.observer.snapshot();
    assert_eq!(
        (observed.armed, observed.completed, observed.dropped),
        (1, 1, 0)
    );
}
