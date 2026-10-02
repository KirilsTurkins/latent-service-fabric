use super::*;

fn exclusive_limits() -> StoreIoLimits {
    let mut config = limits();
    config.active_reads = 1;
    config.recovery = Some(StoreIoRecoveryLimits {
        workers: 1,
        queued_jobs: 4,
        accepted_jobs: 8,
        retained_bytes: 20_000,
        job_bytes: 10_000,
    });
    config
}

fn metadata_retired<S>(owner: &StoreIoOwner<S>) {
    let control = &owner.inner.control;
    let state = control.state.lock().unwrap();
    let (state, timeout) = control
        .changed
        .wait_timeout_while(state, WATCHDOG, |state| {
            state.accepted != 0
                || state.active_reads != 0
                || state.active_writes != 0
                || state.active_recovery_reads != 0
                || state.custody.is_some()
        })
        .unwrap();
    assert!(
        !timeout.timed_out(),
        "actual native/job custody did not retire"
    );
    assert_eq!(state.physical_owners, 0);
}

#[test]
fn exclusive_custody_refuses_actual_live_reads_writes_and_detached_jobs() {
    for kind in [
        StoreIoKind::Read,
        StoreIoKind::Write,
        StoreIoKind::RecoveryRead,
        StoreIoKind::RecoveryWrite,
    ] {
        let (store, _, _) = store();
        let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
        let gate = Rendezvous::new(1);
        let worker = gate.clone();
        let (notice, receiver) = mpsc::channel();
        let job = owner
            .submit(kind, 128, move |_| pause(&worker, &notice, vec![0_u8; 128]))
            .unwrap();
        let (_, ticket) = ready(&receiver);
        assert!(matches!(
            owner.reserve_custody::<()>(128, Instant::now() + WATCHDOG, Arc::new(())),
            Err(StoreIoError::CustodyBusy)
        ));
        drop(job);
        assert!(matches!(
            owner.reserve_custody::<()>(128, Instant::now() + WATCHDOG, Arc::new(())),
            Err(StoreIoError::CustodyBusy)
        ));
        gate.release(ticket).unwrap();
        metadata_retired(&owner);
        let custody = owner
            .reserve_custody::<()>(128, Instant::now() + WATCHDOG, Arc::new(()))
            .unwrap();
        assert!(owner.snapshot().unwrap().custody_active);
        wait(custody.retire());
        metadata_retired(&owner);
        assert!(finish(&owner).clean);
    }
}

#[test]
fn unclaimed_response_and_native_operation_pin_are_not_quiescence() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let (done, ready) = mpsc::channel();
    let response = owner
        .submit(StoreIoKind::Read, 128, move |_| {
            done.send(()).unwrap();
            vec![0_u8; 128]
        })
        .unwrap();
    ready.recv_timeout(WATCHDOG).unwrap();
    assert!(matches!(
        owner.reserve_custody::<()>(128, Instant::now() + WATCHDOG, Arc::new(())),
        Err(StoreIoError::CustodyBusy)
    ));
    assert_eq!(wait(response).unwrap().len(), 128);
    metadata_retired(&owner);
    let mut pin = owner.reserve_retained::<Vec<u8>>(128).unwrap();
    assert!(pin.attach(vec![0_u8; 128]).is_ok());
    assert!(matches!(
        owner.reserve_custody::<()>(128, Instant::now() + WATCHDOG, Arc::new(())),
        Err(StoreIoError::CustodyBusy)
    ));
    wait(pin.retire());
    metadata_retired(&owner);
    assert!(finish(&owner).clean);
}

#[test]
fn custody_excludes_all_generic_work_and_only_its_original_affine_job_can_run() {
    let (store, writes, _) = store();
    let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let custody = owner
        .reserve_custody::<Vec<u8>>(512, Instant::now() + WATCHDOG, Arc::new(()))
        .unwrap();
    for kind in [
        StoreIoKind::Read,
        StoreIoKind::Write,
        StoreIoKind::RecoveryRead,
        StoreIoKind::RecoveryWrite,
    ] {
        assert_eq!(
            owner
                .submit(kind, 0, |_| panic!("noncustodial job entered"))
                .err()
                .unwrap()
                .reason,
            StoreIoError::CustodyBusy
        );
    }
    assert!(matches!(
        owner.reserve_retained::<()>(0),
        Err(StoreIoError::CustodyBusy)
    ));
    assert!(matches!(
        owner.reserve_recovery_retained::<()>(0),
        Err(StoreIoError::CustodyBusy)
    ));
    let (custody, thread) = wait(
        owner
            .submit_custody(
                custody,
                StoreIoKind::RecoveryWrite,
                512,
                |custody, store| {
                    assert!(custody.attach(vec![7_u8; 512]).is_ok());
                    store.writes.fetch_add(1, Ordering::SeqCst);
                    std::thread::current().name().unwrap().to_owned()
                },
            )
            .unwrap(),
    )
    .unwrap();
    assert!(thread.starts_with("latent-store-recovery-"));
    let (custody, bytes) = wait(
        owner
            .submit_custody(custody, StoreIoKind::RecoveryRead, 512, |custody, _| {
                custody.get().unwrap().clone()
            })
            .unwrap(),
    )
    .unwrap();
    assert_eq!(bytes, vec![7_u8; 512]);
    assert_eq!(writes.load(Ordering::SeqCst), 1);
    wait(custody.retire());
    metadata_retired(&owner);
    assert_eq!(
        wait(owner.submit(StoreIoKind::Read, 0, |_| 11).unwrap()).unwrap(),
        11
    );
    assert!(finish(&owner).clean);
}

