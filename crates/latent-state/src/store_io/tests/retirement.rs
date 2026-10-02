use super::*;

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
    let mut retired = Box::pin(retained.retire());
    let (_, ticket) = ready(&receiver);
    assert_ne!(
        threads.recv_timeout(WATCHDOG).unwrap(),
        std::thread::current().id()
    );
    let during = owner.snapshot().unwrap();
    PollProbe::default().pending(retired.as_mut());
    assert_eq!(during.physical_owners, 1);
    assert_eq!(during.accepted, 1);
    assert!(during.retained_bytes >= 256);
    assert!(!closed.load(Ordering::SeqCst));
    clock.advance(Duration::from_secs(1));
    assert!(!wait(drain).clean);
    rendezvous.release(ticket).unwrap();
    wait(retired);
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
