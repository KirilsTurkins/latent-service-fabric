use super::*;

#[test]
fn each_failed_stage_retains_one_reservation_until_reclaimed() {
    for point in [
        io::Cutpoint::Create,
        io::Cutpoint::PartialWrite,
        io::Cutpoint::FileSync,
        io::Cutpoint::Rename,
    ] {
        let directory = Directory::new();
        let cache = directory.open(AotReceiptCacheLimits::default());
        for _ in 0..3 {
            fail(point);
            assert!(cache.publish(&key(1), b"bounded receipt").is_err());
            let snapshot = cache.snapshot();
            assert_eq!(snapshot.entries, 0);
            assert_eq!(snapshot.reserved_disk_bytes, 15);
            assert_eq!(snapshot.staging_bytes, 15);
            assert_eq!(snapshot.active_work, 0);
            assert_eq!(
                cache.publish(&key(2), b"other").err().unwrap().message,
                "native-receipt-cache-reclaimable-pressure"
            );
            assert!(cache.reclaim(1).unwrap().staging_reclaimed);
            assert_eq!(cache.snapshot().reserved_disk_bytes, 0);
            assert_eq!(std::fs::read_dir(&directory.0).unwrap().count(), 2);
        }
    }
}

#[test]
fn replacement_rename_sync_failure_never_claims_rollback_or_refunds() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    cache.publish(&key(1), b"old").unwrap();
    let resident = cache.snapshot().resident_disk_bytes;
    fail(io::Cutpoint::DirectorySync);
    assert_eq!(
        cache
            .publish(&key(1), b"replacement")
            .err()
            .unwrap()
            .message,
        "native-receipt-cache-durability-uncertain"
    );
    assert_eq!(cache.snapshot().resident_disk_bytes, resident);
    assert_eq!(cache.snapshot().reserved_disk_bytes, 11);
    assert_eq!(cache.snapshot().staging_bytes, 0);
    assert_eq!(
        cache.lookup(&key(1)).err().unwrap().message,
        "native-receipt-cache-durability-uncertain"
    );
    assert!(cache.reclaim(1).unwrap().staging_reclaimed);
    assert_eq!(
        cache.lookup(&key(1)).unwrap().unwrap().as_bytes(),
        b"replacement"
    );
    assert_eq!(
        cache.snapshot().resident_disk_bytes,
        io::MARKER.len() as u64 + 11
    );
    assert_eq!(cache.snapshot().reserved_disk_bytes, 0);
}

#[test]
fn unlink_and_parent_sync_failures_retain_exact_deletion_charge() {
    for point in [io::Cutpoint::Unlink, io::Cutpoint::DirectorySync] {
        let directory = Directory::new();
        let cache = directory.open(AotReceiptCacheLimits::default());
        cache.publish(&key(1), b"receipt").unwrap();
        let before = cache.snapshot().resident_disk_bytes;
        fail(point);
        assert!(cache.invalidate(&key(1)).is_err());
        assert_eq!(cache.snapshot().resident_disk_bytes, before);
        assert_eq!(cache.snapshot().deletion_pending_bytes, 7);
        assert_eq!(cache.reclaim(1).unwrap().removed_entries, 1);
        assert_eq!(
            cache.snapshot().resident_disk_bytes,
            io::MARKER.len() as u64
        );
        assert_eq!(cache.snapshot().deletion_pending_bytes, 0);
    }
}

#[test]
fn abandoned_stage_recovery_is_bounded_and_never_adopts_bytes() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    fail(io::Cutpoint::PartialWrite);
    assert!(cache.publish(&key(1), b"uncommitted").is_err());
    drop(cache);
    let reopened = directory.open(AotReceiptCacheLimits::default());
    assert!(reopened.lookup(&key(1)).unwrap().is_none());
    assert!(!directory.0.join(io::STAGE).exists());
    assert_eq!(
        reopened.snapshot().resident_disk_bytes,
        io::MARKER.len() as u64
    );
}

#[test]
fn initialization_cutpoints_recover_only_registered_prefixes() {
    for point in [
        io::Cutpoint::PartialWrite,
        io::Cutpoint::FileSync,
        io::Cutpoint::Rename,
        io::Cutpoint::DirectorySync,
    ] {
        let directory = Directory::new();
        fail(point);
        assert!(ReceiptCache::open(&directory.0, AotReceiptCacheLimits::default()).is_err());
        let cache = directory.open(AotReceiptCacheLimits::default());
        assert_eq!(cache.snapshot().entries, 0);
        assert_eq!(std::fs::read_dir(&directory.0).unwrap().count(), 2);
    }
}

#[test]
fn unknown_files_and_symlinks_are_preserved_on_open_and_delete() {
    use std::os::unix::fs::symlink;
    let directory = Directory::new();
    std::fs::write(directory.0.join("unknown"), b"preserve").unwrap();
    assert!(ReceiptCache::open(&directory.0, AotReceiptCacheLimits::default()).is_err());
    assert_eq!(
        std::fs::read(directory.0.join("unknown")).unwrap(),
        b"preserve"
    );
    std::fs::remove_file(directory.0.join("unknown")).unwrap();
    let cache = directory.open(AotReceiptCacheLimits::default());
    cache.publish(&key(1), b"receipt").unwrap();
    std::fs::remove_file(directory.0.join(filename(1))).unwrap();
    symlink("missing-target", directory.0.join(filename(1))).unwrap();
    assert!(cache.invalidate(&key(1)).is_err());
    assert!(std::fs::symlink_metadata(directory.0.join(filename(1)))
        .unwrap()
        .file_type()
        .is_symlink());
    drop(cache);
    assert!(ReceiptCache::open(&directory.0, AotReceiptCacheLimits::default()).is_err());
}

#[test]
fn root_links_and_unowned_final_rows_are_rejected_without_adoption() {
    use std::os::unix::fs::symlink;
    let directory = Directory::new();
    let link = directory.0.join("link");
    symlink(&directory.0, &link).unwrap();
    assert!(ReceiptCache::open(&link.join("new"), AotReceiptCacheLimits::default()).is_err());
    assert!(!directory.0.join("new").exists());
    std::fs::remove_file(link).unwrap();
    std::fs::write(directory.0.join(filename(1)), b"unowned").unwrap();
    assert!(ReceiptCache::open(&directory.0, AotReceiptCacheLimits::default()).is_err());
    assert!(!directory.0.join(io::MARKER_NAME).exists());
}
