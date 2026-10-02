use super::*;

#[test]
fn closed_startup_never_delivers_readiness_and_keeps_initializer_physically_owned() {
    let (store, _, closed) = store();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let mut startup = Box::pin(
        StoreIoOwner::initialize(
            move || {
                pause(&worker, &notice, vec![0_u8; 64]);
                Ok(store)
            },
            64,
            limits(),
            |_| Ok(()),
        )
        .unwrap(),
    );
    let (_, ticket) = ready(&receiver);
    startup.close();
    assert!(startup.snapshot().unwrap().admission_closed);
    assert!(!closed.load(Ordering::SeqCst));
    rendezvous.release(ticket).unwrap();
    assert!(matches!(
        wait(startup.as_mut()),
        Err(StoreIoError::AdmissionClosed)
    ));
    let report = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(report.clean);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn initialization_and_ordinary_io_use_same_fixed_worker_owner() {
    let (store, writes, closed) = store();
    let initialization_thread = Arc::new(std::sync::Mutex::new(None));
    let observed = Arc::clone(&initialization_thread);
    let startup = StoreIoOwner::initialize(
        move || {
            *observed.lock().unwrap() = std::thread::current().name().map(str::to_owned);
            Ok(store)
        },
        32,
        limits(),
        |_| Ok(()),
    )
    .unwrap();
    let ready = wait(startup).unwrap();
    assert!(initialization_thread
        .lock()
        .unwrap()
        .as_ref()
        .unwrap()
        .starts_with("latent-store-io-"));
    let job = ready
        .submit(StoreIoKind::Write, 0, |store| {
            store.writes.fetch_add(1, Ordering::SeqCst)
        })
        .unwrap();
    assert_eq!(wait(job).unwrap(), 0);
    assert_eq!(writes.load(Ordering::SeqCst), 1);
    let deadline = Instant::now() + WATCHDOG;
    let report = wait(ready.drain_async(deadline, std::future::pending()).unwrap());
    assert!(report.clean);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn dropped_startup_waiter_retains_initializer_until_actual_engine_close() {
    let (mut store, writes, closed) = store();
    let (closed_notice, closed_receiver) = mpsc::channel();
    store.close_notice = Some(closed_notice);
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let buffer = Arc::new(vec![1_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let startup = StoreIoOwner::initialize(
        move || {
            pause(&worker, &notice, buffer);
            store.writes.fetch_add(1, Ordering::SeqCst);
            Ok(store)
        },
        32,
        limits(),
        |_| Ok(()),
    )
    .unwrap();
    let (registration, ticket) = ready(&receiver);
    assert_eq!(startup.snapshot().unwrap().active_writes, 1);
    assert!(startup.snapshot().unwrap().retained_bytes > 0);
    drop(startup);
    assert!(weak.upgrade().is_some());
    assert_eq!(writes.load(Ordering::SeqCst), 0);
    assert!(!closed.load(Ordering::SeqCst));
    rendezvous.release(ticket).unwrap();
    closed_receiver.recv_timeout(WATCHDOG).unwrap();
    rendezvous.require_retired(registration).unwrap();
    assert!(weak.upgrade().is_none());
    assert_eq!(writes.load(Ordering::SeqCst), 1);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn initialization_failure_never_delivers_ready_or_replaces_engine() {
    let clock = clock();
    let now = clock.monotonic_now();
    let mut startup = Box::pin(
        StoreIoOwner::<Store>::initialize_with_clock(
            || Err(StoreIoError::InitializationFailed),
            0,
            limits(),
            |_| panic!("absent engine finalized"),
            Arc::new(clock.clone()),
        )
        .unwrap(),
    );
    let error = wait(startup.as_mut()).err().unwrap();
    assert_eq!(error, StoreIoError::InitializationFailed);
    let snapshot = startup.snapshot().unwrap();
    assert!(snapshot.admission_closed);
    assert!(snapshot.quarantined);
    assert_eq!(snapshot.failure, Some(StoreIoError::InitializationFailed));
    let deadline = now + Duration::from_secs(1);
    let report = wait(
        startup
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
}
