use super::super::io::{fail_next, FailPoint};
use super::*;

#[test]
fn publication_cutpoints_never_expose_partial_bytes_and_reopen_recovers_exact_outcome() {
    for (point, committed) in [
        (FailPoint::BeforeDirectorySync, false),
        (FailPoint::BeforePublishRename, false),
        (FailPoint::AfterPublishRename, true),
    ] {
        let root = Root::new();
        let limits = RawArtifactCacheLimits::default();
        let cache = RawArtifactCache::open(root.path(), limits).unwrap();
        let key = blob(b"atomic");
        let write = cache.reserve_write(key.clone(), 6).unwrap();
        fail_next(point);
        assert!(write.publish(b"atomic").is_err());
        assert!(cache.try_pin(&key).unwrap().is_none());
        let stage = root.path().join("staging").join(key.name());
        let object = root.path().join("objects").join(key.name());
        if stage.exists() || object.exists() {
            let snapshot = cache.snapshot().unwrap();
            assert_eq!(snapshot.reserved_disk_bytes, 6);
            assert_eq!(snapshot.staging_entries, 1);
            assert_eq!(snapshot.deletion_pending_bytes, 6);
        }
        assert_eq!(cache.snapshot().unwrap().active_work, 0);
        drop(cache);
        let recovered = RawArtifactCache::open(root.path(), limits).unwrap();
        let pin = recovered.try_pin(&key).unwrap();
        assert_eq!(pin.is_some(), committed);
        if let Some(pin) = pin {
            assert_eq!(
                pin.reserve_read(6)
                    .unwrap()
                    .read_verified()
                    .unwrap()
                    .as_bytes(),
                b"atomic"
            );
        }
        let snapshot = recovered.snapshot().unwrap();
        assert_eq!(snapshot.reserved_disk_bytes, 0);
        assert_eq!(snapshot.staging_entries, 0);
        assert_eq!(snapshot.active_work, 0);
        assert!(!stage.exists());
    }
}

#[test]
fn failed_publish_keeps_staging_capacity_until_explicit_reclamation() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits {
        maximum_staging_entries: 1,
        maximum_staging_bytes: 6,
        ..RawArtifactCacheLimits::default()
    };
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    let write = cache.reserve_write(blob(b"atomic"), 6).unwrap();
    fail_next(FailPoint::BeforePublishRename);
    assert!(write.publish(b"atomic").is_err());
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.reserved_disk_bytes, 6);
    assert_eq!(snapshot.staging_entries, 1);
    assert_eq!(snapshot.active_work, 0);
    assert!(cache.reserve_write(blob(b"b"), 1).is_err());
    let result = cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert_eq!(result.removed, 1);
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.reserved_disk_bytes, 0);
    assert_eq!(snapshot.staging_entries, 0);
    assert_eq!(snapshot.deletion_pending_bytes, 0);
    drop(put(&cache, b"b"));
}

#[test]
fn failed_unlink_and_directory_sync_keep_disk_charge_until_successful_retry() {
    for point in [
        FailPoint::BeforeRemove,
        FailPoint::AfterRemoveData,
        FailPoint::BeforeDirectorySync,
    ] {
        let root = Root::new();
        let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
        drop(put(&cache, b"abc"));
        fail_next(point);
        assert!(cache.reserve_reclaim(1).unwrap().run().is_err());
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.entries, 1);
        assert_eq!(snapshot.resident_disk_bytes, 3);
        assert_eq!(snapshot.deletion_pending_bytes, 3);
        assert_eq!(snapshot.active_work, 0);
        assert_eq!(snapshot.pins, 0);
        assert!(cache.try_pin(&blob(b"abc")).unwrap().is_none());
        cache.reserve_reclaim(1).unwrap().run().unwrap();
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.entries, 0);
        assert_eq!(snapshot.resident_disk_bytes, 0);
        assert_eq!(snapshot.deletion_pending_bytes, 0);
        assert_eq!(snapshot.evictions, 1);
        assert!(cache.reserve_write(blob(b"abc"), 3).is_ok());
    }
}

