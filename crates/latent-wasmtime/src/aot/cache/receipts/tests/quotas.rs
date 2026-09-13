use super::*;

#[test]
fn read_owners_and_bytes_remain_charged_after_invalidation() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits {
        maximum_read_owners: 1,
        maximum_retained_read_bytes: 4,
        ..Default::default()
    });
    cache.publish(&key(1), b"four").unwrap();
    let owner = cache.lookup(&key(1)).unwrap().unwrap();
    assert_eq!(
        cache.lookup(&key(1)).err().unwrap().message,
        "native-receipt-cache-capacity"
    );
    cache.invalidate(&key(1)).unwrap();
    assert_eq!(cache.snapshot().retained_read_bytes, 4);
    assert_eq!(owner.as_bytes(), b"four");
    drop(owner);
    assert_eq!(cache.snapshot().retained_read_bytes, 0);
    assert_eq!(cache.snapshot().read_owners, 0);
}

#[test]
fn exact_entry_metadata_and_recovery_boundaries_do_not_evict_implicitly() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits {
        maximum_entries: 1,
        maximum_metadata_bytes: 8192 + 256,
        maximum_recovery_entries: 3,
        ..Default::default()
    });
    cache.publish(&key(1), b"one").unwrap();
    assert_eq!(cache.snapshot().metadata_bytes, 8192 + 256);
    assert_eq!(
        cache.publish(&key(2), b"two").err().unwrap().message,
        "native-receipt-cache-reclaimable-pressure"
    );
    assert!(cache.lookup(&key(1)).unwrap().is_some());
    let limits = cache.limits();
    drop(cache);
    let reopened = directory.open(limits);
    assert_eq!(reopened.snapshot().entries, 1);
}

#[test]
fn replacement_reserves_old_plus_new_and_oversize_never_reclaims() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits {
        maximum_disk_bytes: io::MARKER.len() as u64 + 40,
        maximum_receipt_bytes: 40,
        ..Default::default()
    });
    cache.publish(&key(1), &[1; 30]).unwrap();
    assert_eq!(
        cache.publish(&key(1), &[2; 11]).err().unwrap().message,
        "native-receipt-cache-reclaimable-pressure"
    );
    cache.publish(&key(1), &[2; 10]).unwrap();
    assert_eq!(
        cache.publish(&key(2), &[0; 41]).err().unwrap().message,
        "native-receipt-cache-capacity"
    );
    assert_eq!(cache.snapshot().entries, 1);
    assert_eq!(cache.snapshot().evictions, 0);
}

#[test]
fn recovery_counts_stage_bytes_and_fixed_inventory_files_before_cleanup() {
    let directory = Directory::new();
    drop(directory.open(AotReceiptCacheLimits::default()));
    std::fs::write(directory.0.join(io::STAGE), [1; 50]).unwrap();
    let small = AotReceiptCacheLimits {
        maximum_disk_bytes: 64,
        ..Default::default()
    };
    assert_eq!(
        ReceiptCache::open(&directory.0, small)
            .err()
            .unwrap()
            .message,
        "native-receipt-cache-capacity"
    );
    assert_eq!(
        std::fs::metadata(directory.0.join(io::STAGE))
            .unwrap()
            .len(),
        50
    );
    let few = AotReceiptCacheLimits {
        maximum_recovery_entries: 2,
        ..Default::default()
    };
    assert!(ReceiptCache::open(&directory.0, few).is_err());
    assert!(directory.0.join(io::STAGE).exists());
    drop(directory.open(AotReceiptCacheLimits::default()));
    assert!(!directory.0.join(io::STAGE).exists());
}

#[test]
fn impossible_owner_limits_and_path_bounds_reject_before_creation() {
    let directory = Directory::new();
    let child = directory.0.join("not-created");
    let limits = AotReceiptCacheLimits {
        maximum_metadata_bytes: 1,
        ..Default::default()
    };
    assert_eq!(
        ReceiptCache::open(&child, limits).err().unwrap().message,
        "native-receipt-cache-capacity"
    );
    assert!(!child.exists());
    assert!(ReceiptCache::open(
        &directory.0.join("x".repeat(4097)),
        AotReceiptCacheLimits::default()
    )
    .is_err());
    let invalid = AotReceiptCacheLimits {
        maximum_receipt_bytes: 8193,
        ..Default::default()
    };
    assert!(invalid.validate().is_err());
    let invalid = AotReceiptCacheLimits {
        maximum_receipt_bytes: 0,
        ..invalid
    };
    assert!(invalid.validate().is_err());
}
