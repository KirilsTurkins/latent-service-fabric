use super::*;

#[test]
fn physical_operation_pins_bound_admission_keep_root_through_deadline_and_retire_after_close() {
    let (_root, mut config) = fixture();
    config.io.accepted_jobs = 4;
    config.io.queued_jobs = 4;
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = wait(
        ProtectedStoreOwner::start_with_clock(config.clone(), Arc::new(clock.clone())).unwrap(),
    )
    .unwrap();
    let pins: Vec<_> = (0..4).map(|_| owner.reserve_operation().unwrap()).collect();
    assert!(matches!(
        owner.reserve_operation(),
        Err(ProtectedStoreError::Io(StoreIoError::AcceptedFull))
    ));
    assert_eq!(owner.snapshot().unwrap().physical_owners, 4);
    let deadline = clock.monotonic_now() + std::time::Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    clock.advance(std::time::Duration::from_secs(1));
    let report = wait(drain);
    assert!(!report.clean);
    assert!(report.snapshot.quarantined);
    assert_eq!(report.snapshot.physical_owners, 4);
    assert!(!report.snapshot.engine_closed());
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    for pin in pins {
        wait(pin.retire());
    }
    let late = wait(
        owner
            .drain_async(
                clock.monotonic_now() + std::time::Duration::from_secs(2),
                std::future::pending(),
            )
            .unwrap(),
    );
    assert!(late.snapshot.physically_retired());
    assert!(!late.clean);
    let reopened = start(config);
    assert!(finish(&reopened).clean);
}

#[test]
fn protected_initialization_shared_families_snapshots_and_reopen_are_real() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    assert!(owner.snapshot().unwrap().retained_bytes >= config.io.resident_bytes);
    wait(owner.apply(batch(b"first")).unwrap())
        .unwrap()
        .unwrap();
    let caller_thread = std::thread::current().id();
    let worker_thread = wait(
        owner
            .with_store(StoreIoKind::Read, 1024, |engine| {
                let view = engine.snapshot()?;
                assert_eq!(
                    view.get(&key(Family::Command, "command"))?,
                    Some(b"first".to_vec())
                );
                Ok(std::thread::current().id())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_ne!(caller_thread, worker_thread);
    let old = wait(owner.open_view().unwrap()).unwrap().unwrap();
    wait(owner.apply(batch(b"second")).unwrap())
        .unwrap()
        .unwrap();
    let (old, values) = read(&owner, old);
    assert_eq!(values, vec![Some(b"first".to_vec()); 3]);
    drop(old);
    let view = wait(owner.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&owner, view);
    assert_eq!(values, vec![Some(b"second".to_vec()); 3]);
    drop(view);
    assert!(finish(&owner).clean);
    assert_eq!(owner.snapshot().unwrap().retained_bytes, 0);
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![Some(b"second".to_vec()); 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn native_read_view_survives_deadline_and_retires_only_on_fixed_worker() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = wait(
        ProtectedStoreOwner::start_with_clock(config.clone(), Arc::new(clock.clone())).unwrap(),
    )
    .unwrap();
    let view = wait(owner.open_view().unwrap()).unwrap().unwrap();
    let deadline = clock.monotonic_now() + std::time::Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    clock.advance(std::time::Duration::from_secs(1));
    let report = wait(drain);
    assert!(!report.clean);
    assert!(report.snapshot.quarantined);
    assert_eq!(report.snapshot.physical_owners, 1);
    assert!(!report.snapshot.engine_closed());
    // The physical descriptor still prevents a second engine from opening.
    assert!(matches!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(_)
    ));
    drop(view);
    let late = wait(
        owner
            .drain_async(
                clock.monotonic_now() + std::time::Duration::from_secs(2),
                std::future::pending(),
            )
            .unwrap(),
    );
    assert!(late.snapshot.physically_retired());
    assert_eq!(late.snapshot.physical_owners, 0);
    assert!(!late.clean); // quarantine is sticky after actual retirement
    let reopened = start(config);
    assert!(finish(&reopened).clean);
}

#[test]
fn foreign_views_and_native_view_caps_reject_without_cross_store_reads() {
    let (_root, mut config) = fixture();
    config.engine.maximum_read_views = 1;
    let owner = start(config);
    let (_other_root, other_config) = fixture();
    let other = start(other_config);
    let view = wait(owner.open_view().unwrap()).unwrap().unwrap();
    assert!(matches!(
        wait(owner.open_view().unwrap()).unwrap(),
        Err(ProtectedStoreError::Store(StoreError::Capacity))
    ));
    assert!(matches!(
        other.with_view::<()>(view, 0, |_| panic!("foreign native view was read")),
        Err(ProtectedStoreError::ForeignView)
    ));
    assert!(finish(&owner).clean);
    assert!(finish(&other).clean);
}

#[test]
fn root_replacement_during_read_gates_after_worker_operation_and_preserves_new_bytes() {
    let (root, config) = fixture();
    let owner = start(config.clone());
    let view = wait(owner.open_view().unwrap()).unwrap().unwrap();
    let pause = Rendezvous::new(1);
    let worker = pause.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .with_view(view, 64, move |_| {
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut parked = Box::pin(physical.pause());
            PollProbe::default().pending(parked.as_mut());
            notice
                .send(worker.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(parked);
            Ok(())
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let file = root.path().join(&config.file_name);
    fs::rename(&file, root.path().join("old-engine.redb")).unwrap();
    fs::write(&file, b"replacement").unwrap();
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
    pause.release(ticket).unwrap();
    let (view, result) = wait(job).unwrap();
    assert_eq!(result, Err(ProtectedStoreError::UnsafeRoot));
    assert!(owner.snapshot().unwrap().quarantined);
    assert!(matches!(
        owner.apply(batch(b"forbidden")),
        Err(ProtectedStoreError::UnsafeRoot)
    ));
    drop(view);
    assert!(!finish(&owner).clean);
    assert_eq!(fs::read(file).unwrap(), b"replacement");
}

#[test]
fn lost_protected_fence_after_flush_reports_commit_uncertain_and_never_business_abort() {
    let (root, config) = fixture();
    let owner = start(config.clone());
    let pause = Rendezvous::new(1);
    let worker = pause.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .apply_fenced(batch(b"committed-original"), 0, move || {
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut parked = Box::pin(physical.pause());
            PollProbe::default().pending(parked.as_mut());
            notice
                .send(worker.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(parked);
            Ok::<_, ()>(())
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let file = root.path().join(&config.file_name);
    fs::rename(&file, root.path().join("original.redb")).unwrap();
    fs::write(&file, b"replacement").unwrap();
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
    pause.release(ticket).unwrap();
    assert_eq!(
        wait(job).unwrap(),
        Err(ProtectedFencedStoreError::Store(
            ProtectedStoreError::CommitUncertain
        ))
    );
    assert!(!finish(&owner).clean);
    assert_eq!(fs::read(file).unwrap(), b"replacement");
    let mut original_config = config;
    original_config.file_name = "original.redb".into();
    let recovered = start(original_config);
    let view = wait(recovered.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&recovered, view);
    assert_eq!(values, vec![Some(b"committed-original".to_vec()); 3]);
    drop(view);
    assert!(finish(&recovered).clean);
}
