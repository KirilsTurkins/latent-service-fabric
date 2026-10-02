use super::*;

struct OrdinaryPressure {
    gates: Rendezvous,
    tickets: Vec<latent_core::test_support::coordination::PauseTicket>,
    jobs: Vec<crate::store_io::StoreIoJob<Result<(), ProtectedStoreError>>>,
    queued: crate::store_io::StoreIoJob<Result<(), ProtectedStoreError>>,
}

impl OrdinaryPressure {
    fn enter(owner: &ProtectedStoreOwner) -> Self {
        let gates = Rendezvous::new(3);
        let (notice, receiver) = mpsc::channel();
        let mut jobs = Vec::new();
        let mut tickets = Vec::new();
        for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
            let worker = gates.clone();
            let notice = notice.clone();
            jobs.push(
                owner
                    .with_store(kind, 512, move |_| {
                        let (registration, mut tracked) = worker.track(()).unwrap();
                        tracked.commit(Stage::Entered).unwrap();
                        let mut pause = Box::pin(tracked.pause());
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
        Self {
            gates,
            tickets,
            jobs,
            queued,
        }
    }

    fn release(self) {
        for ticket in self.tickets {
            self.gates.release(ticket).unwrap();
        }
        for job in self.jobs {
            wait(job).unwrap().unwrap();
        }
        wait(self.queued).unwrap().unwrap();
    }
}

#[test]
fn detached_checkpoint_write_keeps_original_global_owner_through_actual_recovery_cleanup() {
    let (_business, mut config) = fixture();
    config.io.queued_jobs = 1;
    let external = external();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound_with_clock(config, clock.clone());
    let native = owner.native_capacity().unwrap();
    let keeper = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 64 * 1024,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + std::time::Duration::from_secs(1),
            )
            .unwrap(),
    );
    let weak = Arc::downgrade(&keeper);
    let (mut checkpoint, initialized) = wait(
        owner
            .open_checkpoint(
                ProtectedCheckpointConfig {
                    root: external.path().to_path_buf(),
                },
                identity(),
                witness(&owner),
                keeper,
                observed,
            )
            .unwrap(),
    )
    .unwrap();
    initialized.unwrap();
    assert!(weak
        .upgrade()
        .unwrap()
        .reserve_buffer(
            latent_core::native_capacity::NativeBufferClass::Work,
            64 * 1024,
        )
        .is_err()); // The actual native root/file footprint already owns Work.
    let retired = checkpoint.retirement_witness().unwrap();
    assert!(checkpoint.retirement_witness().is_none());
    seed_owner(&owner, 3, 4000);

    let ordinary = OrdinaryPressure::enter(&owner);
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .advance_checkpoint(checkpoint, None, 2, move |view| {
            let actual = observed(view)?;
            let (registration, mut tracked) = worker_gates.track(()).unwrap();
            tracked.commit(Stage::Entered).unwrap();
            let mut pause = Box::pin(tracked.pause());
            PollProbe::default().pending(pause.as_mut());
            notice
                .send(worker_gates.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(pause);
            Ok(actual)
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(job);
    clock.advance(std::time::Duration::from_secs(2));
    assert!(!retired.has_retired());
    assert!(weak.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    owner.close();
    gates.release(ticket).unwrap();
    ordinary.release();
    let report = finish(&owner);
    assert!(report.clean);
    assert!(retired.has_retired());
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(report.snapshot.physical_owners, 0);
    assert!(fs::read(external.path().join(CHECKPOINT_NAME))
        .unwrap()
        .is_empty());
}

#[test]
fn lost_checkpoint_fence_after_actual_write_is_uncertain_and_gates_further_io() {
    let (_business, config) = fixture();
    let external = external();
    let owner = bound(config);
    let checkpoint = open(&owner, &external, witness(&owner));
    seed_owner(&owner, 3, 4000);
    let (mut checkpoint, original) = wait(
        owner
            .advance_checkpoint(checkpoint, None, 2, observed)
            .unwrap(),
    )
    .unwrap();
    let original = original.unwrap();
    let retired = checkpoint.retirement_witness().unwrap();
    seed_owner(&owner, 4, 5000);
    let path = external.path().join(CHECKPOINT_NAME);
    let changed_path = path.clone();
    let (checkpoint, uncertain) = wait(
        owner
            .advance_checkpoint_for_test(checkpoint, Some(original), 3, observed, move || {
                fs::set_permissions(changed_path, fs::Permissions::from_mode(0o644)).unwrap();
            })
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        uncertain,
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    let persisted = ExternalCheckpoint::decode(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(persisted.generation(), 2);
    assert_eq!(persisted.dispatch_owner_epoch(), 4);
    assert_eq!(persisted.clock_floor_millis(), 5000);
    assert_eq!(
        owner.failure(),
        Some(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    assert!(matches!(
        owner.advance_checkpoint(checkpoint, Some(persisted.clone()), 3, observed),
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    ));
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert!(retired.has_retired());
    assert_eq!(
        ExternalCheckpoint::decode(&fs::read(path).unwrap()).unwrap(),
        persisted
    );
}
