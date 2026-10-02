use super::*;
use crate::store_io::StoreIoKind;

#[test]
fn reserved_native_status_progresses_while_all_ordinary_workers_and_queue_are_full() {
    let (_root, mut config) = fixture();
    config.io.queued_jobs = 1;
    let owner = start(config);
    wait(owner.apply(batch(b"durable-before-pressure")).unwrap())
        .unwrap()
        .unwrap();
    let rendezvous = Rendezvous::new(3);
    let (notice, receiver) = mpsc::channel();
    let mut jobs = Vec::new();
    let mut tickets = Vec::new();
    for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
        let worker = rendezvous.clone();
        let notice = notice.clone();
        jobs.push(
            owner
                .with_store(kind, 512, move |_engine| {
                    let (registration, mut retained) = worker.track(vec![0_u8; 512]).unwrap();
                    retained.commit(Stage::Entered).unwrap();
                    let mut pause = Box::pin(retained.pause());
                    PollProbe::default().pending(pause.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(pause);
                    Ok(())
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let queued = owner.with_store(StoreIoKind::Write, 0, |_| Ok(())).unwrap();
    assert!(matches!(
        owner.with_store(StoreIoKind::Read, 0, |_| Ok(())),
        Err(ProtectedStoreError::Io(StoreIoError::QueueFull))
    ));
    let status = owner
        .with_store(StoreIoKind::RecoveryRead, 4_096, |engine| {
            engine.snapshot()?.get(&key(Family::State, "command"))
        })
        .unwrap();
    assert_eq!(
        wait(status).unwrap().unwrap().as_deref(),
        Some(b"durable-before-pressure".as_slice())
    );
    assert_eq!(owner.snapshot().unwrap().active_reads, 2);
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 0);
    for ticket in tickets {
        rendezvous.release(ticket).unwrap();
    }
    for job in jobs {
        wait(job).unwrap().unwrap();
    }
    wait(queued).unwrap().unwrap();
    assert!(finish(&owner).clean);
    owner.reap_retired_threads().unwrap();
}

#[test]
fn recovery_snapshot_reads_and_retires_on_reserved_worker_under_ordinary_pressure() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    };
    let (_root, mut config) = fixture();
    config.io.queued_jobs = 1;
    config.io.accepted_jobs = 4;
    let owner = start(config);
    let global = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    owner.bind_native_capacity(&global).unwrap();
    wait(owner.apply(batch(b"actual-recovery-view")).unwrap())
        .unwrap()
        .unwrap();
    let rendezvous = Rendezvous::new(3);
    let (notice, receiver) = mpsc::channel();
    let mut jobs = Vec::new();
    let mut tickets = Vec::new();
    for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
        let worker = rendezvous.clone();
        let notice = notice.clone();
        jobs.push(
            owner
                .with_store(kind, 512, move |_| {
                    let (registration, mut retained) = worker.track(vec![0_u8; 512]).unwrap();
                    retained.commit(Stage::Entered).unwrap();
                    let mut pause = Box::pin(retained.pause());
                    PollProbe::default().pending(pause.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(pause);
                    Ok(())
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let queued = owner.with_store(StoreIoKind::Write, 0, |_| Ok(())).unwrap();
    assert!(matches!(
        owner.open_view(),
        Err(ProtectedStoreError::Io(StoreIoError::AcceptedFull))
    ));
    let original = Arc::new(
        global
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 128,
                    work_bytes: 16384,
                    response_bytes: 4096,
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    );
    let original_weak = Arc::downgrade(&original);
    let view = wait(owner.open_recovery_view_retaining(original).unwrap())
        .unwrap()
        .unwrap();
    let (view, result) = wait(
        owner
            .with_view(view, 4096, |native| {
                assert!(std::thread::current()
                    .name()
                    .unwrap()
                    .starts_with("latent-store-recovery-"));
                native.get(&key(Family::State, "command"))
            })
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        result.unwrap().as_deref(),
        Some(b"actual-recovery-view".as_slice())
    );
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 1);
    assert_eq!(global.snapshot().unwrap().recovery.slots, 1);
    wait(view.retire());
    assert!(original_weak.upgrade().is_none());
    assert!(global.snapshot().unwrap().physically_retired());
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 0);
    // No ordinary worker needed to retire the actual read transaction.
    assert_eq!(owner.snapshot().unwrap().active_reads, 2);
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    for ticket in tickets {
        rendezvous.release(ticket).unwrap();
    }
    for job in jobs {
        wait(job).unwrap().unwrap();
    }
    wait(queued).unwrap().unwrap();
    assert!(finish(&owner).clean);
}

#[test]
fn detached_recovery_view_keeps_original_global_reservation_until_native_retirement() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityError, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    };
    let (_root, config) = fixture();
    let owner = start(config);
    let mut limits = NativeCapacityLimits::default();
    limits.recovery.slots = 1;
    let global = NativeCapacityOwner::new(limits).unwrap();
    owner.bind_native_capacity(&global).unwrap();
    let request = NativeReservationRequest {
        request_bytes: 128,
        work_bytes: 16384,
        response_bytes: 4096,
    };
    let deadline = Instant::now() + WATCHDOG;
    let original = Arc::new(
        global
            .reserve(NativeAdmissionClass::Recovery, request, deadline)
            .unwrap(),
    );
    let weak = Arc::downgrade(&original);
    let mut view = wait(owner.open_recovery_view_retaining(original).unwrap())
        .unwrap()
        .unwrap();
    let witness = view.retirement_witness().unwrap();
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .with_view(view, 1024, move |native| {
            let (registration, mut retained) = worker.track(vec![0_u8; 1024]).unwrap();
            retained.commit(Stage::Entered).unwrap();
            let mut pause = Box::pin(retained.pause());
            PollProbe::default().pending(pause.as_mut());
            notice
                .send(worker.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(pause);
            native.get(&key(Family::State, "missing"))
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(job);
    owner.close();
    assert!(!witness.has_retired());
    assert!(weak.upgrade().is_some());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert_eq!(owner.snapshot().unwrap().active_recovery_reads, 1);
    assert!(matches!(
        global.reserve(NativeAdmissionClass::Recovery, request, deadline),
        Err(NativeCapacityError::SlotsFull)
    ));
    gates.release(ticket).unwrap();
    let report = finish(&owner);
    assert!(report.clean);
    assert!(witness.has_retired());
    assert!(weak.upgrade().is_none());
    assert!(global.snapshot().unwrap().physically_retired());
}
