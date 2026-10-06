use super::*;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityError, NativeCapacityOwner, NativeReservation,
    NativeReservationRequest,
};

struct KeptNative {
    pause: Rendezvous,
    notice: mpsc::Sender<(Registration, PauseTicket)>,
    bytes: Vec<u8>,
    destroyed: Arc<AtomicBool>,
}
impl Drop for KeptNative {
    fn drop(&mut self) {
        pause(&self.pause, &self.notice, std::mem::take(&mut self.bytes));
        self.destroyed.store(true, Ordering::SeqCst);
    }
}
struct OriginalKeeper {
    _capacity: NativeReservation,
    native_destroyed: Arc<AtomicBool>,
    io: StoreIoOwner<Store>,
    notice: mpsc::Sender<usize>,
}
impl Drop for OriginalKeeper {
    fn drop(&mut self) {
        assert!(self.native_destroyed.load(Ordering::SeqCst));
        // The native allocation is destroyed, but the enclosing storage
        // reservation and retirement witness have not been released yet.
        self.notice
            .send(self.io.snapshot().unwrap().physical_owners)
            .unwrap();
    }
}

struct OriginalJobKeeper {
    _capacity: NativeReservation,
    destroyed: Arc<AtomicBool>,
    io: StoreIoOwner<Store>,
    notice: mpsc::Sender<usize>,
}
impl Drop for OriginalJobKeeper {
    fn drop(&mut self) {
        assert!(self.destroyed.load(Ordering::SeqCst));
        self.notice
            .send(self.io.snapshot().unwrap().accepted)
            .unwrap();
    }
}

#[test]
fn original_job_capacity_survives_callback_completion_and_detached_buffer_destruction() {
    let (physical, _, _) = store();
    let owner = StoreIoOwner::new(physical, limits(), |_| Ok(())).unwrap();
    let mut global_limits = latent_core::native_capacity::NativeCapacityLimits::default();
    global_limits.recovery.slots = 1;
    let global = NativeCapacityOwner::new(global_limits).unwrap();
    let request = NativeReservationRequest {
        request_bytes: 128,
        work_bytes: 512,
        response_bytes: 1024,
    };
    let deadline = Instant::now() + WATCHDOG;
    let capacity = global
        .reserve(NativeAdmissionClass::Recovery, request, deadline)
        .unwrap();
    let destroyed = Arc::new(AtomicBool::new(false));
    let (retired_notice, retired) = mpsc::channel();
    let keeper = Arc::new(OriginalJobKeeper {
        _capacity: capacity,
        destroyed: Arc::clone(&destroyed),
        io: owner.clone(),
        notice: retired_notice,
    });
    let weak = Arc::downgrade(&keeper);
    let callback = Rendezvous::new(1);
    let worker_callback = callback.clone();
    let destructor = Rendezvous::new(1);
    let worker_destructor = destructor.clone();
    let (callback_notice, callback_receiver) = mpsc::channel();
    let (destructor_notice, destructor_receiver) = mpsc::channel();
    let worker_destroyed = Arc::clone(&destroyed);
    let job = owner
        .submit_retaining(StoreIoKind::Write, 512, keeper, move |_| {
            pause(&worker_callback, &callback_notice, ());
            KeptNative {
                pause: worker_destructor,
                notice: destructor_notice,
                bytes: vec![0; 512],
                destroyed: worker_destroyed,
            }
        })
        .unwrap();
    let (_, ticket) = ready(&callback_receiver);
    drop(job);
    assert!(weak.upgrade().is_some());
    assert!(matches!(
        global.reserve(NativeAdmissionClass::Recovery, request, deadline),
        Err(NativeCapacityError::SlotsFull)
    ));
    callback.release(ticket).unwrap();
    let (_, ticket) = ready(&destructor_receiver);
    assert!(!destroyed.load(Ordering::SeqCst));
    assert!(weak.upgrade().is_some());
    assert!(matches!(
        global.reserve(NativeAdmissionClass::Recovery, request, deadline),
        Err(NativeCapacityError::SlotsFull)
    ));
    destructor.release(ticket).unwrap();
    assert!(finish(&owner).clean);
    assert_eq!(retired.recv_timeout(WATCHDOG).unwrap(), 1);
    assert!(weak.upgrade().is_none());
    assert!(destroyed.load(Ordering::SeqCst));
    assert!(global
        .reserve(NativeAdmissionClass::Recovery, request, deadline)
        .is_ok());
}

