use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier, Mutex, Weak};
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use crate::test_support::coordination::{with_watchdog, PollProbe, Rendezvous, Stage, WATCHDOG};
use crate::test_support::{block_on, TestClock};
use crate::ActivationClock;

use super::*;

fn fixture() -> (NativeCapacityOwner, TestClock, Instant) {
    let clock = TestClock::new(100, Instant::now(), 1);
    let owner = NativeCapacityOwner::with_clock(limits(), Arc::new(clock.clone())).unwrap();
    let deadline = clock.monotonic_now() + Duration::from_secs(10);
    (owner, clock, deadline)
}

fn limits() -> NativeCapacityLimits {
    NativeCapacityLimits {
        ordinary: NativeCapacityPartition {
            slots: 2,
            bytes: 10_000,
            maximum_reservation_bytes: 8_000,
        },
        recovery: NativeCapacityPartition {
            slots: 1,
            bytes: 4_000,
            maximum_reservation_bytes: 4_000,
        },
        maximum_lifetime: Duration::from_secs(30),
    }
}

fn request() -> NativeReservationRequest {
    NativeReservationRequest {
        request_bytes: 128,
        work_bytes: 512,
        response_bytes: 1_024,
    }
}

#[test]
fn paired_existing_reservations_keep_capacity_and_both_original_deadlines() {
    let (owner, clock, deadline) = fixture();
    let ordinary = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let recovery_deadline = deadline.checked_sub(Duration::from_secs(5)).unwrap();
    let recovery = owner
        .reserve(NativeAdmissionClass::Recovery, request(), recovery_deadline)
        .unwrap();
    let before = owner.snapshot().unwrap();
    ordinary
        .with_live_pair_until(&recovery, deadline, || ())
        .unwrap();
    ordinary
        .with_live_pair_until(&ordinary, deadline, || ())
        .unwrap();
    assert_eq!(owner.snapshot().unwrap(), before);
    clock.advance(Duration::from_secs(5));
    ordinary.with_live(|| ()).unwrap();
    assert_eq!(
        ordinary.with_live_pair_until(&recovery, deadline, || panic!(
            "expired other reservation accepted"
        )),
        Err(NativeCapacityError::DeadlineExceeded)
    );
    assert_eq!(owner.snapshot().unwrap(), before);
    drop((ordinary, recovery));
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn paired_reservations_refuse_foreign_owner_and_either_closed_partition() {
    let (owner, _, deadline) = fixture();
    let ordinary = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let recovery = owner
        .reserve(NativeAdmissionClass::Recovery, request(), deadline)
        .unwrap();
    let (foreign, _, foreign_deadline) = fixture();
    let other = foreign
        .reserve(NativeAdmissionClass::Recovery, request(), foreign_deadline)
        .unwrap();
    assert_eq!(
        ordinary.with_live_pair_until(&other, deadline, || panic!("foreign native owner accepted")),
        Err(NativeCapacityError::InvalidRequest)
    );
    owner.close_ordinary();
    recovery.with_live(|| ()).unwrap();
    assert_eq!(
        recovery.with_live_pair_until(&ordinary, deadline, || panic!(
            "closed other reservation accepted"
        )),
        Err(NativeCapacityError::AdmissionClosed)
    );
    drop((ordinary, recovery, other));
    assert!(owner.snapshot().unwrap().physically_retired());
    assert!(foreign.snapshot().unwrap().physically_retired());
}

#[test]
fn panicked_paired_acceptance_retains_both_real_capacity_owners_and_fails_closed() {
    let (owner, _, deadline) = fixture();
    let ordinary = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let recovery = owner
        .reserve(NativeAdmissionClass::Recovery, request(), deadline)
        .unwrap();
    let frame = ordinary
        .allocate_bytes(NativeBufferClass::Response, 1024)
        .unwrap();
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = recovery.with_live_pair_until(&ordinary, deadline, || {
            panic!("paired host acceptance failed")
        });
    }))
    .is_err());
    assert_eq!(
        ordinary.with_live(|| ()),
        Err(NativeCapacityError::Poisoned)
    );
    drop((ordinary, recovery));
    owner.close();
    let retained = owner.0.lock_physical().snapshot();
    assert!(retained.quarantined);
    assert_eq!(retained.ordinary.slots, 1);
    assert_eq!(retained.recovery.slots, 0);
    drop(frame);
    let retired = owner.0.lock_physical().report(false);
    assert!(!retired.clean && retired.snapshot.physically_retired());
}

