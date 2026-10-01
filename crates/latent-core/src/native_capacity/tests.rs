use std::sync::{mpsc, Arc, Barrier};
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

fn wait<T>(future: impl std::future::Future<Output = T>) -> T {
    block_on(with_watchdog(WATCHDOG, future))
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

#[test]
fn single_drain_waiter_detachment_does_not_extend_original_native_buffer_cutoff() {
    let (owner, clock, original) = fixture();
    let response = owner
        .reserve(NativeAdmissionClass::Recovery, request(), original)
        .unwrap();
    let cutoff = clock.monotonic_now() + Duration::from_secs(1);
    let drain = owner
        .drain_async(cutoff, clock.sleep_until(cutoff))
        .unwrap();
    assert!(matches!(
        owner.drain_async(original, std::future::pending()),
        Err(NativeCapacityError::DrainWaiterBusy)
    ));
    drop(drain);
    clock.advance(Duration::from_secs(2));
    let report = wait(owner.drain_async(original, std::future::pending()).unwrap());
    assert!(!report.clean && report.snapshot.recovery.slots == 1);
    drop(response);
    let retired = wait(owner.drain_async(original, std::future::pending()).unwrap());
    assert!(!retired.clean && retired.snapshot.physically_retired());
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
