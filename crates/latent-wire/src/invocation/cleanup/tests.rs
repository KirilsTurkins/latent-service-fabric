mod retirement;

use std::future::{pending, Future};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Wake, Waker};
use std::time::Duration;

use latent_core::PlatformErrorCode;
use tokio::runtime::Handle;
use tokio::sync::oneshot;
use tokio::time::Instant;

use super::state::{Phase, Shared, Work};
use super::{ActivationCleanupHandle, ActivationCleanupOwner, Driver};

fn owner(capacity: usize) -> ActivationCleanupOwner {
    ActivationCleanupOwner::start(capacity, Duration::from_millis(10), &Handle::current()).unwrap()
}

fn work(future: impl Future<Output = ()> + Send + 'static) -> Work {
    Work {
        future: Box::pin(future),
        deadline: Instant::now() + Duration::from_millis(20),
    }
}

struct DropProbe {
    port: ActivationCleanupHandle,
    dropped: Arc<AtomicUsize>,
    panic: bool,
}

impl Drop for DropProbe {
    fn drop(&mut self) {
        // The original slot must remain charged while a native destructor
        // reenters. A table lock or premature refund breaks this assertion.
        assert!(self.port.try_reserve().is_err());
        self.dropped.fetch_add(1, Ordering::SeqCst);
        assert!(!self.panic, "fixture destructor panic");
    }
}

#[tokio::test(start_paused = true)]
async fn bounded_slots_refund_and_closing_waits_for_reserved_rpc() {
    let owner = owner(2);
    let port = owner.handle();
    let first = port.try_reserve().unwrap();
    let second = port.try_reserve().unwrap();
    assert_eq!(
        port.try_reserve().err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(first);
    let replacement = port.try_reserve().unwrap();
    owner.stop_accepting();
    assert_eq!(
        port.try_reserve().err().unwrap().code,
        PlatformErrorCode::Unavailable
    );
    tokio::task::yield_now().await;
    assert!(port.snapshot().driver_alive);
    drop(second);
    tokio::task::yield_now().await;
    assert!(port.snapshot().driver_alive);
    drop(replacement);
    let final_state = owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert!(final_state.driver_joined);
    assert!(!final_state.driver_alive);
    assert_eq!(final_state.reserved, 0);
    assert_eq!(final_state.handoffs, 0);
}

#[tokio::test(start_paused = true)]
async fn reserved_slot_can_handoff_after_close_and_destructs_before_refund() {
    let owner = owner(1);
    let port = owner.handle();
    let slot = port.try_reserve().unwrap();
    let dropped = Arc::new(AtomicUsize::new(0));
    let probe = DropProbe {
        port: port.clone(),
        dropped: dropped.clone(),
        panic: false,
    };
    owner.stop_accepting();
    tokio::task::yield_now().await;
    assert!(port.snapshot().driver_alive);
    slot.transfer(work(async move {
        drop(probe);
    }));
    let snapshot = owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert_eq!(snapshot.handoffs, 1);
    assert_eq!(snapshot.completed, 1);
    assert_eq!(snapshot.reserved + snapshot.queued + snapshot.running, 0);
}

#[tokio::test(start_paused = true)]
async fn ready_destructor_sees_charged_slot_while_admission_is_open() {
    let owner = owner(1);
    let port = owner.handle();
    let dropped = Arc::new(AtomicUsize::new(0));
    let probe = DropProbe {
        port: port.clone(),
        dropped: dropped.clone(),
        panic: false,
    };
    port.try_reserve().unwrap().transfer(work(async move {
        drop(probe);
    }));
    tokio::task::yield_now().await;
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    drop(port.try_reserve().expect("slot refunded after destruction"));
    owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test(start_paused = true)]
async fn abort_before_first_poll_drains_queue_and_handles_late_reservation() {
    let mut owner = owner(2);
    let port = owner.handle();
    let queued = port.try_reserve().unwrap();
    let late = port.try_reserve().unwrap();
    let dropped = Arc::new(AtomicUsize::new(0));
    let probe = DropProbe {
        port: port.clone(),
        dropped: dropped.clone(),
        panic: false,
    };
    queued.transfer(work(async move {
        let _probe = probe;
        pending::<()>().await;
    }));
    // No yield has occurred: the concrete driver guard exists outside its poll.
    owner.task.as_ref().unwrap().abort();
    let _ = owner.task.as_mut().unwrap().await;
    owner.task.take();
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert!(!port.snapshot().driver_alive);
    let late_probe = DropProbe {
        port: port.clone(),
        dropped: dropped.clone(),
        panic: false,
    };
    late.transfer(work(async move {
        let _probe = late_probe;
        pending::<()>().await;
    }));
    let snapshot = port.snapshot();
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
    assert_eq!(snapshot.handoffs, 2);
    assert_eq!(snapshot.fallbacks, 2);
    assert_eq!(snapshot.reserved + snapshot.queued + snapshot.running, 0);
    assert!(snapshot.failed);
    assert!(
        !snapshot.driver_joined,
        "aborting a raw join is not owner shutdown"
    );
}

#[tokio::test(start_paused = true)]
async fn absolute_handoff_timeout_drops_owner_and_records_failure() {
    let owner = owner(1);
    let port = owner.handle();
    let dropped = Arc::new(AtomicUsize::new(0));
    let probe = DropProbe {
        port: port.clone(),
        dropped: dropped.clone(),
        panic: false,
    };
    port.try_reserve().unwrap().transfer(work(async move {
        let _probe = probe;
        pending::<()>().await;
    }));
    tokio::task::yield_now().await;
    assert_eq!(port.snapshot().running, 1);
    tokio::time::advance(Duration::from_millis(21)).await;
    tokio::task::yield_now().await;
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert_eq!(port.snapshot().timed_out, 1);
    assert!(owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .is_err());
    assert!(port.snapshot().driver_joined);
    assert_eq!(port.snapshot().running, 0);
}

#[tokio::test(start_paused = true)]
async fn panicking_poll_or_destructor_does_not_orphan_other_continuations() {
    for destructor in [false, true] {
        let owner = owner(2);
        let port = owner.handle();
        let bad = port.try_reserve().unwrap();
        let good = port.try_reserve().unwrap();
        let dropped = Arc::new(AtomicUsize::new(0));
        let probe = DropProbe {
            port: port.clone(),
            dropped: dropped.clone(),
            panic: destructor,
        };
        bad.transfer(work(async move {
            if destructor {
                drop(probe);
            } else {
                let _probe = probe;
                panic!("fixture poll panic");
            }
        }));
        let (sent, received) = oneshot::channel();
        good.transfer(work(async move {
            let _ = sent.send(());
        }));
        assert!(owner
            .shutdown(Instant::now() + Duration::from_secs(1))
            .await
            .is_err());
        received.await.unwrap();
        let snapshot = port.snapshot();
        assert_eq!(snapshot.panicked, 1);
        assert_eq!(snapshot.completed, 1);
        assert_eq!(snapshot.handoffs, 2);
        assert_eq!(snapshot.queued + snapshot.running, 0);
        assert!(snapshot.driver_joined);
    }
}

#[tokio::test(start_paused = true)]
async fn shutdown_timeout_aborts_and_joins_before_returning() {
    let owner = owner(1);
    let port = owner.handle();
    port.try_reserve().unwrap().transfer(work(pending()));
    assert!(owner.shutdown(Instant::now()).await.is_err());
    let snapshot = port.snapshot();
    assert!(snapshot.driver_joined);
    assert!(!snapshot.driver_alive);
    assert_eq!(snapshot.queued + snapshot.running, 0);
    assert_eq!(snapshot.fallbacks, 1);
}

struct ReentrantWake {
    shared: Arc<Shared>,
    woken: AtomicBool,
}
impl Wake for ReentrantWake {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }
    fn wake_by_ref(self: &Arc<Self>) {
        let _snapshot = self.shared.snapshot();
        self.woken.store(true, Ordering::SeqCst);
    }
}

