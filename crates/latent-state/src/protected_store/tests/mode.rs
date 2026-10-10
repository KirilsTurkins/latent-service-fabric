use super::*;

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservation,
    NativeReservationRequest,
};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

use crate::store_identity::StoreIdentity;

fn identity() -> StoreIdentity {
    StoreIdentity::new("mode-store".into()).unwrap()
}

fn bound(config: ProtectedStoreConfig, clock: &TestClock) -> ProtectedStoreOwner {
    let owner = wait(
        ProtectedStoreOwner::start_bound_validated_view_with_clock(
            config,
            identity(),
            4096,
            |view| super::super::physical::validate_records(view, &mut StoreIdentity::validate_row),
            Arc::new(clock.clone()),
        )
        .unwrap(),
    )
    .unwrap();
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    owner.bind_native_capacity(&native).unwrap();
    owner
}

fn original(owner: &ProtectedStoreOwner, clock: &TestClock) -> Arc<NativeReservation> {
    Arc::new(
        owner
            .native_capacity()
            .unwrap()
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 64 * 1024,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + WATCHDOG,
            )
            .unwrap(),
    )
}

fn marker(owner: &ProtectedStoreOwner, clock: &TestClock) -> StateModeObservation {
    wait(
        owner
            .ensure_state_mode_marker(identity(), original(owner, clock))
            .unwrap(),
    )
    .unwrap()
    .unwrap()
}

#[test]
fn fresh_identity_persists_closed_mode_without_consuming_the_checkpoint_witness() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config, &clock);
    assert!(marker(&owner, &clock).created_here);
    let path = root.path().join(STATE_MODE_FILE);
    assert_eq!(
        fs::read(&path).unwrap(),
        super::super::mode::encoded(&identity())
    );
    assert_eq!(
        fs::metadata(&path).unwrap().permissions().mode() & 0o7777,
        0o600
    );
    let fresh = wait(owner.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(fresh.identity(), &identity());
    assert!(wait(owner.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
        .is_none());
    assert!(!marker(&owner, &clock).created_here);
    assert!(finish(&owner).clean);
}

#[test]
fn fresh_identity_with_prior_business_rows_refuses_mode_io_without_consuming_its_witness() {
    for family in [Family::State, Family::Maintenance] {
        let (root, config) = fixture();
        let clock = TestClock::new(1000, Instant::now(), 1);
        let owner = bound(config, &clock);
        // A value larger than the entire mode reservation proves that the
        // freshness check must observe presence without copying that value.
        wait(
            owner
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: key(family, "premature-business-write"),
                        value: Some(vec![7; 64 * 1024]),
                    }],
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(
            wait(
                owner
                    .ensure_state_mode_marker(identity(), original(&owner, &clock))
                    .unwrap(),
            )
            .unwrap(),
            Err(ProtectedStoreError::Store(StoreError::Conflict))
        );
        assert!(!root.path().join(STATE_MODE_FILE).exists());
        assert!(!owner.snapshot().unwrap().quarantined);
        let fresh = wait(owner.take_initialization_witness().unwrap())
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(fresh.identity(), &identity());
        assert!(finish(&owner).clean);
    }
}

#[test]
fn matching_reopen_verifies_mode_byte_exactly_without_replacing_its_named_inode() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config.clone(), &clock);
    assert!(marker(&owner, &clock).created_here);
    let path = root.path().join(STATE_MODE_FILE);
    let bytes = fs::read(&path).unwrap();
    let inode = fs::metadata(&path).unwrap().ino();
    assert!(finish(&owner).clean);
    drop(owner);
    let reopened = bound(config, &clock);
    assert!(wait(reopened.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
        .is_none());
    assert!(!marker(&reopened, &clock).created_here);
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(fs::metadata(&path).unwrap().ino(), inode);
    assert!(finish(&reopened).clean);
}