#[test]
fn detached_custody_destructor_keeps_original_global_reservation_and_gate_charged() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    };
    struct Native {
        gate: Rendezvous,
        notice: mpsc::Sender<(Registration, PauseTicket)>,
    }
    impl Drop for Native {
        fn drop(&mut self) {
            pause(&self.gate, &self.notice, vec![0_u8; 512]);
        }
    }
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let mut limits = NativeCapacityLimits::default();
    limits.recovery.slots = 1;
    let native = NativeCapacityOwner::new(limits).unwrap();
    let original = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 2048,
                    ..NativeReservationRequest::default()
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    );
    let weak = Arc::downgrade(&original);
    let mut custody = owner
        .reserve_custody::<Native>(512, original.original_deadline(), original)
        .unwrap();
    let witness = custody.retirement_witness().unwrap();
    let gate = Rendezvous::new(1);
    let worker = gate.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit_custody(
            custody,
            StoreIoKind::RecoveryWrite,
            512,
            move |custody, _| {
                assert!(custody
                    .attach(Native {
                        gate: worker,
                        notice
                    })
                    .is_ok());
            },
        )
        .unwrap();
    drop(job);
    let (_, ticket) = ready(&receiver);
    assert!(!witness.has_retired());
    assert!(weak.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert!(owner.snapshot().unwrap().custody_active);
    assert_eq!(
        owner
            .submit(StoreIoKind::RecoveryRead, 0, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::CustodyBusy
    );
    gate.release(ticket).unwrap();
    metadata_retired(&owner);
    assert!(witness.has_retired());
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn foreign_owner_and_expired_deadline_cannot_reuse_original_custody() {
    let original_clock = clock();
    let (store, _, _) = store();
    let owner = StoreIoOwner::with_clock(
        store,
        exclusive_limits(),
        |_| Ok(()),
        Arc::new(original_clock.clone()),
    )
    .unwrap();
    let (store, _, _) = store();
    let foreign = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let custody = owner
        .reserve_custody::<()>(
            128,
            original_clock.monotonic_now() + Duration::from_secs(1),
            Arc::new(()),
        )
        .unwrap();
    assert!(matches!(
        foreign.submit_custody(custody, StoreIoKind::RecoveryRead, 0, |_, _| panic!(
            "foreign custody ran"
        )),
        Err(StoreIoError::CustodyMismatch)
    ));
    metadata_retired(&owner);
    let custody = owner
        .reserve_custody::<()>(
            128,
            original_clock.monotonic_now() + Duration::from_secs(1),
            Arc::new(()),
        )
        .unwrap();
    original_clock.advance(Duration::from_secs(2));
    assert!(matches!(
        owner.submit_custody(custody, StoreIoKind::RecoveryRead, 0, |_, _| panic!(
            "expired custody ran"
        )),
        Err(StoreIoError::CustodyExpired)
    ));
    metadata_retired(&owner);
    assert!(!owner.snapshot().unwrap().quarantined);
    assert!(finish(&owner).clean);
    assert!(finish(&foreign).clean);
}

#[test]
fn custody_panic_quarantines_without_reopening_admission_or_skipping_native_cleanup() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let mut custody = owner
        .reserve_custody::<Vec<u8>>(512, Instant::now() + WATCHDOG, Arc::new(()))
        .unwrap();
    let witness = custody.retirement_witness().unwrap();
    let failed = owner
        .submit_custody(custody, StoreIoKind::RecoveryWrite, 512, |custody, _| {
            assert!(custody.attach(vec![0_u8; 512]).is_ok());
            panic!("controlled physical callback panic");
        })
        .unwrap();
    assert!(matches!(wait(failed), Err(StoreIoError::RecoveryRequired)));
    metadata_retired(&owner);
    assert!(witness.has_retired());
    assert_eq!(
        owner
            .submit(StoreIoKind::Read, 0, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::AdmissionClosed
    );
    let report = finish(&owner);
    assert!(!report.clean && report.snapshot.physically_retired());
}

#[test]
fn custody_native_destructor_panic_retains_original_capacity_without_retirement_proof() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservationRequest,
    };
    struct Native;
    impl Drop for Native {
        fn drop(&mut self) {
            panic!("controlled unknown native retirement");
        }
    }
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, exclusive_limits(), |_| Ok(())).unwrap();
    let global = NativeCapacityOwner::new(Default::default()).unwrap();
    let original = Arc::new(
        global
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 512,
                    ..NativeReservationRequest::default()
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    );
    let weak = Arc::downgrade(&original);
    let mut custody = owner
        .reserve_custody::<Native>(512, original.original_deadline(), original)
        .unwrap();
    let witness = custody.retirement_witness().unwrap();
    assert!(custody.attach(Native).is_ok());
    // Dropping the observation supplies no affirmative native cleanup proof.
    drop(custody.retire());
    let control = &owner.inner.control;
    let state = control.state.lock().unwrap();
    let (state, timeout) = control
        .changed
        .wait_timeout_while(state, WATCHDOG, |state| !state.quarantined)
        .unwrap();
    assert!(!timeout.timed_out());
    assert!(state.custody.is_some() && state.closed);
    assert_eq!(state.physical_owners, 1);
    assert_eq!(state.accepted, 1);
    drop(state);
    assert!(!witness.has_retired());
    assert!(weak.upgrade().is_some());
    assert_eq!(global.snapshot().unwrap().recovery.slots, 1);
    let report = wait(
        owner
            .drain_async(Instant::now() + WATCHDOG, std::future::ready(()))
            .unwrap(),
    );
    assert!(!report.clean && !report.snapshot.physically_retired());
    assert!(report.snapshot.custody_active);
    assert_eq!(global.snapshot().unwrap().recovery.slots, 1);
    // This bounded unresolved owner intentionally survives until process loss.
    // No test-only reset converts unknown physical cleanup into positive proof.
}
