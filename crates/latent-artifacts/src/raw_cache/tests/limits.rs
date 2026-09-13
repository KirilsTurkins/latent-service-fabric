use super::*;

#[test]
fn each_zero_limit_rejects_before_creating_the_cache_root() {
    let base = RawArtifactCacheLimits::default();
    for limits in [
        RawArtifactCacheLimits {
            maximum_entries: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_disk_bytes: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_metadata_bytes: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_staging_entries: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_staging_bytes: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_read_bytes: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_reads: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_pins: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_work: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_object_bytes: 0,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_recovery_entries: 0,
            ..base
        },
    ] {
        let root = Root::new();
        assert_eq!(
            failure(RawArtifactCache::open(root.path(), limits)).code,
            PlatformErrorCode::InvalidArgument
        );
        assert!(!root.path().exists());
    }
}

#[test]
fn each_hard_ceiling_rejects_overflow_sized_configuration_before_io() {
    let base = RawArtifactCacheLimits::default();
    for limits in [
        RawArtifactCacheLimits {
            maximum_entries: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_disk_bytes: u64::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_metadata_bytes: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_staging_entries: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_staging_bytes: u64::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_read_bytes: u64::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_reads: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_pins: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_work: usize::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_object_bytes: u64::MAX,
            ..base
        },
        RawArtifactCacheLimits {
            maximum_recovery_entries: usize::MAX,
            ..base
        },
    ] {
        let root = Root::new();
        assert_eq!(
            failure(RawArtifactCache::open(root.path(), limits)).code,
            PlatformErrorCode::InvalidArgument
        );
        assert!(!root.path().exists());
    }
}

#[cfg(unix)]
#[test]
fn metadata_budget_smaller_than_the_empty_owner_creates_no_cache_files() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits {
        maximum_metadata_bytes: 1,
        ..RawArtifactCacheLimits::default()
    };
    assert!(RawArtifactCache::open(root.path(), limits).is_err());
    assert!(!root.path().exists());
}

#[cfg(unix)]
#[test]
fn entry_and_object_caps_reject_before_staging_and_count_zero_bytes() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits {
        maximum_entries: 1,
        maximum_object_bytes: 3,
        ..RawArtifactCacheLimits::default()
    };
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    assert!(cache.reserve_write(blob(b"four"), 4).is_err());
    let pin = put(&cache, b"");
    assert!(cache.reserve_write(blob(b"a"), 1).is_err());
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.entries, 1);
    assert_eq!(snapshot.resident_disk_bytes, 0);
    assert_eq!(snapshot.pins, 1);
    assert_eq!(snapshot.staging_entries, 0);
    assert_eq!(snapshot.active_work, 0);
    drop(pin);
    cache.reserve_reclaim(1).unwrap().run().unwrap();
    assert_eq!(cache.snapshot().unwrap().entries, 0);
    drop(put(&cache, b"abc"));
}

#[cfg(unix)]
#[test]
fn resident_plus_reserved_disk_bytes_share_one_ceiling() {
    let root = Root::new();
    let cache = RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_disk_bytes: 4,
            ..RawArtifactCacheLimits::default()
        },
    )
    .unwrap();
    drop(put(&cache, b"aa"));
    assert!(cache.reserve_write(blob(b"bbb"), 3).is_err());
    let reservation = cache.reserve_write(blob(b"bb"), 2).unwrap();
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.resident_disk_bytes, 2);
    assert_eq!(snapshot.reserved_disk_bytes, 2);
    assert_eq!(snapshot.staging_entries, 1);
    drop(reservation);
    assert_eq!(cache.snapshot().unwrap().reserved_disk_bytes, 0);
}

#[cfg(unix)]
#[test]
fn staging_entry_and_byte_limits_are_independent_and_refund_untouched_work() {
    for byte_limited in [false, true] {
        let root = Root::new();
        let limits = RawArtifactCacheLimits {
            maximum_staging_entries: if byte_limited { 2 } else { 1 },
            maximum_staging_bytes: if byte_limited { 3 } else { 10 },
            ..RawArtifactCacheLimits::default()
        };
        let cache = RawArtifactCache::open(root.path(), limits).unwrap();
        let reservation = cache.reserve_write(blob(b"abc"), 3).unwrap();
        assert!(cache.reserve_write(blob(b"d"), 1).is_err());
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.staging_entries, 1);
        assert_eq!(snapshot.reserved_disk_bytes, 3);
        assert_eq!(snapshot.active_work, 1);
        drop(reservation);
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.staging_entries, 0);
        assert_eq!(snapshot.reserved_disk_bytes, 0);
        assert_eq!(snapshot.active_work, 0);
        assert!(cache.reserve_write(blob(b"d"), 1).is_ok());
    }
}