fn wait<T>(future: impl std::future::Future<Output = T>) -> T {
    block_on(with_watchdog(WATCHDOG, future))
}

// Dropping a safe executor waker can run application-owned destructors. A
// destructor may inspect this same capacity owner, so it must run unlocked.
struct InspectingWake {
    owner: NativeCapacityOwner,
    drops: Arc<std::sync::atomic::AtomicUsize>,
    locked_drops: Arc<std::sync::atomic::AtomicUsize>,
}

impl std::task::Wake for InspectingWake {
    fn wake(self: Arc<Self>) {}
}

impl Drop for InspectingWake {
    fn drop(&mut self) {
        use std::sync::atomic::Ordering;
        if self.owner.0.state.try_lock().is_err() {
            self.locked_drops.fetch_add(1, Ordering::SeqCst);
        }
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn drain_waker_destruction_runs_outside_the_capacity_lock() {
    use std::future::Future;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::task::{Context, Waker};

    let mut locked_modes = Vec::new();
    for mode in ["replace", "detach", "finish"] {
        let (owner, _, deadline) = fixture();
        let reservation = owner
            .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
            .unwrap();
        let mut drain = Box::pin(owner.drain_async(deadline, std::future::pending()).unwrap());
        let drops = Arc::new(AtomicUsize::new(0));
        let locked_drops = Arc::new(AtomicUsize::new(0));
        let waker = Waker::from(Arc::new(InspectingWake {
            owner: owner.clone(),
            drops: Arc::clone(&drops),
            locked_drops: Arc::clone(&locked_drops),
        }));
        assert!(drain
            .as_mut()
            .poll(&mut Context::from_waker(&waker))
            .is_pending());
        drop(waker); // the registered waker is the only remaining owner

        match mode {
            "replace" => {
                assert!(drain
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop()))
                    .is_pending());
                drop(drain);
                drop(reservation);
            }
            "detach" => {
                drop(drain);
                drop(reservation);
            }
            "finish" => {
                drop(reservation);
                assert!(drain
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop()))
                    .is_ready());
                drop(drain);
            }
            _ => unreachable!(),
        }
        assert_eq!(drops.load(Ordering::SeqCst), 1, "{mode}");
        if locked_drops.load(Ordering::SeqCst) != 0 {
            locked_modes.push(mode);
        }
    }
    assert!(
        locked_modes.is_empty(),
        "waker dropped under lock: {locked_modes:?}"
    );
}

