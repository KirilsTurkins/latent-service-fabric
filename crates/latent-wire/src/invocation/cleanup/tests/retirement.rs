//! Retirement witnesses cover destruction, not merely a ready poll or join.
use std::future::{pending, Future};
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};
use std::time::Duration;

use tokio::sync::oneshot;
use tokio::time::Instant;

use super::{owner, ActivationCleanupOwner, Driver, Shared, Work};

struct PanickingWakerDrop(Arc<AtomicUsize>);

#[expect(
    clippy::manual_noop_waker,
    reason = "The custom final waker destructor deliberately panics to test owner retirement."
)]
impl Wake for PanickingWakerDrop {
    fn wake(self: Arc<Self>) {}
}

impl Drop for PanickingWakerDrop {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::SeqCst);
        panic!("stored driver waker destructor panic");
    }
}

struct ChargedOwner {
    shared: Arc<Shared>,
    destroyed: Arc<AtomicUsize>,
}

impl Drop for ChargedOwner {
    fn drop(&mut self) {
        let snapshot = self.shared.snapshot();
        assert_eq!(snapshot.reserved + snapshot.queued + snapshot.running, 1);
        self.destroyed.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test(start_paused = true)]
async fn panicking_stored_waker_drop_cannot_skip_a_self_retaining_queued_owner() {
    let shared = Arc::new(Shared::new(1, Duration::from_millis(20)));
    let mut driver = Driver::new(shared.clone(), 1);
    let waker_drops = Arc::new(AtomicUsize::new(0));
    let waker = Waker::from(Arc::new(PanickingWakerDrop(waker_drops.clone())));
    assert!(Pin::new(&mut driver)
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    drop(waker);

    // Park only the saved waker while setting up queued work, so its final
    // destructor is exercised by Driver::drop, not the transfer's wake path.
    let saved = shared.lock().waker.take();
    let destroyed = Arc::new(AtomicUsize::new(0));
    let owner = ChargedOwner {
        shared: shared.clone(),
        destroyed: destroyed.clone(),
    };
    shared.reserve().unwrap().transfer(Work {
        future: Box::pin(async move {
            let _owner = owner;
            pending::<()>().await;
        }),
        deadline: Instant::now() + Duration::from_millis(20),
    });
    shared.lock().waker = saved;
    assert_eq!(shared.snapshot().queued, 1);

    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(driver)));
    assert!(
        result.is_ok(),
        "a waker panic must not bypass owner retirement"
    );
    assert_eq!(waker_drops.load(Ordering::SeqCst), 1);
    assert_eq!(destroyed.load(Ordering::SeqCst), 1);
    let snapshot = shared.snapshot();
    assert!(!snapshot.driver_alive);
    assert!(snapshot.failed);
    assert_eq!(snapshot.reserved + snapshot.queued + snapshot.running, 0);
    assert_eq!(snapshot.fallbacks, 1);
    // Without draining the queued future, Shared -> Work -> ChargedOwner ->
    // Shared would keep the table and its lifecycle owner alive permanently.
    assert_eq!(Arc::strong_count(&shared), 1);
}

struct SlowRetirement {
    owner: ChargedOwner,
    slow_poll: bool,
    polled: Arc<AtomicUsize>,
}

impl Future for SlowRetirement {
    type Output = ();

    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        self.polled.fetch_add(1, Ordering::SeqCst);
        if self.slow_poll {
            std::thread::sleep(Duration::from_millis(25));
        }
        Poll::Ready(())
    }
}

impl Drop for SlowRetirement {
    fn drop(&mut self) {
        if !self.slow_poll {
            std::thread::sleep(Duration::from_millis(25));
        }
        // This read observes the real owner before its following field Drop.
        assert_eq!(self.owner.shared.snapshot().running, 1);
    }
}

#[tokio::test]
async fn ready_poll_and_final_destructor_both_count_toward_the_absolute_handoff_cap() {
    for slow_poll in [true, false] {
        let shared = Arc::new(Shared::new(1, Duration::from_millis(20)));
        let mut driver = Driver::new(shared.clone(), 1);
        let destroyed = Arc::new(AtomicUsize::new(0));
        let polled = Arc::new(AtomicUsize::new(0));
        let future = Box::pin(SlowRetirement {
            owner: ChargedOwner {
                shared: shared.clone(),
                destroyed: destroyed.clone(),
            },
            slow_poll,
            polled: polled.clone(),
        });
        let slot = shared.reserve().unwrap();
        let deadline = Instant::now() + Duration::from_millis(20);
        slot.transfer(Work { future, deadline });
        assert!(Pin::new(&mut driver)
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(
            polled.load(Ordering::SeqCst),
            1,
            "exercise a ready poll, not pre-dispatch expiry"
        );
        assert_eq!(destroyed.load(Ordering::SeqCst), 1);
        let snapshot = shared.snapshot();
        assert_eq!(snapshot.completed, 0);
        assert_eq!(snapshot.timed_out, 1);
        assert_eq!(snapshot.running + snapshot.queued + snapshot.reserved, 0);
        assert!(snapshot.failed);
        assert!(shared.lock().last_retired.unwrap() > deadline);
        drop(driver);
    }
}

async fn driver_finished(owner: &ActivationCleanupOwner) {
    for _ in 0..8 {
        if owner.task.as_ref().unwrap().is_finished() {
            return;
        }
        tokio::task::yield_now().await;
    }
    assert!(
        owner.task.as_ref().unwrap().is_finished(),
        "finite ready driver must finish"
    );
}

#[tokio::test(start_paused = true)]
async fn already_ready_join_does_not_hide_retirement_after_the_original_shutdown_cutoff() {
    let owner = owner(1);
    let port = owner.handle();
    let (send, receive) = oneshot::channel();
    let cutoff = Instant::now() + Duration::from_millis(5);
    port.try_reserve().unwrap().transfer(Work {
        future: Box::pin(async move {
            receive.await.unwrap();
        }),
        deadline: Instant::now() + Duration::from_millis(20),
    });
    owner.stop_accepting();
    tokio::task::yield_now().await;
    assert_eq!(port.snapshot().running, 1);
    tokio::time::advance(Duration::from_millis(6)).await;
    send.send(()).unwrap();
    driver_finished(&owner).await;
    assert!(port.shared.lock().last_retired.unwrap() > cutoff);
    // Completion met its own 20 ms allowance. Only the original, shorter
    // shutdown cutoff is violated; polling an already-ready join cannot prove it.
    assert_eq!(port.snapshot().completed, 1);
    assert_eq!(port.snapshot().timed_out, 0);
    assert!(owner.shutdown(cutoff).await.is_err());
    let snapshot = port.snapshot();
    assert!(snapshot.driver_joined);
    assert!(snapshot.failed);
    assert_eq!(snapshot.reserved + snapshot.queued + snapshot.running, 0);
}

#[tokio::test(start_paused = true)]
async fn late_observation_of_an_idle_join_is_not_late_owner_retirement() {
    let owner = owner(1);
    let cutoff = Instant::now();
    let port = owner.handle();
    owner.stop_accepting();
    driver_finished(&owner).await;
    assert_eq!(port.shared.lock().last_retired, None);
    tokio::time::advance(Duration::from_millis(25)).await;
    let snapshot = owner.shutdown(cutoff).await.unwrap();
    assert!(snapshot.driver_joined);
    assert!(!snapshot.failed);
}