#[test]
fn interrupted_unlink_reopens_without_resurrecting_missing_payload() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits::default();
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    drop(put(&cache, b"abc"));
    fail_next(FailPoint::AfterRemoveData);
    assert!(cache.reserve_reclaim(1).unwrap().run().is_err());
    drop(cache);
    let recovered = RawArtifactCache::open(root.path(), limits).unwrap();
    assert!(recovered.try_pin(&blob(b"abc")).unwrap().is_none());
    let snapshot = recovered.snapshot().unwrap();
    assert_eq!(snapshot.entries, 0);
    assert_eq!(snapshot.resident_disk_bytes, 0);
    assert_eq!(snapshot.deletion_pending_bytes, 0);
}

#[test]
fn interrupted_entry_writes_are_reclaimed_with_absent_or_partial_data() {
    for record in [b"".as_slice(), b"{\"formatVersion\":".as_slice()] {
        for data in [None, Some(b"a".as_slice())] {
            let root = Root::new();
            let limits = RawArtifactCacheLimits::default();
            drop(RawArtifactCache::open(root.path(), limits).unwrap());
            let stage = root.path().join("staging").join(blob(b"abc").name());
            std::fs::create_dir(&stage).unwrap();
            std::fs::write(stage.join("ENTRY.json"), record).unwrap();
            if let Some(data) = data {
                std::fs::write(stage.join("data"), data).unwrap();
            }
            let recovered = RawArtifactCache::open(root.path(), limits).unwrap();
            assert!(!stage.exists());
            assert!(recovered.try_pin(&blob(b"abc")).unwrap().is_none());
            let snapshot = recovered.snapshot().unwrap();
            assert_eq!(snapshot.entries, 0);
            assert_eq!(snapshot.staging_entries, 0);
            assert_eq!(snapshot.reserved_disk_bytes, 0);
        }
    }
}

#[test]
fn partial_staging_with_unknown_files_or_symlinks_is_preserved() {
    for linked in [false, true] {
        let root = Root::new();
        let limits = RawArtifactCacheLimits::default();
        drop(RawArtifactCache::open(root.path(), limits).unwrap());
        let stage = root.path().join("staging").join(blob(b"abc").name());
        std::fs::create_dir(&stage).unwrap();
        std::fs::write(stage.join("ENTRY.json"), b"{").unwrap();
        let outside = root.base().join("outside.keep");
        std::fs::write(&outside, b"keep").unwrap();
        if linked {
            std::os::unix::fs::symlink(&outside, stage.join("data")).unwrap();
        } else {
            std::fs::write(stage.join("unknown.keep"), b"keep").unwrap();
        }
        assert!(RawArtifactCache::open(root.path(), limits).is_err());
        assert_eq!(std::fs::read(stage.join("ENTRY.json")).unwrap(), b"{");
        assert_eq!(std::fs::read(&outside).unwrap(), b"keep");
        if linked {
            assert!(std::fs::symlink_metadata(stage.join("data"))
                .unwrap()
                .file_type()
                .is_symlink());
        } else {
            assert_eq!(std::fs::read(stage.join("unknown.keep")).unwrap(), b"keep");
        }
    }
}

#[test]
fn partial_root_marker_and_both_rename_cutpoints_are_recoverable() {
    for bytes in [b"".as_slice(), b"LSF raw".as_slice()] {
        let root = Root::new();
        std::fs::create_dir(root.path()).unwrap();
        std::fs::write(root.path().join("RAW_CACHE.next"), bytes).unwrap();
        let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
        assert_eq!(
            std::fs::read(root.path().join("RAW_CACHE")).unwrap(),
            super::super::io::MARKER
        );
        assert!(!root.path().join("RAW_CACHE.next").exists());
        assert_eq!(cache.snapshot().unwrap().entries, 0);
    }
    for point in [
        FailPoint::BeforeRootMarkerRename,
        FailPoint::AfterRootMarkerRename,
    ] {
        let root = Root::new();
        fail_next(point);
        assert!(RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).is_err());
        let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
        assert!(!root.path().join("RAW_CACHE.next").exists());
        assert_eq!(cache.snapshot().unwrap().entries, 0);
    }
}

#[test]
fn valid_root_marker_preserves_objects_while_discarding_only_registered_stale_next() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits::default();
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    drop(put(&cache, b"kept"));
    drop(cache);
    std::fs::write(root.path().join("RAW_CACHE.next"), b"partial").unwrap();
    let recovered = RawArtifactCache::open(root.path(), limits).unwrap();
    assert!(recovered.try_pin(&blob(b"kept")).unwrap().is_some());
    assert!(!root.path().join("RAW_CACHE.next").exists());
}
