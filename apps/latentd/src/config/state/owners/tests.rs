use super::*;

pub(in crate::config::state) fn input() -> serde_json::Value {
    serde_json::json!({
        "store": {
            "maximumFileBytes":268_435_456,"cacheBytes":8_388_608,"maximumRows":16_384,
            "maximumLogicalBytes":33_554_432,"maximumReadViews":8,"maximumViewAgeMillis":30_000,
            "ordinary":{"workers":3,"queuedJobs":8,"acceptedJobs":32,"activeReads":2,
                "retainedBytes":117_440_512,"maximumJobBytes":41_943_040},
            "recovery":{"workers":1,"queuedJobs":4,"acceptedJobs":8,
                "retainedBytes":16_777_216,"maximumJobBytes":8_396_800}
        },
        "native": {
            "ordinary":{"slots":128,"bytes":268_435_456,"maximumReservationBytes":67_108_864},
            "recovery":{"slots":8,"bytes":100_663_296,"maximumReservationBytes":33_554_432},
            "maximumLifetimeMillis":180_000
        },
        "dispatcher":{"workers":2,"queuedJobs":4,"acceptedJobs":16,"maximumCommandOwners":128,
            "perTenantJobs":1,"retainedBytes":83_886_080,"pageRows":16,"pageBytes":1_048_576,
            "scanPagesPerTick":4,"pollIntervalMillis":100}
    })
}

#[test]
fn explicit_limits_keep_reserved_recovery_and_production_record_framing() {
    let value = input();
    let storage: StorageLimitsConfig = serde_json::from_value(value["store"].clone()).unwrap();
    let config = storage
        .derive(std::env::temp_dir().join("state-settings/state"), false)
        .unwrap();
    assert_eq!(config.io.workers, 4);
    let recovery = config.io.recovery.unwrap();
    assert_eq!(
        (
            recovery.workers,
            recovery.queued_jobs,
            recovery.accepted_jobs
        ),
        (1, 4, 8)
    );
    assert_eq!(recovery.job_bytes, 8 * MIB + 8192);
    assert_eq!(
        config.io.retained_bytes - recovery.retained_bytes,
        storage.ordinary.retained_bytes
    );
    assert_eq!(
        (
            config.engine.maximum_key_bytes,
            config.engine.maximum_value_bytes,
            config.engine.maximum_batch_rows
        ),
        (4096, 2 * 1024 * 1024, 1024)
    );
    let dispatch: DispatcherLimitsConfig =
        serde_json::from_value(value["dispatcher"].clone()).unwrap();
    let config = dispatch.derive().unwrap();
    assert!(config.start_paused);
    assert_eq!(config.ordering, DispatchOrdering::Unordered);
}

#[test]
fn recovery_limits_cannot_be_consumed_by_ordinary_work_or_below_actual_frame_bounds() {
    for (section, field, value) in [
        ("ordinary", "workers", 1),
        ("ordinary", "activeReads", 3),
        ("ordinary", "acceptedJobs", 7),
        ("ordinary", "maximumJobBytes", 40 * MIB - 1),
        ("recovery", "workers", 0),
        ("recovery", "queuedJobs", 3),
        ("recovery", "acceptedJobs", 7),
        ("recovery", "maximumJobBytes", 8 * MIB + 8191),
    ] {
        let mut wire = input()["store"].clone();
        wire[section][field] = value.into();
        let config: StorageLimitsConfig = serde_json::from_value(wire).unwrap();
        assert!(
            config
                .derive(std::env::temp_dir().join("state-settings/state"), false)
                .is_err(),
            "{section}.{field}"
        );
    }
    let mut config: StorageLimitsConfig = serde_json::from_value(input()["store"].clone()).unwrap();
    config.ordinary.retained_bytes = 64 * MIB;
    config.ordinary.maximum_job_bytes = 64 * MIB;
    assert!(config
        .derive(std::env::temp_dir().join("state-settings/state"), false)
        .is_err());
}

#[test]
fn native_reservations_include_full_wire_copies_and_original_startup_lifetime() {
    let mut config: NativeLimitsConfig = serde_json::from_value(input()["native"].clone()).unwrap();
    let limits = config.derive(Duration::from_mins(1)).unwrap();
    assert_eq!(limits.recovery.maximum_reservation_bytes, 32 * MIB);
    config.recovery.maximum_reservation_bytes = 32 * MIB - 1;
    assert!(config.derive(Duration::from_mins(1)).is_err());
    config.recovery.maximum_reservation_bytes = 32 * MIB;
    config.maximum_lifetime_millis = 59_999;
    assert!(config.derive(Duration::from_mins(1)).is_err());
    config.maximum_lifetime_millis = u64::MAX;
    assert!(config.derive(Duration::from_mins(1)).is_err());
}

