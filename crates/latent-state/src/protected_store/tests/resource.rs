use super::*;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
};
use latent_core::test_support::coordination::PauseTicket;
use std::os::unix::fs::{FileExt, OpenOptionsExt};
use std::sync::atomic::{AtomicBool, Ordering};

struct PausedFile {
    file: std::fs::File,
    gates: Rendezvous,
    notice: mpsc::Sender<PauseTicket>,
    destroyed: Arc<AtomicBool>,
}

impl Drop for PausedFile {
    fn drop(&mut self) {
        assert!(self.file.metadata().unwrap().is_file());
        let (registration, mut tracked) = self.gates.track(()).unwrap();
        tracked.commit(Stage::Entered).unwrap();
        let mut pause = Box::pin(tracked.pause());
        PollProbe::default().pending(pause.as_mut());
        self.notice
            .send(self.gates.blocked(registration, Stage::Entered).unwrap())
            .unwrap();
        block_on(pause);
        self.destroyed.store(true, Ordering::SeqCst);
        // Actual File destruction follows this destructor before keeper refund.
    }
}

#[test]
fn detached_native_resource_initializer_keeps_file_and_global_permit_until_actual_destruction() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner =
        wait(ProtectedStoreOwner::start_with_clock(config, Arc::new(clock.clone())).unwrap())
            .unwrap();
    let mut limits = NativeCapacityLimits::default();
    limits.recovery.slots = 1;
    let native = NativeCapacityOwner::with_clock(limits, Arc::new(clock.clone())).unwrap();
    owner.bind_native_capacity(&native).unwrap();
    let keeper = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 8192,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + std::time::Duration::from_secs(1),
            )
            .unwrap(),
    );
    let weak = Arc::downgrade(&keeper);
    let mut resource = owner.reserve_recovery_resource(8192, keeper).unwrap();
    let witness = resource.retirement_witness().unwrap();
    assert!(resource.retirement_witness().is_none());
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let destroyed = Arc::new(AtomicBool::new(false));
    let worker_destroyed = Arc::clone(&destroyed);
    let path = root.path().join("external-checkpoint");
    let job = owner
        .initialize_resource(resource, 1024, move |_| {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(path)
                .map_err(|_| StoreError::Unavailable)?;
            Ok(PausedFile {
                file,
                gates: worker_gates,
                notice,
                destroyed: worker_destroyed,
            })
        })
        .unwrap();
    drop(job); // Initialization and its detached resource response still execute.
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(std::time::Duration::from_secs(2));
    assert!(!witness.has_retired());
    assert!(!destroyed.load(Ordering::SeqCst));
    assert!(weak.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 1);
    owner.close();
    let mut drain = Box::pin(
        owner
            .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert!(!witness.has_retired());
    gates.release(ticket).unwrap();
    let report = wait(drain);
    assert!(report.clean);
    assert!(destroyed.load(Ordering::SeqCst));
    assert!(witness.has_retired());
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(report.snapshot.physical_owners, 0);
}

#[test]
fn recovery_native_resource_reads_progress_under_full_ordinary_worker_and_queue_pressure() {
    let (root, mut config) = fixture();
    config.io.queued_jobs = 1;
    let owner = start(config);
    let path = root.path().join("native-checkpoint");
    let resource = owner.reserve_recovery_resource(8192, Arc::new(())).unwrap();
    let (mut resource, initialized) = wait(
        owner
            .initialize_resource(resource, 1024, move |_| {
                let file = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .open(path)
                    .map_err(|_| StoreError::Unavailable)?;
                file.write_all_at(b"protected-floor", 0)
                    .map_err(|_| StoreError::Unavailable)?;
                Ok(file)
            })
            .unwrap(),
    )
    .unwrap();
    initialized.unwrap();
    let witness = resource.retirement_witness().unwrap();
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
    let caller = std::thread::current().id();
    let (resource, result) = wait(
        owner
            .with_resource(resource, StoreIoKind::RecoveryRead, 128, move |file, _| {
                assert_ne!(caller, std::thread::current().id());
                let mut bytes = [0; 15];
                file.read_exact_at(&mut bytes, 0)
                    .map_err(|_| StoreError::Unavailable)?;
                Ok(bytes)
            })
            .unwrap(),
    )
    .unwrap();
    assert_eq!(result.unwrap(), *b"protected-floor");
    wait(resource.retire());
    assert!(witness.has_retired());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 0);
    for ticket in tickets {
        gates.release(ticket).unwrap();
    }
    for job in jobs {
        wait(job).unwrap().unwrap();
    }
    wait(queued).unwrap().unwrap();
    assert!(finish(&owner).clean);
}