#[test]
fn matching_identity_after_reopen_cannot_recreate_a_missing_mode_leaf() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config.clone(), &clock);
    assert!(finish(&owner).clean);
    drop(owner);
    let reopened = bound(config, &clock);
    let result = wait(
        reopened
            .ensure_state_mode_marker(identity(), original(&reopened, &clock))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        result,
        Err(ProtectedStoreError::Store(StoreError::Unavailable))
    );
    assert!(!root.path().join(STATE_MODE_FILE).exists());
    assert!(reopened.snapshot().unwrap().quarantined);
    assert!(finish(&reopened).snapshot.physically_retired());
}

#[test]
fn fresh_initialization_never_overwrites_an_existing_failed_or_mismatched_mode() {
    for malformed in [
        Vec::new(),
        b"LSM\0\x02bad".to_vec(),
        super::super::mode::encoded(&StoreIdentity::new("foreign-store".into()).unwrap()),
    ] {
        let (root, config) = fixture();
        let path = root.path().join(STATE_MODE_FILE);
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        std::io::Write::write_all(&mut file, &malformed).unwrap();
        drop(file);
        let clock = TestClock::new(1000, Instant::now(), 1);
        let owner = bound(config, &clock);
        assert!(wait(
            owner
                .ensure_state_mode_marker(identity(), original(&owner, &clock))
                .unwrap()
        )
        .unwrap()
        .is_err());
        assert_eq!(fs::read(&path).unwrap(), malformed);
        assert!(finish(&owner).snapshot.physically_retired());
    }
}

#[test]
fn foreign_global_capacity_and_different_persisted_identity_refuse_without_mode_io() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config, &clock);
    let foreign =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    let wrong = Arc::new(
        foreign
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 64 * 1024,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + WATCHDOG,
            )
            .unwrap(),
    );
    assert!(matches!(
        owner.ensure_state_mode_marker(identity(), wrong),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    let other = StoreIdentity::new("other-store".into()).unwrap();
    assert_eq!(
        wait(
            owner
                .ensure_state_mode_marker(other, original(&owner, &clock))
                .unwrap()
        )
        .unwrap(),
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    assert!(!root.path().join(STATE_MODE_FILE).exists());
    assert!(!owner.snapshot().unwrap().quarantined);
    assert!(finish(&owner).clean);
}

#[test]
fn expired_original_recovery_capacity_cannot_create_a_mode_marker_or_refresh_its_deadline() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config, &clock);
    let permit = original(&owner, &clock);
    clock.advance(WATCHDOG + std::time::Duration::from_secs(1));
    assert!(matches!(
        owner.ensure_state_mode_marker(identity(), permit),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    assert!(!root.path().join(STATE_MODE_FILE).exists());
    assert!(!owner.snapshot().unwrap().quarantined);
    // The refused mode operation gets no replacement grant. This separate
    // test-owned engine cleanup only observes destruction of the old fixture.
    assert!(
        wait(
            owner
                .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
                .unwrap()
        )
        .clean
    );
}

#[test]
fn detached_mode_waiter_keeps_original_capacity_until_actual_file_retirement() {
    let (root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let owner = bound(config, &clock);
    let native = owner.native_capacity().unwrap();
    let permit = original(&owner, &clock);
    let weak = Arc::downgrade(&permit);
    let gates = Rendezvous::new(1);
    let worker = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .ensure_state_mode_marker_inner(identity(), Arc::clone(&permit), move || {
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut paused = Box::pin(physical.pause());
            PollProbe::default().pending(paused.as_mut());
            notice
                .send((
                    std::thread::current().id(),
                    worker.blocked(registration, Stage::Entered).unwrap(),
                ))
                .unwrap();
            block_on(paused);
        })
        .unwrap();
    let (worker_id, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_ne!(worker_id, std::thread::current().id());
    assert!(root.path().join(STATE_MODE_FILE).exists());
    drop(job);
    drop(permit);
    assert!(weak.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 1);
    owner.close();
    gates.release(ticket).unwrap();
    let report = finish(&owner);
    assert!(report.clean && report.snapshot.physically_retired());
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
}