#[test]
fn replacing_a_waker_can_release_the_last_reservation_and_wake_the_replacement() {
    use std::future::Future;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::task::{Context, Wake, Waker};

    struct ReleaseOnDrop {
        _reservation: NativeReservation,
    }
    impl Wake for ReleaseOnDrop {
        fn wake(self: Arc<Self>) {}
    }
    struct CountWakes(AtomicUsize);
    impl Wake for CountWakes {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    let (owner, _, deadline) = fixture();
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let mut drain = Box::pin(owner.drain_async(deadline, std::future::pending()).unwrap());
    let first = Waker::from(Arc::new(ReleaseOnDrop {
        _reservation: reservation,
    }));
    assert!(drain
        .as_mut()
        .poll(&mut Context::from_waker(&first))
        .is_pending());
    drop(first);

    let wakes = Arc::new(CountWakes(AtomicUsize::new(0)));
    let replacement = Waker::from(Arc::clone(&wakes));
    assert!(drain
        .as_mut()
        .poll(&mut Context::from_waker(&replacement))
        .is_pending());
    assert_eq!(wakes.0.load(Ordering::SeqCst), 1);
    assert!(matches!(
        drain.as_mut().poll(&mut Context::from_waker(&replacement)),
        std::task::Poll::Ready(report) if report.clean && report.snapshot.physically_retired()
    ));
}

#[test]
fn delayed_old_wake_cannot_remove_a_new_drain_waiter() {
    use std::future::Future;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::task::{Context, Wake, Waker};

    struct DelayedWake {
        entered: mpsc::SyncSender<()>,
        release: std::sync::Mutex<mpsc::Receiver<()>>,
    }
    impl Wake for DelayedWake {
        fn wake(self: Arc<Self>) {
            self.entered.send(()).unwrap();
            self.release.lock().unwrap().recv_timeout(WATCHDOG).unwrap();
        }
    }
    struct CountWakes(AtomicUsize);
    impl Wake for CountWakes {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    let (owner, _, deadline) = fixture();
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let mut first = Box::pin(owner.drain_async(deadline, std::future::pending()).unwrap());
    let (entered_tx, entered_rx) = mpsc::sync_channel(1);
    let (release_tx, release_rx) = mpsc::sync_channel(1);
    let old_waker = Waker::from(Arc::new(DelayedWake {
        entered: entered_tx,
        release: std::sync::Mutex::new(release_rx),
    }));
    assert!(first
        .as_mut()
        .poll(&mut Context::from_waker(&old_waker))
        .is_pending());
    let other_owner = owner.clone();
    let waking = std::thread::spawn(move || other_owner.close_ordinary());
    entered_rx.recv_timeout(WATCHDOG).unwrap();

    assert!(first
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    drop(first);
    let mut second = Box::pin(owner.drain_async(deadline, std::future::pending()).unwrap());
    let wakes = Arc::new(CountWakes(AtomicUsize::new(0)));
    let new_waker = Waker::from(Arc::clone(&wakes));
    assert!(second
        .as_mut()
        .poll(&mut Context::from_waker(&new_waker))
        .is_pending());
    release_tx.send(()).unwrap();
    waking.join().unwrap();
    assert_eq!(wakes.0.load(Ordering::SeqCst), 0);

    drop(reservation);
    assert_eq!(wakes.0.load(Ordering::SeqCst), 1);
    assert!(matches!(
        second.as_mut().poll(&mut Context::from_waker(&new_waker)),
        std::task::Poll::Ready(report) if report.clean && report.snapshot.physically_retired()
    ));
}

#[test]
fn ordinary_slot_and_bytes_pressure_preserve_actual_reserved_recovery_capacity() {
    for pressure in [
        NativeCapacityError::SlotsFull,
        NativeCapacityError::BytesFull,
    ] {
        let clock = TestClock::new(100, Instant::now(), 1);
        let mut config = limits();
        if pressure == NativeCapacityError::BytesFull {
            config.ordinary.bytes = 8_000;
        }
        let owner = NativeCapacityOwner::with_clock(config, Arc::new(clock.clone())).unwrap();
        let deadline = clock.monotonic_now() + Duration::from_secs(10);
        let first = owner
            .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
            .unwrap();
        let alias = owner.clone();
        let foreign = NativeCapacityOwner::with_clock(limits(), Arc::new(clock.clone())).unwrap();
        assert!(first.is_from_owner(&owner));
        assert!(first.is_from_owner(&alias));
        assert!(!first.is_from_owner(&foreign));
        let second = if pressure == NativeCapacityError::SlotsFull {
            Some(
                owner
                    .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
                    .unwrap(),
            )
        } else {
            None
        };
        let extra = if pressure == NativeCapacityError::BytesFull {
            NativeReservationRequest {
                work_bytes: 3_000,
                ..request()
            }
        } else {
            request()
        };
        assert!(
            matches!(owner.reserve(NativeAdmissionClass::Ordinary, extra, deadline), Err(actual) if actual == pressure)
        );
        let recovery = owner
            .reserve(NativeAdmissionClass::Recovery, request(), deadline)
            .unwrap();
        assert!(recovery.is_from_owner(&alias));
        assert!(!recovery.is_from_owner(&foreign));
        assert_eq!(recovery.response_bytes(), 1_024);
        assert_eq!(
            recovery.reserved_bytes(),
            1_664 + NATIVE_RESERVATION_METADATA_BYTES
        );
        let mut response = recovery
            .allocate_bytes(NativeBufferClass::Response, 1_024)
            .unwrap();
        response.as_mut_slice()[0] = 42;
        drop(recovery);
        assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
        assert_eq!(response.get()[0], 42);
        assert!(matches!(
            owner.reserve(NativeAdmissionClass::Recovery, request(), deadline),
            Err(NativeCapacityError::SlotsFull)
        ));
        drop(response);
        drop(first);
        drop(second);
        assert!(owner.snapshot().unwrap().physically_retired());
    }
}

#[test]
fn bounded_buffer_parts_and_shells_cannot_borrow_or_duplicate_native_capacity() {
    let (owner, _, deadline) = fixture();
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let request_buffer = reservation
        .allocate_bytes(NativeBufferClass::Request, 128)
        .unwrap();
    assert!(matches!(
        reservation.reserve_buffer(NativeBufferClass::Request, 1),
        Err(NativeCapacityError::BufferTooLarge)
    ));
    let mut shells = Vec::new();
    for _ in 1..MAXIMUM_NATIVE_BUFFER_GUARDS {
        shells.push(
            reservation
                .reserve_buffer(NativeBufferClass::Work, 0)
                .unwrap(),
        );
    }
    assert!(matches!(
        reservation.reserve_buffer(NativeBufferClass::Response, 0),
        Err(NativeCapacityError::BufferLimit)
    ));
    drop(shells);
    let response = reservation
        .allocate_bytes(NativeBufferClass::Response, 1_024)
        .unwrap();
    assert!(matches!(
        reservation.reserve_buffer(NativeBufferClass::Response, 1),
        Err(NativeCapacityError::BufferTooLarge)
    ));
    drop(reservation);
    drop(request_buffer);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    drop(response);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn overflow_invalid_deadline_and_size_reject_before_any_native_owner_is_created() {
    let (owner, clock, deadline) = fixture();
    for (request, time, expected) in [
        (
            NativeReservationRequest {
                request_bytes: u64::MAX,
                ..request()
            },
            deadline,
            NativeCapacityError::InvalidRequest,
        ),
        (
            request(),
            clock.monotonic_now(),
            NativeCapacityError::DeadlineExceeded,
        ),
        (
            request(),
            deadline + Duration::from_secs(30),
            NativeCapacityError::DeadlineTooLong,
        ),
        (
            NativeReservationRequest {
                work_bytes: 8_000,
                ..request()
            },
            deadline,
            NativeCapacityError::ReservationTooLarge,
        ),
    ] {
        assert!(
            matches!(owner.reserve(NativeAdmissionClass::Ordinary, request, time), Err(actual) if actual == expected)
        );
        assert!(owner.snapshot().unwrap().physically_retired());
    }
    let mut config = limits();
    config.recovery.maximum_reservation_bytes = NATIVE_RESERVATION_METADATA_BYTES - 1;
    assert!(matches!(
        NativeCapacityOwner::new(config),
        Err(NativeCapacityError::InvalidLimits)
    ));
}

#[test]
fn original_monotonic_deadline_and_close_fence_never_refund_retained_response_bytes() {
    let (owner, clock, deadline) = fixture();
    let ordinary = Arc::new(
        owner
            .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
            .unwrap(),
    );
    let response = Arc::clone(&ordinary);
    let frame = ordinary
        .allocate_bytes(NativeBufferClass::Response, 1_024)
        .unwrap();
    clock.set_wall_unix_millis(u64::MAX);
    ordinary.with_live(|| ()).unwrap();
    owner.close_ordinary();
    assert!(matches!(
        ordinary.with_live(|| panic!("closed ordinary action ran")),
        Err(NativeCapacityError::AdmissionClosed)
    ));
    let recovery = owner
        .reserve(NativeAdmissionClass::Recovery, request(), deadline)
        .unwrap();
    recovery.with_live(|| ()).unwrap();
    clock.advance(Duration::from_secs(10));
    assert!(matches!(
        recovery.with_live(|| panic!("expired recovery action ran")),
        Err(NativeCapacityError::DeadlineExceeded)
    ));
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(ordinary);
    drop(response);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    drop(frame);
    drop(recovery);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn linked_expiry_fences_delivery_without_renewing_or_refunding_original_frames() {
    let (owner, clock, deadline) = fixture();
    let reservation = Arc::new(
        owner
            .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
            .unwrap(),
    );
    let expiry = reservation.monotonic_now() + Duration::from_millis(5);
    let frame = reservation
        .allocate_bytes(NativeBufferClass::Response, 1024)
        .unwrap();
    reservation.with_live_until(expiry, || ()).unwrap();
    clock.advance(Duration::from_millis(5));
    reservation.with_live(|| ()).unwrap();
    assert!(matches!(
        reservation.with_live_until(expiry, || panic!("expired linked payload")),
        Err(NativeCapacityError::DeadlineExceeded)
    ));
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    clock.advance(Duration::from_secs(10));
    assert!(matches!(
        reservation.with_live_until(deadline + Duration::from_secs(10), || panic!(
            "original reservation renewed"
        )),
        Err(NativeCapacityError::DeadlineExceeded)
    ));
    drop(reservation);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    drop(frame);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn concurrent_aliases_have_one_global_native_limit_and_no_recovery_permit_loan() {
    let (owner, _, deadline) = fixture();
    assert!(owner.is_same_owner(&owner.clone()));
    assert!(!owner.is_same_owner(&NativeCapacityOwner::new(limits()).unwrap()));
    let barrier = Arc::new(Barrier::new(9));
    let (notice, receiver) = mpsc::channel();
    let mut workers = Vec::new();
    for _ in 0..8 {
        let owner = owner.clone();
        let barrier = Arc::clone(&barrier);
        let notice = notice.clone();
        workers.push(std::thread::spawn(move || {
            let admission = owner.reserve(NativeAdmissionClass::Ordinary, request(), deadline);
            notice.send(admission.is_ok()).unwrap();
            barrier.wait();
            drop(admission);
        }));
    }
    let accepted = (0..8)
        .map(|_| usize::from(receiver.recv_timeout(WATCHDOG).unwrap()))
        .sum::<usize>();
    assert_eq!(accepted, 2);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 2);
    let recovery = owner
        .reserve(NativeAdmissionClass::Recovery, request(), deadline)
        .unwrap();
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    barrier.wait();
    for worker in workers {
        worker.join().unwrap();
    }
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 0);
    drop(recovery);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn dropped_waiter_and_paused_actual_buffer_destructor_cannot_publish_physical_retirement() {
    struct Physical {
        pause: Rendezvous,
        notice: mpsc::Sender<crate::test_support::coordination::PauseTicket>,
    }
    impl Drop for Physical {
        fn drop(&mut self) {
            let (registration, mut buffer) = self.pause.track(vec![0_u8; 512]).unwrap();
            buffer.commit(Stage::Entered).unwrap();
            let mut parked = Box::pin(buffer.pause());
            PollProbe::default().pending(parked.as_mut());
            self.notice
                .send(self.pause.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(parked);
        }
    }
    let (owner, clock, original) = fixture();
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), original)
        .unwrap();
    let pause = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let physical = reservation
        .reserve_buffer(NativeBufferClass::Work, 512)
        .unwrap()
        .attach(Physical {
            pause: pause.clone(),
            notice,
        });
    drop(reservation); // Detached waiter; the actual worker buffer remains original.
    let cleanup = std::thread::spawn(move || drop(physical));
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let cutoff = clock.monotonic_now() + Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(cutoff, clock.sleep_until(cutoff))
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    clock.advance(Duration::from_secs(1));
    let report = wait(drain);
    assert!(!report.clean && !report.snapshot.physically_retired());
    assert!(matches!(
        owner.reserve(NativeAdmissionClass::Recovery, request(), original),
        Err(NativeCapacityError::Quarantined)
    ));
    pause.release(ticket).unwrap();
    cleanup.join().unwrap();
    let late = wait(owner.drain_async(original, std::future::pending()).unwrap());
    assert!(!late.clean && late.snapshot.physically_retired());
}

struct CheckingClock {
    inner: TestClock,
    owner: Mutex<Weak<Owner>>,
    locked_calls: AtomicUsize,
}
impl ActivationClock for CheckingClock {
    fn sample(&self) -> crate::ClockSample {
        self.inner.sample()
    }
    fn monotonic_now(&self) -> Instant {
        if let Some(owner) = self.owner.lock().unwrap().upgrade() {
            let locked = usize::from(owner.state.try_lock().is_err());
            self.locked_calls.fetch_add(locked, Ordering::SeqCst);
        }
        self.inner.monotonic_now()
    }
}
struct InspectTimerDrop {
    owner: NativeCapacityOwner,
    dropped_unlocked: Arc<AtomicBool>,
}
impl Future for InspectTimerDrop {
    type Output = ();
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        panic!("rejected timer must not be polled")
    }
}
impl Drop for InspectTimerDrop {
    fn drop(&mut self) {
        self.dropped_unlocked
            .store(self.owner.0.state.try_lock().is_ok(), Ordering::SeqCst);
    }
}

#[test]
fn single_drain_waiter_detachment_does_not_extend_original_native_buffer_cutoff() {
    let clock = TestClock::new(100, Instant::now(), 1);
    let checking_clock = Arc::new(CheckingClock {
        inner: clock.clone(),
        owner: Mutex::new(Weak::new()),
        locked_calls: AtomicUsize::new(0),
    });
    let owner = NativeCapacityOwner::with_clock(limits(), checking_clock.clone()).unwrap();
    *checking_clock.owner.lock().unwrap() = Arc::downgrade(&owner.0);
    let original = clock.monotonic_now() + Duration::from_secs(10);
    let response = owner
        .reserve(NativeAdmissionClass::Recovery, request(), original)
        .unwrap();
    checking_clock.locked_calls.store(0, Ordering::SeqCst);
    assert_eq!(owner.drain_deadline(original).unwrap(), original);
    let cutoff = clock.monotonic_now() + Duration::from_secs(1);
    let drain = owner
        .drain_async(cutoff, clock.sleep_until(cutoff))
        .unwrap();
    assert!(matches!(
        owner.drain_async(original, std::future::pending()),
        Err(NativeCapacityError::DrainWaiterBusy)
    ));
    drop(drain);

    let before = {
        let state = owner.0.state.lock().unwrap();
        (state.next_waiter, state.shutdown_deadline, state.snapshot())
    };
    let dropped_unlocked = Arc::new(AtomicBool::new(false));
    assert!(matches!(
        owner.drain_async(
            original,
            InspectTimerDrop {
                owner: owner.clone(),
                dropped_unlocked: Arc::clone(&dropped_unlocked),
            },
        ),
        Err(NativeCapacityError::DeadlineTooLong)
    ));
    assert!(dropped_unlocked.load(Ordering::SeqCst));
    {
        let state = owner.0.state.lock().unwrap();
        assert_eq!(
            (state.next_waiter, state.shutdown_deadline, state.snapshot()),
            before
        );
        assert!(state.waiter.is_none());
    }
    assert_eq!(owner.drain_deadline(original).unwrap(), cutoff);
    assert_eq!(clock.pending_waiters(), 0);

    // An intervening waiter can shorten the cutoff after a caller observes it.
    // Its stale later timer must be rejected, and a retry uses the new cutoff.
    let observed_cutoff = owner.drain_deadline(original).unwrap();
    let earlier = clock.monotonic_now() + Duration::from_millis(500);
    let contender_owner = owner.clone();
    let contender_clock = clock.clone();
    let (ready_tx, ready_rx) = mpsc::sync_channel(1);
    let contender = std::thread::spawn(move || {
        let intervening = contender_owner
            .drain_async(earlier, contender_clock.sleep_until(earlier))
            .unwrap();
        drop(intervening);
        ready_tx.send(()).unwrap();
    });
    ready_rx.recv_timeout(WATCHDOG).unwrap();
    contender.join().unwrap();
    let before_retry = {
        let state = owner.0.state.lock().unwrap();
        (state.next_waiter, state.shutdown_deadline, state.snapshot())
    };
    assert!(matches!(
        owner.drain_async(observed_cutoff, clock.sleep_until(observed_cutoff)),
        Err(NativeCapacityError::DeadlineTooLong)
    ));
    {
        let state = owner.0.state.lock().unwrap();
        assert_eq!(
            (state.next_waiter, state.shutdown_deadline, state.snapshot()),
            before_retry
        );
        assert!(state.waiter.is_none());
    }
    assert_eq!(owner.drain_deadline(original).unwrap(), earlier);
    let mut replacement = Box::pin(
        owner
            .drain_async(earlier, clock.sleep_until(earlier))
            .unwrap(),
    );
    let wake = PollProbe::default();
    wake.pending(replacement.as_mut());
    assert_eq!(clock.pending_waiters(), 1);
    clock.advance(Duration::from_millis(500));
    assert!(
        wake.wakes() > 0,
        "original drain cutoff did not wake replacement"
    );
    let report = wake.ready(replacement.as_mut());
    assert!(!report.clean && report.snapshot.recovery.slots == 1);
    assert_eq!(checking_clock.locked_calls.load(Ordering::SeqCst), 0);
    drop(response);
    let retired = wait(owner.drain_async(original, std::future::pending()).unwrap());
    assert!(!retired.clean && retired.snapshot.physically_retired());

    check_immediate_drain_observations();
}

fn check_immediate_drain_observations() {
    // A later timer is harmless when no physical owner remains: polling can
    // report immediately without depending on a timer wake.
    let (empty_owner, empty_clock, empty_original) = fixture();
    let empty_reservation = empty_owner
        .reserve(NativeAdmissionClass::Ordinary, request(), empty_original)
        .unwrap();
    let empty_cutoff = empty_clock.monotonic_now() + Duration::from_secs(1);
    drop(
        empty_owner
            .drain_async(empty_cutoff, empty_clock.sleep_until(empty_cutoff))
            .unwrap(),
    );
    drop(empty_reservation);
    let empty = wait(
        empty_owner
            .drain_async(empty_original, std::future::pending())
            .unwrap(),
    );
    assert!(empty.clean && empty.snapshot.physically_retired());

    // At an already elapsed cutoff, a live owner produces an immediate
    // quarantine report even if the replacement timer itself never wakes.
    let (expired_owner, expired_clock, expired_original) = fixture();
    let expired_reservation = expired_owner
        .reserve(NativeAdmissionClass::Recovery, request(), expired_original)
        .unwrap();
    let expired_cutoff = expired_clock.monotonic_now() + Duration::from_secs(1);
    drop(
        expired_owner
            .drain_async(expired_cutoff, expired_clock.sleep_until(expired_cutoff))
            .unwrap(),
    );
    expired_clock.advance(Duration::from_secs(1));
    let expired = wait(
        expired_owner
            .drain_async(expired_original, std::future::pending())
            .unwrap(),
    );
    assert!(!expired.clean && expired.snapshot.recovery.slots == 1);
    assert!(expired.snapshot.quarantined);
    drop(expired_reservation);
}

#[test]
fn native_response_retires_before_cutoff_even_when_original_drain_polls_later() {
    let (owner, clock, original) = fixture();
    let response = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), original)
        .unwrap();
    let cutoff = clock.monotonic_now() + Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(cutoff, clock.sleep_until(cutoff))
            .unwrap(),
    );
    let wake = PollProbe::default();
    wake.pending(drain.as_mut());
    drop(response);
    assert!(wake.wakes() > 0);
    clock.advance(Duration::from_secs(2));
    let report = wait(drain);
    assert!(report.clean && report.snapshot.physically_retired());
}

