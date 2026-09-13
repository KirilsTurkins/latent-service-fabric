use super::*;

#[test]
fn reclaim_uses_lru_order_while_skipping_live_file_pins() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    for bytes in [b"a", b"b", b"c"] {
        drop(put(&cache, bytes));
    }
    drop(cache.try_pin(&blob(b"a")).unwrap().unwrap());
    let pinned = cache.try_pin(&blob(b"b")).unwrap().unwrap();
    let reclaimed = cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert_eq!(reclaimed.removed, 1);
    assert_eq!(reclaimed.reclaimed_bytes, 1);
    assert!(cache.try_pin(&blob(b"c")).unwrap().is_none());
    assert!(cache.try_pin(&blob(b"a")).unwrap().is_some());
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.entries, 2);
    assert_eq!(snapshot.resident_disk_bytes, 2);
    assert_eq!(snapshot.pinned_disk_bytes, 1);
    assert_eq!(snapshot.evictions, 1);
    assert_eq!(pinned.key(), &blob(b"b"));
}

#[test]
fn full_pinned_cache_rejects_new_fills_and_reclaim_cannot_remove_live_objects() {
    let root = Root::new();
    let cache = RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_entries: 2,
            maximum_disk_bytes: 2,
            ..RawArtifactCacheLimits::default()
        },
    )
    .unwrap();
    let first = put(&cache, b"a");
    let second = put(&cache, b"b");
    assert!(cache.reserve_write(blob(b"c"), 1).is_err());
    let reclaimed = cache.reserve_reclaim(2).unwrap().run().unwrap();
    assert_eq!(reclaimed.removed, 0);
    assert_eq!(reclaimed.pinned, 2);
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.entries, 2);
    assert_eq!(snapshot.pinned_disk_bytes, 2);
    assert_eq!(snapshot.staging_entries, 0);
    assert_eq!(snapshot.reserved_disk_bytes, 0);
    assert!(snapshot.pressure_rejections >= 1);
    drop(first);
    cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert_eq!(cache.snapshot().unwrap().entries, 1);
    drop(put(&cache, b"c"));
    assert_eq!(second.key(), &blob(b"b"));
}

#[test]
fn dropping_pin_performs_no_reclamation_and_explicit_work_has_its_own_slot() {
    let root = Root::new();
    let cache = RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_work: 1,
            ..RawArtifactCacheLimits::default()
        },
    )
    .unwrap();
    let pin = put(&cache, b"kept");
    let file = root
        .path()
        .join("objects")
        .join(blob(b"kept").name())
        .join("data");
    let metadata = cache.snapshot().unwrap().metadata_bytes;
    drop(pin);
    assert_eq!(std::fs::read(&file).unwrap(), b"kept");
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.entries, 1);
    assert_eq!(snapshot.pins, 0);
    assert_eq!(snapshot.active_work, 0);
    assert_eq!(snapshot.resident_disk_bytes, 4);
    assert!(snapshot.metadata_bytes < metadata);
    assert!(cache.reserve_reclaim(0).is_err());
    let reclaim = cache.reserve_reclaim(1).unwrap();
    assert_eq!(cache.snapshot().unwrap().active_work, 1);
    assert!(cache.reserve_reclaim(1).is_err());
    drop(reclaim);
    assert_eq!(cache.snapshot().unwrap().active_work, 0);
    assert!(file.exists());
    let reclaimed = cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert_eq!(reclaimed.removed, 1);
    assert!(!file.exists());
    assert_eq!(cache.snapshot().unwrap().active_work, 0);
}

#[test]
fn hit_miss_and_usage_counters_do_not_turn_raw_residency_into_a_pin() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    assert!(cache.try_pin(&blob(b"a")).unwrap().is_none());
    let pin = put(&cache, b"a");
    let another = cache.try_pin(&blob(b"a")).unwrap().unwrap();
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.hits, 1);
    assert_eq!(snapshot.misses, 1);
    assert_eq!(snapshot.pins, 2);
    assert_eq!(
        snapshot.pinned_disk_bytes, 1,
        "disk occupancy is counted once per object"
    );
    drop(pin);
    assert_eq!(cache.snapshot().unwrap().pinned_disk_bytes, 1);
    drop(another);
    assert_eq!(cache.snapshot().unwrap().pinned_disk_bytes, 0);
    assert_eq!(cache.snapshot().unwrap().resident_disk_bytes, 1);
}