#[test]
fn resident_startup_owner_cannot_consume_the_last_full_recovery_slot_or_byte_envelope() {
    let declared = input();
    let storage: StorageLimitsConfig = serde_json::from_value(declared["store"].clone()).unwrap();
    let store = storage
        .derive(std::env::temp_dir().join("state-settings/state"), false)
        .unwrap();
    let native: NativeLimitsConfig = serde_json::from_value(declared["native"].clone()).unwrap();
    let mut limits = native.derive(Duration::from_secs(5)).unwrap();
    let work = startup_footprint(&store, limits).unwrap();
    assert_eq!(
        work,
        store
            .startup_memory_bytes(super::super::STARTUP_VALIDATOR_BYTES)
            .unwrap()
            + super::super::STARTUP_APPLICATION_BYTES
            + effect_metadata_bytes().unwrap()
    );
    assert!(work > 24 * MIB);
    limits.recovery.slots = 1;
    assert!(startup_footprint(&store, limits).is_err());
    limits.recovery.slots = 2;
    limits.recovery.bytes = work + NATIVE_RESERVATION_METADATA_BYTES + 32 * MIB - 1;
    assert!(startup_footprint(&store, limits).is_err());
    limits.recovery.bytes += 1;
    assert_eq!(startup_footprint(&store, limits), Ok(work));
    limits.ordinary.maximum_reservation_bytes = 32 * MIB;
    assert!(startup_footprint(&store, limits).is_err());
}

#[test]
fn reviewed_explicit_native_profile_is_finite_and_large_cache_startup_requires_its_own_capacity() {
    let declared = input();
    let mut storage: StorageLimitsConfig =
        serde_json::from_value(declared["store"].clone()).unwrap();
    let native = NativeLimitsConfig::default()
        .derive(Duration::from_mins(1))
        .unwrap();
    assert_eq!(native.recovery.bytes, 96 * MIB);
    assert_eq!(native.recovery.maximum_reservation_bytes, 32 * MIB);
    storage.cache_bytes = 64 * 1024 * 1024;
    let store = storage
        .derive(std::env::temp_dir().join("state-settings/state"), false)
        .unwrap();
    assert!(startup_footprint(&store, native).is_err());
    let mut adequate = native;
    adequate.recovery.maximum_reservation_bytes = 96 * MIB;
    adequate.recovery.bytes = 128 * MIB;
    assert!(startup_footprint(&store, adequate).is_ok());
}

#[test]
fn owner_declarations_reject_unknown_permission_flags_and_missing_partitions() {
    for (name, unknown) in [
        ("store", "continuityProven"),
        ("native", "grant"),
        ("dispatcher", "startPaused"),
    ] {
        let mut wire = input()[name].clone();
        wire[unknown] = true.into();
        let refused = match name {
            "store" => serde_json::from_value::<StorageLimitsConfig>(wire).is_err(),
            "native" => serde_json::from_value::<NativeLimitsConfig>(wire).is_err(),
            "dispatcher" => serde_json::from_value::<DispatcherLimitsConfig>(wire).is_err(),
            _ => unreachable!(),
        };
        assert!(refused);
    }
    let mut wire = input()["native"].clone();
    wire.as_object_mut().unwrap().remove("recovery");
    assert!(serde_json::from_value::<NativeLimitsConfig>(wire).is_err());
    let mut wire = input()["store"].clone();
    wire["recovery"] = serde_json::Value::Null;
    assert!(serde_json::from_value::<StorageLimitsConfig>(wire).is_err());
    assert!(
        serde_json::from_value::<NativePartitionConfig>(serde_json::json!([
            8, 33_554_432, 33_554_432
        ]))
        .is_err()
    );
    assert!(
        serde_json::from_value::<StorageRecoveryConfig>(serde_json::json!([
            1, 4, 8, 16_777_216, 8_396_800
        ]))
        .is_err()
    );
    assert!(
        serde_json::from_value::<StorageWorkerConfig>(serde_json::json!([
            3,
            8,
            32,
            2,
            117_440_512,
            41_943_040
        ]))
        .is_err()
    );
}