#[test]
fn finalized_original_activation_ledger_cannot_refund_live_native_response_frame() {
    use crate::{ActivationBudget, ClockSample, EffectiveActivationBudget, ResourceBudget};
    let (owner, clock, deadline) = fixture();
    let ceiling = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 4_096,
        wall_time_limit_millis: Some(1_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 128,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_at(
        &ceiling,
        &ceiling,
        &ceiling,
        None,
        ClockSample::new(100, clock.monotonic_now()),
    )
    .unwrap();
    let activation = ActivationBudget::new(grant);
    let response = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let frame = response
        .allocate_bytes(NativeBufferClass::Response, 1_024)
        .unwrap();
    drop(response);
    let terminal = activation.finalize_at(None, clock.monotonic_now());
    assert!(activation.finalized().is_some());
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    assert!(owner.snapshot().unwrap().ordinary.bytes >= 1_024);
    assert_eq!(
        activation.finalize_at(None, clock.monotonic_now()),
        terminal
    );
    drop(activation);
    assert_eq!(frame.get().len(), 1_024);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    drop(frame);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn panicked_native_acceptance_fails_closed_without_refunding_original_buffer_owners() {
    let (owner, _, deadline) = fixture();
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request(), deadline)
        .unwrap();
    let frame = reservation
        .allocate_bytes(NativeBufferClass::Response, 1_024)
        .unwrap();
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = reservation.with_live(|| panic!("host acceptance failed"));
    }))
    .is_err());
    assert!(matches!(
        owner.reserve(NativeAdmissionClass::Recovery, request(), deadline),
        Err(NativeCapacityError::Poisoned)
    ));
    assert!(matches!(
        owner.drain_async(deadline, std::future::pending()),
        Err(NativeCapacityError::Poisoned)
    ));
    drop(reservation);
    owner.close();
    let pending = owner.0.lock_physical().snapshot();
    assert!(pending.quarantined && pending.admission_closed);
    assert_eq!(pending.ordinary.slots, 1);
    drop(frame);
    let retired = owner.0.lock_physical().report(false);
    assert!(!retired.clean && retired.snapshot.physically_retired());
}
