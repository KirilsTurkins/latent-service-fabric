use super::*;
use latent_core::{
    authority_rejection::AuthorityRejection,
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservation, NativeReservationRequest,
    },
    test_support::TestClock,
    ActivationClock,
};

struct Fixture {
    native: NativeCapacityOwner,
    clock: TestClock,
    resident: Arc<NativeReservation>,
    caller: Arc<NativeReservation>,
    owner: EffectAuthorityOwner,
}
impl Fixture {
    fn new() -> Self {
        let clock = TestClock::new(100, Instant::now(), 1);
        let native = NativeCapacityOwner::with_clock(
            NativeCapacityLimits::default(),
            Arc::new(clock.clone()),
        )
        .unwrap();
        let reserve = |bytes| {
            Arc::new(
                native
                    .reserve(
                        NativeAdmissionClass::Recovery,
                        NativeReservationRequest {
                            work_bytes: bytes,
                            ..NativeReservationRequest::default()
                        },
                        clock.monotonic_now() + Duration::from_secs(10),
                    )
                    .unwrap(),
            )
        };
        let resident = reserve(EffectAuthorityOwner::retained_memory_bytes(2).unwrap());
        let caller = reserve(2 * EffectControlGeneration::METADATA_BYTES);
        let owner =
            EffectAuthorityOwner::with_retained_capacity(2, 2, 100, &native, Arc::clone(&resident))
                .unwrap();
        Self {
            native,
            clock,
            resident,
            caller,
            owner,
        }
    }
    fn capture(&self) -> Result<EffectControlGeneration, AuthorityError> {
        self.owner
            .capture_control_generation(&self.native, Arc::clone(&self.caller), time(100))
    }
}

#[test]
fn actual_retained_rules_refuse_unpaid_foreign_and_oversized_owned_capacities() {
    let fixture = Fixture::new();
    assert!(fixture.owner.uses_native_capacity(&fixture.native));
    assert_eq!(
        EffectAuthorityOwner::retained_memory_bytes(128),
        Ok(2_113_536)
    );
    assert!(EffectAuthorityOwner::with_retained_capacity(
        2,
        2,
        100,
        &fixture.native,
        Arc::clone(&fixture.caller)
    )
    .is_err());
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    assert!(EffectAuthorityOwner::with_retained_capacity(
        2,
        2,
        100,
        &foreign,
        Arc::clone(&fixture.resident)
    )
    .is_err());
    let unretained = EffectAuthorityOwner::new(2, 2, 100).unwrap();
    assert!(unretained
        .capture_control_generation(&fixture.native, Arc::clone(&fixture.caller), time(100))
        .is_err());
    let mut oversized = rule();
    oversized.profile.destination = String::with_capacity(512);
    oversized.profile.destination.push_str("actual-destination");
    assert!(oversized.valid());
    assert_eq!(fixture.owner.publish(oversized.clone()), Ok(()));
    // A clone has a fresh compact allocation; the actual moved oversized
    // producer value is refused without retaining its spare physical capacity.
    oversized.policy_revision = 2;
    assert_eq!(
        fixture.owner.publish(oversized),
        Err(AuthorityError::Capacity)
    );
    assert_eq!(fixture.owner.0.state.lock().unwrap().generation, 2);
    let mut legacy = rule();
    legacy.profile.destination = String::with_capacity(512);
    legacy.profile.destination.push_str("legacy-destination");
    unretained.publish(legacy).unwrap();
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 2);
}

#[test]
fn real_rule_rotation_namespace_close_and_observer_rejection_invalidate_original_capture() {
    let fixture = Fixture::new();
    let mut installed = rule();
    fixture.owner.publish(installed.clone()).unwrap();
    let captured = fixture.capture().unwrap();
    fixture
        .owner
        .with_control_generation(&captured, time(100), || ())
        .unwrap();
    let original_generation = captured.rules_generation();
    installed.policy_revision = 2;
    installed.credential_epoch = 2;
    installed.protected_credential_reference = "rotated-provider".into();
    fixture.owner.publish(installed.clone()).unwrap();
    assert_eq!(
        fixture
            .owner
            .with_control_generation(&captured, time(100), || ()),
        Err(AuthorityError::Stale)
    );
    drop(captured);
    let fresh = fixture.capture().unwrap();
    assert!(fresh.rules_generation() > original_generation);
    fixture.owner.publish(installed.clone()).unwrap();
    fixture
        .owner
        .with_control_generation(&fresh, time(100), || ())
        .unwrap();
    let foreign = EffectAuthorityOwner::new(2, 2, 100).unwrap();
    foreign.publish(installed).unwrap();
    assert_eq!(
        foreign.with_control_generation(&fresh, time(100), || ()),
        Err(AuthorityError::Stale)
    );
    fixture
        .owner
        .rejection_observer()
        .reject(AuthorityRejection::Publication {
            tenant: Some("tenant-a"),
            publication: "publication-a",
        })
        .unwrap();
    assert!(fixture
        .owner
        .with_control_generation(&fresh, time(100), || ())
        .is_err());
    assert!(fixture.capture().is_err());
    drop(fresh);
    let mut replacement = rule();
    replacement.policy_revision = 3;
    replacement.credential_epoch = 3;
    fixture.owner.publish(replacement).unwrap();
    let current = fixture.capture().unwrap();
    fixture
        .owner
        .prepare_namespace_close("tenant-a", "orders", 1)
        .unwrap()
        .accept(|| Ok::<_, ()>(()))
        .unwrap();
    assert_eq!(
        fixture
            .owner
            .with_control_generation(&current, time(100), || ()),
        Err(AuthorityError::Stale)
    );
}

