use super::*;

#[test]
fn canonical_ancestor_expansion_is_bounded_before_creating_missing_leaves() {
    let root = Root::new();
    let real = root
        .base()
        .join("an-existing-ancestor-with-a-deliberately-longer-name");
    std::fs::create_dir(&real).unwrap();
    let alias = root.base().join("short");
    std::os::unix::fs::symlink(&real, &alias).unwrap();
    let target = alias.join("new/cache");
    let maximum = real.join("new/cache").as_os_str().len() - 1;
    assert!(target.as_os_str().len() < maximum);
    assert_eq!(
        failure(super::super::recovery::bounded_root(target, maximum)).code,
        PlatformErrorCode::InvalidArgument
    );
    assert!(!real.join("new").exists());
}

#[test]
fn corrupt_entries_still_consume_the_startup_hash_budget() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    for bytes in [b"aaa", b"bbb"] {
        drop(put(&cache, bytes));
        std::fs::write(
            root.path()
                .join("objects")
                .join(blob(bytes).name())
                .join("data"),
            b"bad",
        )
        .unwrap();
    }
    drop(cache);
    io::take_hash_bytes();
    let rejected = failure(RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_disk_bytes: 4,
            ..RawArtifactCacheLimits::default()
        },
    ));
    assert_eq!(rejected.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(io::take_hash_bytes(), 3);
}

#[test]
fn a_selected_lru_entry_is_not_deleted_after_new_access_or_incarnation() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let key = blob(b"abc");
    drop(put(&cache, b"abc"));
    let selected = {
        let state = cache.state().unwrap();
        let entry = state.entries.get(&key).unwrap();
        (entry.recency, entry.incarnation)
    };
    let reclaim = cache.reserve_reclaim(1).unwrap();
    drop(cache.try_pin(&key).unwrap().unwrap());
    assert_eq!(
        reclaim.entry(&key, Some(selected)).unwrap().0,
        RawArtifactEviction::Absent
    );
    assert!(cache.try_pin(&key).unwrap().is_some());
    drop(reclaim);
    assert_eq!(cache.evict(&key).unwrap(), RawArtifactEviction::Removed);
    drop(put(&cache, b"abc"));
    let reclaim = cache.reserve_reclaim(1).unwrap();
    assert_eq!(
        reclaim.entry(&key, Some(selected)).unwrap().0,
        RawArtifactEviction::Absent
    );
    assert!(cache.try_pin(&key).unwrap().is_some());
}
