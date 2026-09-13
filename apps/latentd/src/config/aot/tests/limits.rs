use super::*;
const MIB: usize = 1024 * 1024;

#[test]
fn defaults_and_checked_aggregate_limits_cover_the_real_owners() {
    let directory = TempDir::new().unwrap();
    let config = parsed(directory.path());
    let (process, raw, receipts, images) = check_limits(&config).unwrap();
    assert_eq!(process.resources.maximum_jobs, 1);
    assert_eq!(
        process.resources.maximum_input_bytes,
        config.limits.maximum_component_bytes
    );
    assert_eq!(process.resources.maximum_native_bytes, 128 * MIB);
    assert_eq!(process.sandbox.cpu_seconds, 30);
    assert_eq!(raw.maximum_object_bytes, 128 * MIB as u64);
    assert!(raw.maximum_staging_bytes >= raw.maximum_object_bytes);
    assert!(raw.maximum_read_bytes >= raw.maximum_object_bytes);
    assert_eq!(receipts.maximum_entries, raw.maximum_entries);
    assert_eq!(receipts.maximum_receipt_bytes, 8192);
    assert_eq!(images.maximum_image_bytes, 128 * MIB);
    assert_eq!(images.maximum_total_bytes, 256 * MIB);
    assert_eq!(images.maximum_images, 64);
}

#[test]
fn invalid_and_impossible_combinations_reject_instead_of_raising_budgets() {
    let directory = TempDir::new().unwrap();
    for (group, name, value) in [
        ("process", "maximumOutputBytes", 0_u64),
        ("process", "maximumOutputBytes", 256 * MIB as u64 + 1),
        ("process", "jobTimeoutMillis", 300_001),
        ("process", "addressSpaceBytes", 4 * 1024 * MIB as u64 + 1),
        ("cache", "entries", 16_385),
        ("cache", "diskBytes", 128 * MIB as u64 - 1),
        ("cache", "diskBytes", 4 * 1024 * MIB as u64 + 1),
        ("images", "maximumImages", 4097),
        ("images", "maximumImageBytes", 128 * MIB as u64 - 1),
        ("images", "maximumTotalBytes", 1024 * MIB as u64 + 1),
    ] {
        let mut value_doc = document(directory.path());
        value_doc["isolatedAot"][group] = json!({(name):value});
        let config: NodeConfig = serde_json::from_value(value_doc).unwrap();
        assert!(check_limits(&config).is_err(), "{group}.{name}");
    }
    let mut config = parsed(directory.path());
    config.cache.preparations = 8;
    let aot = config.isolated_aot.as_mut().unwrap();
    aot.process.maximum_output_bytes = 256 * MIB;
    aot.images.maximum_image_bytes = 256 * MIB;
    aot.cache.disk_bytes = 512 * MIB as u64;
    assert!(check_limits(&config).is_err()); // 2 GiB exceeds the 1 GiB hard cap.
    config.cache.preparations = 4;
    let (process, _, _, _) = check_limits(&config).unwrap();
    assert_eq!(process.resources.maximum_native_bytes, 1024 * MIB);
}

#[test]
fn lowered_subpage_output_still_requires_a_complete_mapping_page() {
    let directory = TempDir::new().unwrap();
    let mut config = parsed(directory.path());
    let aot = config.isolated_aot.as_mut().unwrap();
    aot.process.maximum_output_bytes = 1;
    aot.images.maximum_image_bytes = 1;
    assert!(check_limits(&config).is_err());
    config
        .isolated_aot
        .as_mut()
        .unwrap()
        .images
        .maximum_image_bytes = 65_536;
    assert!(check_limits(&config).is_ok());
}

#[test]
fn small_receipt_caches_reserve_marker_lock_and_stage_inventory() {
    let directory = TempDir::new().unwrap();
    for entries in [1, 2, 1024, 16_384] {
        let mut config = parsed(directory.path());
        config.isolated_aot.as_mut().unwrap().cache.entries = entries;
        let (_, raw, receipts, _) = check_limits(&config).unwrap();
        assert_eq!(raw.maximum_recovery_entries, 2 * entries);
        assert_eq!(
            receipts.maximum_recovery_entries,
            (2 * entries).max(entries + 3)
        );
        assert!(receipts.maximum_recovery_entries <= 32_768);
    }
}