#[test]
fn original_capacity_keeper_survives_detached_native_retirement_until_actual_destruction() {
    let (physical, _, closed) = store();
    let owner = StoreIoOwner::new(physical, limits(), |_| Ok(())).unwrap();
    let mut global_limits = latent_core::native_capacity::NativeCapacityLimits::default();
    global_limits.ordinary.slots = 1;
    let global = NativeCapacityOwner::new(global_limits).unwrap();
    let request = NativeReservationRequest {
        request_bytes: 128,
        work_bytes: 512,
        response_bytes: 1024,
    };
    let deadline = Instant::now() + WATCHDOG;
    let capacity = global
        .reserve(NativeAdmissionClass::Ordinary, request, deadline)
        .unwrap();
    let native_destroyed = Arc::new(AtomicBool::new(false));
    let (keeper_notice, keeper_retired) = mpsc::channel();
    let keeper = Arc::new(OriginalKeeper {
        _capacity: capacity,
        native_destroyed: Arc::clone(&native_destroyed),
        io: owner.clone(),
        notice: keeper_notice,
    });
    let weak_keeper = Arc::downgrade(&keeper);
    let mut retained = owner.reserve_retained::<KeptNative>(512).unwrap();
    assert!(retained.retain_owner(keeper).is_ok());
    let foreign: Arc<dyn std::any::Any + Send + Sync> = Arc::new(());
    let refused = retained.retain_owner(Arc::clone(&foreign)).unwrap_err();
    assert!(Arc::ptr_eq(&refused, &foreign));
    drop(refused);
    let witness = retained.retirement_witness().unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker_pause = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let destroyed = Arc::clone(&native_destroyed);
    let opened = owner
        .submit(StoreIoKind::Read, 512, move |_| {
            assert!(retained
                .attach(KeptNative {
                    pause: worker_pause,
                    notice,
                    bytes: vec![0; 512],
                    destroyed,
                })
                .is_ok());
            retained
        })
        .unwrap();
    let retained = wait(opened).unwrap();
    // Drop the original response without retaining an explicit receipt. The
    // pre-reserved destructor and original global keeper remain physical owners.
    drop(retained);
    let (_, ticket) = ready(&receiver);
    owner.close();
    assert!(!native_destroyed.load(Ordering::SeqCst));
    assert!(!witness.has_retired());
    assert!(weak_keeper.upgrade().is_some());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert!(owner.snapshot().unwrap().retained_bytes >= 512);
    assert!(matches!(
        global.reserve(NativeAdmissionClass::Ordinary, request, deadline),
        Err(NativeCapacityError::SlotsFull)
    ));
    assert!(!closed.load(Ordering::SeqCst));
    rendezvous.release(ticket).unwrap();
    assert!(finish(&owner).clean);
    assert_eq!(keeper_retired.recv_timeout(WATCHDOG).unwrap(), 1);
    assert!(native_destroyed.load(Ordering::SeqCst));
    assert!(witness.has_retired());
    assert!(weak_keeper.upgrade().is_none());
    let replacement = global
        .reserve(NativeAdmissionClass::Ordinary, request, deadline)
        .unwrap();
    drop(replacement);

    let (store, _, _) = store();
    let late = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let mut retained = late.reserve_retained::<u8>(1).unwrap();
    assert!(retained.attach(1).is_ok());
    assert!(retained.retain_owner(foreign).is_err());
    drop(retained);
    assert!(finish(&late).clean);
}

