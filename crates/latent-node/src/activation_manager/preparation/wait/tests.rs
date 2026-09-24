use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};
use std::time::{Duration, Instant};

use latent_core::{
    ActivationClock, ActivationId, ClockSample, DeadlineWaitObserver, PlatformError,
    PlatformErrorCode,
};
use latent_executor::PreparationReadWait;

use super::*;
use crate::activation_manager::control::stage;
use crate::activation_manager::transport_stop::TransportStop;
use crate::activation_manager::ActivationTransportInterruption;
use crate::ActivationCancellationRegistry;

fn poll<F: Future + ?Sized>(future: Pin<&mut F>) -> Poll<F::Output> {
    future.poll(&mut Context::from_waker(Waker::noop()))
}

struct Clock(DeadlineWaitObserver);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1_000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }
    fn uses_system_monotonic(&self) -> bool {
        true
    }
    fn deadline_wait_observer(&self) -> Option<&DeadlineWaitObserver> {
        Some(&self.0)
    }
}

#[derive(Default)]
struct Counters {
    started: AtomicUsize,
    completed: AtomicUsize,
    dropped: AtomicUsize,
}
struct Owner(Arc<Counters>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.dropped.fetch_add(1, Ordering::Relaxed);
    }
}

fn pending_preparation(
    counters: Arc<Counters>,
    until: Instant,
) -> impl Future<Output = Result<(), PlatformError>> {
    // Capture the owner before polling, just like an affine readiness future.
    let owner = Owner(counters.clone());
    async move {
        let _owner = owner;
        counters.started.fetch_add(1, Ordering::Relaxed);
        Timer.wait_until(until).await;
        counters.completed.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum Stop {
    Cancel,
    Deadline,
    Disconnect,
    TransportDeadline,
}
const STOPS: [Stop; 4] = [
    Stop::Cancel,
    Stop::Deadline,
    Stop::Disconnect,
    Stop::TransportDeadline,
];

fn expected(stop: Stop) -> (PlatformErrorCode, &'static str) {
    match stop {
        Stop::Cancel => (PlatformErrorCode::Cancelled, "original cancellation"),
        Stop::Disconnect => (
            PlatformErrorCode::Cancelled,
            "activation transport disconnected",
        ),
        Stop::Deadline | Stop::TransportDeadline => (
            PlatformErrorCode::DeadlineExceeded,
            "activation deadline exceeded",
        ),
    }
}

#[tokio::test(start_paused = true)]
async fn preparation_timer_uses_one_monotonic_domain_and_never_finishes_early() {
    let initial = Timer.now();
    assert_eq!(initial, tokio::time::Instant::now().into_std());
    let until = initial + Duration::from_millis(20);
    let mut waiting = Timer.wait_until(until);
    assert!(poll(waiting.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(19)).await;
    assert_eq!(Timer.now(), initial + Duration::from_millis(19));
    assert!(poll(waiting.as_mut()).is_pending());
    tokio::time::advance(Duration::from_millis(2)).await;
    assert!(poll(waiting.as_mut()).is_ready());
    assert!(Timer.now() >= until);
}

#[derive(Default)]
struct WakeCount(AtomicUsize);
impl Wake for WakeCount {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
    fn wake_by_ref(self: &Arc<Self>) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

#[tokio::test(start_paused = true)]
async fn dropped_preparation_timer_retires_its_pending_wakeup() {
    let observation = Arc::new(WakeCount::default());
    let waker = Waker::from(observation.clone());
    let mut waiting = Timer.wait_until(Timer.now() + Duration::from_secs(1));
    assert!(waiting
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    drop(waiting);
    let before = observation.0.load(Ordering::Relaxed);
    tokio::time::advance(Duration::from_secs(2)).await;
    tokio::task::yield_now().await;
    assert_eq!(observation.0.load(Ordering::Relaxed), before);
}

#[tokio::test(start_paused = true)]
async fn pending_preparation_wait_keeps_stage_stops_and_drops_owned_work_before_return() {
    for stop in STOPS {
        let source = Arc::new(Clock(DeadlineWaitObserver::new()));
        let clock: Arc<dyn ActivationClock> = source.clone();
        let registration = ActivationCancellationRegistry::default()
            .register(ActivationId("pending-preparation".into()))
            .unwrap();
        let token = registration.token();
        let transport = TransportStop::default();
        let counters = Arc::new(Counters::default());
        let original_deadline = Timer.now() + Duration::from_millis(20);
        let read_deadline = Timer.now() + Duration::from_hours(1);
        let mut future = Box::pin(stage(
            pending_preparation(counters.clone(), read_deadline),
            &token,
            Some(original_deadline),
            &clock,
            &transport,
        ));
        assert!(poll(future.as_mut()).is_pending());
        assert_eq!(counters.started.load(Ordering::Relaxed), 1);
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 0);
        assert_eq!(source.0.snapshot().live, 1);
        match stop {
            Stop::Cancel => assert!(registration.handle().cancel("original cancellation")),
            Stop::Deadline => tokio::time::advance(Duration::from_millis(21)).await,
            Stop::Disconnect => transport.mark(ActivationTransportInterruption::Disconnected),
            Stop::TransportDeadline => {
                transport.mark(ActivationTransportInterruption::DeadlineExceeded);
            }
        }
        let Poll::Ready(Err(error)) = poll(future.as_mut()) else {
            panic!("the original stage stop must interrupt its owned timer");
        };
        let (code, message) = expected(stop);
        assert_eq!(error.code, code);
        assert_eq!(error.message, message);
        assert!(!error.retryable);
        assert!(Timer.now() < read_deadline);
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 1);
        assert_eq!(counters.completed.load(Ordering::Relaxed), 0);
        assert_eq!(source.0.snapshot().live, 0);
        assert_eq!(token.is_cancelled(), matches!(stop, Stop::Cancel));
        drop(future);
        tokio::time::advance(Duration::from_secs(3_601)).await;
        assert_eq!(counters.started.load(Ordering::Relaxed), 1);
        assert_eq!(counters.completed.load(Ordering::Relaxed), 0);
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 1);
    }
}

#[tokio::test(start_paused = true)]
async fn existing_stage_stop_drops_preparation_without_polling_or_arming_its_timer() {
    for stop in STOPS {
        let clock: Arc<dyn ActivationClock> = Arc::new(Clock(DeadlineWaitObserver::new()));
        let registration = ActivationCancellationRegistry::default()
            .register(ActivationId("unpolled-preparation".into()))
            .unwrap();
        let token = registration.token();
        let transport = TransportStop::default();
        match stop {
            Stop::Cancel => assert!(registration.handle().cancel("original cancellation")),
            Stop::Deadline => {}
            Stop::Disconnect => transport.mark(ActivationTransportInterruption::Disconnected),
            Stop::TransportDeadline => {
                transport.mark(ActivationTransportInterruption::DeadlineExceeded);
            }
        }
        let expiry = Timer.now()
            + if matches!(stop, Stop::Deadline) {
                Duration::ZERO
            } else {
                Duration::from_secs(1)
            };
        let counters = Arc::new(Counters::default());
        let mut future = Box::pin(stage(
            pending_preparation(counters.clone(), Timer.now() + Duration::from_hours(1)),
            &token,
            Some(expiry),
            &clock,
            &transport,
        ));
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 0);
        let Poll::Ready(Err(error)) = poll(future.as_mut()) else {
            panic!("a preexisting stop must not enter preparation");
        };
        let (code, message) = expected(stop);
        assert_eq!(error.code, code);
        assert_eq!(error.message, message);
        assert_eq!(counters.started.load(Ordering::Relaxed), 0);
        assert_eq!(counters.completed.load(Ordering::Relaxed), 0);
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 1);
        drop(future);
        assert_eq!(counters.dropped.load(Ordering::Relaxed), 1);
    }
}
