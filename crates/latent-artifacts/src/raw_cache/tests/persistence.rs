use super::*;

fn directory(root: &Root, key: &RawArtifactKey) -> PathBuf {
    root.path().join("objects").join(key.name())
}

#[test]
fn missing_truncated_oversized_and_wrong_hash_objects_are_never_verified_reads() {
    for damaged in [
        None,
        Some(b"a".as_slice()),
        Some(b"abcdef".as_slice()),
        Some(b"xyz".as_slice()),
    ] {
        let root = Root::new();
        let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
        let held = put(&cache, b"abc");
        let reader = cache.try_pin(&blob(b"abc")).unwrap().unwrap();
        let path = directory(&root, &blob(b"abc")).join("data");
        if let Some(bytes) = damaged {
            std::fs::write(&path, bytes).unwrap();
        } else {
            std::fs::remove_file(&path).unwrap();
        }
        let code = failure(reader.reserve_read(3).unwrap().read_verified()).code;
        assert!(matches!(
            code,
            PlatformErrorCode::CorruptArtifact | PlatformErrorCode::NotFound
        ));
        assert!(!matches!(cache.try_pin(&blob(b"abc")), Ok(Some(_))));
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.resident_disk_bytes, 3);
        assert_eq!(snapshot.pinned_disk_bytes, 3);
        assert_eq!(snapshot.deletion_pending_bytes, 3);
        assert!(snapshot.corruptions >= 1);
        assert_eq!(snapshot.retained_read_bytes, 0);
        assert_eq!(snapshot.reserved_read_bytes, 0);
        assert!(cache.reserve_write(blob(b"abc"), 3).is_err());
        assert_eq!(cache.reserve_reclaim(1).unwrap().run().unwrap().removed, 0);
        drop(held);
        assert!(
            directory(&root, &blob(b"abc")).exists(),
            "pin Drop never unlinks files"
        );
        cache.reserve_reclaim(1).unwrap().run().unwrap();
        assert_eq!(cache.snapshot().unwrap().resident_disk_bytes, 0);
        let replacement = put(&cache, b"abc");
        assert_eq!(
            replacement
                .reserve_read(3)
                .unwrap()
                .read_verified()
                .unwrap()
                .as_bytes(),
            b"abc"
        );
    }
}

#[test]
fn unknown_object_files_block_reclamation_and_are_preserved_on_reopen() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    drop(put(&cache, b"abc"));
    let path = directory(&root, &blob(b"abc"));
    std::fs::write(path.join("unrecognized.keep"), b"preserve").unwrap();
    assert!(cache.reserve_reclaim(1).unwrap().run().is_err());
    assert_eq!(
        std::fs::read(path.join("unrecognized.keep")).unwrap(),
        b"preserve"
    );
    assert_eq!(std::fs::read(path.join("data")).unwrap(), b"abc");
    assert_eq!(cache.snapshot().unwrap().resident_disk_bytes, 3);
    drop(cache);
    assert!(RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).is_err());
    assert_eq!(
        std::fs::read(path.join("unrecognized.keep")).unwrap(),
        b"preserve"
    );
}

#[test]
fn symlinked_object_data_never_reads_or_removes_an_external_target() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let pin = put(&cache, b"abc");
    let data = directory(&root, &blob(b"abc")).join("data");
    let outside = root.base().join("outside.keep");
    std::fs::write(&outside, b"external source").unwrap();
    std::fs::remove_file(&data).unwrap();
    std::os::unix::fs::symlink(&outside, &data).unwrap();
    assert!(pin.reserve_read(3).unwrap().read_verified().is_err());
    assert!(cache.reserve_reclaim(1).unwrap().run().is_err());
    assert!(std::fs::symlink_metadata(&data)
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(std::fs::read(&outside).unwrap(), b"external source");
    drop(cache);
    assert!(RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).is_err());
    assert_eq!(std::fs::read(&outside).unwrap(), b"external source");
}

#[test]
fn unknown_unicode_object_name_returns_an_error_without_panicking_or_deleting() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    drop(cache);
    let name = "€".repeat(22);
    assert_eq!(name.len(), 66);
    let unknown = root.path().join("objects").join(name);
    std::fs::create_dir(&unknown).unwrap();
    std::fs::write(unknown.join("keep"), b"unknown Unicode entry").unwrap();
    let outcome = std::panic::catch_unwind(|| {
        RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default())
    });
    assert!(
        outcome.is_ok(),
        "a non-ASCII name must not panic on UTF-8 slicing"
    );
    assert!(outcome.unwrap().is_err());
    assert_eq!(
        std::fs::read(unknown.join("keep")).unwrap(),
        b"unknown Unicode entry"
    );
}

#[test]
fn recovery_scan_limit_rejects_existing_objects_without_deleting_them() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    for bytes in [b"a", b"b"] {
        drop(put(&cache, bytes));
    }
    drop(cache);
    assert!(RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_recovery_entries: 1,
            ..RawArtifactCacheLimits::default()
        }
    )
    .is_err());
    for bytes in [b"a", b"b"] {
        assert_eq!(
            std::fs::read(directory(&root, &blob(bytes)).join("data")).unwrap(),
            bytes
        );
    }
    let reopened = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    assert_eq!(reopened.snapshot().unwrap().entries, 2);
}

#[test]
fn reopen_uses_deterministic_digest_order_for_initial_lru() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let mut keys = [blob(b"a"), blob(b"b"), blob(b"c")];
    for bytes in [b"b", b"c", b"a"] {
        drop(put(&cache, bytes));
    }
    drop(cache);
    let reopened = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    keys.sort();
    assert_eq!(
        reopened.reserve_reclaim(1).unwrap().run().unwrap().removed,
        1
    );
    assert!(reopened.try_pin(&keys[0]).unwrap().is_none());
    for key in &keys[1..] {
        assert!(reopened.try_pin(key).unwrap().is_some());
    }
}