#[tokio::test(start_paused = true)]
async fn queue_wakes_outside_lock_and_each_poll_has_a_finite_initial_batch() {
    let shared = Arc::new(Shared::new(1, Duration::from_millis(20)));
    let mut driver = Driver::new(shared.clone(), 1);
    let wake = Arc::new(ReentrantWake {
        shared: shared.clone(),
        woken: AtomicBool::new(false),
    });
    let waker = Waker::from(wake.clone());
    let mut context = Context::from_waker(&waker);
    assert!(Pin::new(&mut driver).poll(&mut context).is_pending());
    shared.reserve().unwrap().transfer(work(async {}));
    assert!(wake.woken.load(Ordering::SeqCst));
    assert!(Pin::new(&mut driver).poll(&mut context).is_pending());
    assert_eq!(shared.snapshot().completed, 1);
    let slot = shared.reserve().unwrap();
    shared.close();
    assert!(Pin::new(&mut driver).poll(&mut context).is_pending());
    wake.woken.store(false, Ordering::SeqCst);
    drop(slot);
    assert!(wake.woken.load(Ordering::SeqCst));
    assert!(Pin::new(&mut driver).poll(&mut context).is_ready());
}

#[tokio::test(start_paused = true)]
async fn generation_exhaustion_fails_closed_without_wrapping() {
    let owner = owner(1);
    let port = owner.handle();
    {
        let mut state = port.shared.lock();
        state.slots[0].generation = u64::MAX;
        assert_eq!(state.slots[0].phase, Phase::Free);
    }
    assert_eq!(
        port.try_reserve().err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(port.shared.lock().slots[0].generation, u64::MAX);
    assert!(owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .is_err());
    assert!(port.snapshot().driver_joined);
}