#[test]
fn native_retirement_remains_charged_and_on_worker_through_paused_destructor() {
    struct Native {
        pause: Rendezvous,
        notice: mpsc::Sender<(Registration, PauseTicket)>,
        destructor_thread: mpsc::Sender<std::thread::ThreadId>,
    }
    impl Drop for Native {
        fn drop(&mut self) {
            self.destructor_thread
                .send(std::thread::current().id())
                .unwrap();
            pause(&self.pause, &self.notice, vec![0_u8; 256]);
        }
    }
    let (store, _, closed) = store();
    let clock = clock();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let mut retained = owner.reserve_retained::<Native>(256).unwrap();
    let rendezvous = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let (destructor_thread, threads) = mpsc::channel();
    assert!(retained
        .attach(Native {
            pause: rendezvous.clone(),
            notice,
            destructor_thread
        })
        .is_ok());
    let deadline = clock.monotonic_now() + Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    let witness = retained.retirement_witness().unwrap();
    assert!(retained.retirement_witness().is_none());
    assert!(!witness.has_retired());
    let mut retired = Box::pin(retained.retire());
    let (_, ticket) = ready(&receiver);
    assert_ne!(
        threads.recv_timeout(WATCHDOG).unwrap(),
        std::thread::current().id()
    );
    let during = owner.snapshot().unwrap();
    PollProbe::default().pending(retired.as_mut());
    assert!(!witness.has_retired());
    assert_eq!(during.physical_owners, 1);
    assert_eq!(during.accepted, 1);
    assert!(during.retained_bytes >= 256);
    assert!(!closed.load(Ordering::SeqCst));
    clock.advance(Duration::from_secs(1));
    assert!(!wait(drain).clean);
    rendezvous.release(ticket).unwrap();
    wait(retired);
    assert!(witness.has_retired());
    let report = wait(
        owner
            .drain_async(
                clock.monotonic_now() + Duration::from_secs(1),
                std::future::pending(),
            )
            .unwrap(),
    );
    assert!(report.snapshot.physically_retired());
    assert!(!report.clean);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn dropping_retirement_receipt_detaches_without_refunding_paused_physical_cleanup() {
    struct Native {
        pause: Rendezvous,
        notice: mpsc::Sender<(Registration, PauseTicket)>,
        destroyed: Arc<AtomicBool>,
    }
    impl Drop for Native {
        fn drop(&mut self) {
            pause(&self.pause, &self.notice, vec![0_u8; 512]);
            self.destroyed.store(true, Ordering::SeqCst);
        }
    }
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let mut retained = owner.reserve_retained::<Native>(512).unwrap();
    let rendezvous = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let destroyed = Arc::new(AtomicBool::new(false));
    assert!(retained
        .attach(Native {
            pause: rendezvous.clone(),
            notice,
            destroyed: Arc::clone(&destroyed),
        })
        .is_ok());
    let mut retired = Box::pin(retained.retire());
    let (_, ticket) = ready(&receiver);
    PollProbe::default().pending(retired.as_mut());
    drop(retired);
    assert!(!destroyed.load(Ordering::SeqCst));
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert!(owner.snapshot().unwrap().retained_bytes >= 512);
    owner.close();
    rendezvous.release(ticket).unwrap();
    let report = finish(&owner);
    assert!(report.clean);
    assert!(report.snapshot.physically_retired());
    assert!(destroyed.load(Ordering::SeqCst));
}

#[test]
fn completed_response_memory_prevents_clean_drain_until_actual_waiter_drop() {
    let (store, _, closed) = store();
    let clock = clock();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let (completed, notices) = mpsc::channel();
    let job = owner
        .submit(StoreIoKind::Read, 1024, move |_| {
            completed.send(()).unwrap();
            vec![0_u8; 1024]
        })
        .unwrap();
    notices.recv_timeout(WATCHDOG).unwrap();
    let deadline = clock.monotonic_now() + Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    clock.advance(Duration::from_secs(1));
    let timed_out = wait(drain);
    assert!(!timed_out.clean);
    assert_eq!(timed_out.snapshot.accepted, 1);
    assert!(timed_out.snapshot.retained_bytes >= 1024);
    drop(job);
    let late = wait(
        owner
            .drain_async(
                clock.monotonic_now() + Duration::from_secs(1),
                std::future::pending(),
            )
            .unwrap(),
    );
    assert!(late.snapshot.physically_retired());
    assert!(!late.clean);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn engine_resident_bytes_remain_reserved_until_physical_destruction() {
    let (store, _, _) = store();
    let mut config = limits();
    config.resident_bytes = 4096;
    let owner = StoreIoOwner::new(store, config, |_| Ok(())).unwrap();
    assert_eq!(owner.snapshot().unwrap().retained_bytes, 4096);
    let report = finish(&owner);
    assert!(report.clean);
    assert_eq!(report.snapshot.retained_bytes, 0);
}

#[test]
fn excessive_worker_and_queue_configuration_rejects_before_any_thread_owner() {
    for field in 0..4 {
        let (store, _, _) = store();
        let mut config = limits();
        match field {
            0 => config.workers = 33,
            1 => config.queued_jobs = 4097,
            2 => config.accepted_jobs = 8193,
            _ => config.retained_bytes = 1024 * 1024 * 1024 + 1,
        }
        let error = StoreIoOwner::new(store, config, |_| Ok(())).err().unwrap();
        assert_eq!(error.reason, StoreIoError::InvalidLimits);
        assert!(error.owner.is_none());
        assert!(error.store.is_some());
    }
}

#[test]
fn dropping_drain_cannot_extend_original_deadline_or_make_late_retirement_clean() {
    let (store, _, _) = store();
    let clock = clock();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit(StoreIoKind::Write, 64, move |_| {
            pause(&worker, &notice, vec![0_u8; 64]);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let original = clock.monotonic_now() + Duration::from_secs(1);
    drop(owner.drain_async(original, std::future::pending()).unwrap());
    clock.advance(Duration::from_secs(2));
    let observation = clock.monotonic_now() + Duration::from_secs(5);
    let drain = owner
        .drain_async(observation, std::future::pending())
        .unwrap();
    rendezvous.release(ticket).unwrap();
    wait(job).unwrap();
    let report = wait(drain);
    assert!(report.snapshot.physically_retired());
    assert!(report.snapshot.quarantined);
    assert!(!report.clean);
}