#[cfg(unix)]
#[test]
fn metadata_limit_accounts_reserved_entry_and_handle_before_input_bytes() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let empty = cache.snapshot().unwrap().metadata_bytes;
    let reservation = cache.reserve_write(blob(b"a"), 1).unwrap();
    let reserved = cache.snapshot().unwrap().metadata_bytes;
    assert!(reserved > empty);
    drop(reservation);
    assert_eq!(cache.snapshot().unwrap().metadata_bytes, empty);
    for (maximum, accepted) in [(reserved - 1, false), (reserved, true)] {
        let root = Root::new();
        let cache = RawArtifactCache::open(
            root.path(),
            RawArtifactCacheLimits {
                maximum_metadata_bytes: maximum,
                ..RawArtifactCacheLimits::default()
            },
        )
        .unwrap();
        assert_eq!(cache.reserve_write(blob(b"a"), 1).is_ok(), accepted);
        assert!(cache.snapshot().unwrap().metadata_bytes <= maximum);
    }
}

#[cfg(unix)]
#[test]
fn pin_limit_and_work_limit_do_not_share_unbounded_fallbacks() {
    let root = Root::new();
    let cache = RawArtifactCache::open(
        root.path(),
        RawArtifactCacheLimits {
            maximum_pins: 1,
            maximum_work: 1,
            ..RawArtifactCacheLimits::default()
        },
    )
    .unwrap();
    let pin = put(&cache, b"abc");
    assert!(cache.try_pin(&blob(b"abc")).is_err());
    let read = pin.reserve_read(3).unwrap();
    assert!(cache.reserve_write(blob(b"def"), 3).is_err());
    assert!(cache.reserve_reclaim(1).is_err());
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.pins, 1);
    assert_eq!(snapshot.active_work, 1);
    assert_eq!(snapshot.active_reads, 1);
    assert_eq!(snapshot.reserved_read_bytes, 3);
    drop(read);
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.pins, 0);
    assert_eq!(snapshot.active_work, 0);
    assert_eq!(snapshot.active_reads, 0);
    assert_eq!(snapshot.reserved_read_bytes, 0);
}

#[cfg(unix)]
#[test]
fn read_slots_and_bytes_remain_charged_through_returned_buffer_lifetime() {
    for byte_limited in [false, true] {
        let root = Root::new();
        let limits = RawArtifactCacheLimits {
            maximum_reads: if byte_limited { 2 } else { 1 },
            maximum_read_bytes: if byte_limited { 3 } else { 10 },
            ..RawArtifactCacheLimits::default()
        };
        let cache = RawArtifactCache::open(root.path(), limits).unwrap();
        let read = put(&cache, b"abc").reserve_read(3).unwrap();
        assert!(cache
            .try_pin(&blob(b"abc"))
            .unwrap()
            .unwrap()
            .reserve_read(3)
            .is_err());
        let owned = read.read_verified().unwrap();
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.active_work, 0);
        assert_eq!(snapshot.pins, 0);
        assert_eq!(snapshot.reserved_read_bytes, 0);
        assert_eq!(snapshot.retained_read_bytes, 3);
        assert_eq!(snapshot.active_reads, 1);
        assert!(cache
            .try_pin(&blob(b"abc"))
            .unwrap()
            .unwrap()
            .reserve_read(3)
            .is_err());
        drop(owned);
        let snapshot = cache.snapshot().unwrap();
        assert_eq!(snapshot.retained_read_bytes, 0);
        assert_eq!(snapshot.active_reads, 0);
        let read = cache
            .try_pin(&blob(b"abc"))
            .unwrap()
            .unwrap()
            .reserve_read(3)
            .unwrap();
        read.read_into(&mut [0; 3]).unwrap();
        assert_eq!(cache.snapshot().unwrap().retained_read_bytes, 0);
    }
}