#[test]
fn native_resource_initialization_errors_and_foreign_or_ordinary_use_never_run_callbacks() {
    let (_root, config) = fixture();
    let owner = start(config);
    let (_other_root, other_config) = fixture();
    let other = start(other_config);
    let resource = owner
        .reserve_recovery_resource::<()>(512, Arc::new(()))
        .unwrap();
    let (mut resource, result) = wait(
        owner
            .initialize_resource(resource, 0, |_| Err(StoreError::Conflict))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        result,
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    assert!(owner.failure().is_none());
    let empty_witness = resource.retirement_witness().unwrap();
    assert!(matches!(
        owner.with_resource(
            resource,
            StoreIoKind::RecoveryRead,
            0,
            |(), _| -> Result<(), StoreError> { panic!("an uninitialized resource was used") }
        ),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    let resource = owner.reserve_recovery_resource(512, Arc::new(())).unwrap();
    let (mut resource, result) =
        wait(owner.initialize_resource(resource, 0, |_| Ok(())).unwrap()).unwrap();
    result.unwrap();
    let foreign_witness = resource.retirement_witness().unwrap();
    assert!(matches!(
        other.with_resource(
            resource,
            StoreIoKind::RecoveryRead,
            0,
            |(), _| -> Result<(), StoreError> {
                panic!("a foreign resource crossed the protected owner")
            }
        ),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    let resource = owner.reserve_recovery_resource(512, Arc::new(())).unwrap();
    let (mut resource, result) =
        wait(owner.initialize_resource(resource, 0, |_| Ok(())).unwrap()).unwrap();
    result.unwrap();
    let ordinary_witness = resource.retirement_witness().unwrap();
    assert!(matches!(
        owner.with_resource(
            resource,
            StoreIoKind::Read,
            0,
            |(), _| -> Result<(), StoreError> {
                panic!("a recovery resource was submitted as ordinary work")
            }
        ),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    assert!(finish(&owner).clean);
    assert!(finish(&other).clean);
    assert!(empty_witness.has_retired());
    assert!(foreign_witness.has_retired());
    assert!(ordinary_witness.has_retired());
}

#[test]
fn native_resource_operation_panic_retires_actual_file_and_keeps_recovery_quarantine_sticky() {
    let (root, config) = fixture();
    let owner = start(config);
    let resource = owner.reserve_recovery_resource(8192, Arc::new(())).unwrap();
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let destroyed = Arc::new(AtomicBool::new(false));
    let worker_destroyed = Arc::clone(&destroyed);
    let path = root.path().join("native-resource-panic");
    let (mut resource, result) = wait(
        owner
            .initialize_resource(resource, 1024, move |_| {
                let file = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .open(path)
                    .map_err(|_| StoreError::Unavailable)?;
                Ok(PausedFile {
                    file,
                    gates: worker_gates,
                    notice,
                    destroyed: worker_destroyed,
                })
            })
            .unwrap(),
    )
    .unwrap();
    result.unwrap();
    let witness = resource.retirement_witness().unwrap();
    let job = owner
        .with_resource(
            resource,
            StoreIoKind::RecoveryRead,
            0,
            |_, _| -> Result<(), StoreError> {
                panic!("resource operation panic has no successful completion")
            },
        )
        .unwrap();
    assert_eq!(wait(job).err(), Some(StoreIoError::RecoveryRequired));
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    assert!(!witness.has_retired());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    assert!(owner.snapshot().unwrap().quarantined);
    gates.release(ticket).unwrap();
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert!(report.snapshot.quarantined);
    assert!(destroyed.load(Ordering::SeqCst));
    assert!(witness.has_retired());
}
