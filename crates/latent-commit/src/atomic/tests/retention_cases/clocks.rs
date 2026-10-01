use super::*;

#[test]
fn uncertain_boot_regression_forward_jump_and_overflow_hold_all_retained_responses() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "clock-hold");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(1000, 10), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let samples = [
        observation(999, 11),
        observation(10_000, 11),
        observation(1100, 9),
        observation(u64::MAX, u64::MAX),
        MaintenanceClock {
            boot: [8; 32],
            ..observation(1100, 110)
        },
        MaintenanceClock {
            time: CommandTime {
                unix_millis: 1100,
                continuity_proven: false,
            },
            ..observation(1100, 110)
        },
    ];
    for sample in samples {
        assert_eq!(
            owner.step(&store, sample, maintenance),
            Err(AtomicError::RecoveryRequired)
        );
        assert_eq!(result_bytes(&store, &record), body);
    }
    let progress = owner
        .step(&store, observation(1100, 110), maintenance)
        .unwrap();
    assert_eq!(progress.retired, 1);
    assert!(matches!(
        inspect(
            &store.snapshot().unwrap(),
            &record.key,
            time(1099),
            permission
        ),
        Err(AtomicError::RecoveryRequired)
    ));
}

#[test]
fn boot_recovery_requires_exact_authorized_anchor_and_does_not_extend_original_horizons() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "boot-anchor");
    let owner = ResultMaintenanceOwner::default();
    let initial = owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let boot = MaintenanceClock {
        boot: [8; 32],
        ..observation(1100, 0)
    };
    assert_eq!(
        owner.anchor(&store, Some(initial.generation), boot, |_| Err(
            AtomicError::PermissionDenied
        )),
        Err(AtomicError::PermissionDenied)
    );
    assert_eq!(
        owner.anchor(&store, Some(initial.generation + 1), boot, maintenance),
        Err(AtomicError::Conflict)
    );
    let reanchored = owner
        .anchor(&store, Some(initial.generation), boot, maintenance)
        .unwrap();
    assert_eq!(result_bytes(&store, &record), body);
    assert_eq!(reanchored.retired, 0);
    owner
        .step(
            &store,
            MaintenanceClock {
                monotonic_millis: 1,
                time: time(1101),
                ..boot
            },
            maintenance,
        )
        .unwrap();
    let (protected, response) = inspect(
        &store.snapshot().unwrap(),
        &record.key,
        time(1101),
        permission,
    )
    .unwrap();
    assert!(response.is_none());
    assert_eq!(protected.result_expires, 1100);
    assert_eq!(protected.identity_expires, 2100);
}