#[test]
fn empty_rule_map_still_requires_original_unretired_policy_catalog_observer_generation() {
    let fixture = Fixture::new();
    let captured = fixture.capture().unwrap();
    assert_eq!(captured.rules_generation(), 1);
    fixture
        .owner
        .rejection_observer()
        .reject(AuthorityRejection::PolicyTenant("not-installed"))
        .unwrap();
    assert_eq!(fixture.owner.0.state.lock().unwrap().generation, 1);
    assert!(fixture
        .owner
        .with_control_generation(&captured, time(100), || ())
        .is_err());
    drop(captured);
    let current = fixture.capture().unwrap();
    fixture
        .owner
        .with_control_generation(&current, time(100), || ())
        .unwrap();
    fixture
        .owner
        .rejection_observer()
        .reject(AuthorityRejection::OwnerRetired)
        .unwrap();
    assert!(fixture
        .owner
        .with_control_generation(&current, time(100), || ())
        .is_err());
    assert!(fixture.capture().is_err());
}

#[test]
fn original_control_capture_deadline_close_busy_clock_and_finite_metadata_never_readmit() {
    let fixture = Fixture::new();
    let first = fixture.capture().unwrap();
    let second = fixture.capture().unwrap();
    assert!(fixture.capture().is_err());
    drop(second);
    {
        let _busy = fixture.owner.0.state.try_lock().unwrap();
        assert!(fixture.capture().is_err());
        assert_eq!(
            fixture
                .owner
                .with_control_generation(&first, time(100), || ()),
            Err(AuthorityError::Unavailable)
        );
    }
    let returned = fixture
        .caller
        .reserve_buffer(
            NativeBufferClass::Work,
            EffectControlGeneration::METADATA_BYTES,
        )
        .unwrap();
    drop(returned);
    assert_eq!(
        fixture
            .owner
            .with_control_generation(&first, time(101), || ()),
        Ok(())
    );
    assert_eq!(
        fixture
            .owner
            .with_control_generation(&first, time(100), || ()),
        Err(AuthorityError::ClockDiscontinuity)
    );
    assert_eq!(
        fixture.owner.with_control_generation(
            &first,
            EffectTime {
                unix_millis: 102,
                continuity_proven: false
            },
            || ()
        ),
        Err(AuthorityError::ClockDiscontinuity)
    );
    fixture.clock.advance(Duration::from_secs(10));
    assert_eq!(
        fixture
            .owner
            .with_control_generation(&first, time(101), || ()),
        Err(AuthorityError::Expired)
    );
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 2);
    let closed = Fixture::new();
    let captured = closed.capture().unwrap();
    closed.native.close();
    assert!(closed
        .owner
        .with_control_generation(&captured, time(100), || ())
        .is_err());
    assert!(closed.capture().is_err());
    assert_eq!(closed.native.snapshot().unwrap().recovery.slots, 2);
}

#[test]
fn resident_rule_map_and_original_caller_retire_only_after_last_actual_capture_drop() {
    let fixture = Fixture::new();
    fixture.owner.publish(rule()).unwrap();
    let captured = fixture.capture().unwrap();
    let resident = Arc::downgrade(&fixture.resident);
    let caller = Arc::downgrade(&fixture.caller);
    let native = fixture.native.clone();
    drop(fixture);
    assert!(resident.upgrade().is_some());
    assert!(caller.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 2);
    drop(captured);
    assert!(resident.upgrade().is_none());
    assert!(caller.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
}
