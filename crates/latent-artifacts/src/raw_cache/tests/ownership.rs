use super::*;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn typed_keys_and_zero_byte_objects_roundtrip_exact_bytes() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    for bytes in [b"".as_slice(), b"same exact bytes".as_slice()] {
        let blob_pin = put(&cache, bytes);
        let manifest_pin = cache
            .reserve_write(manifest(bytes), bytes.len() as u64)
            .unwrap()
            .publish(bytes)
            .unwrap();
        assert_ne!(blob_pin.key(), manifest_pin.key());
        for pin in [blob_pin, manifest_pin] {
            assert_eq!(pin.size_bytes(), bytes.len() as u64);
            let owned = pin
                .reserve_read(bytes.len() as u64)
                .unwrap()
                .read_verified()
                .unwrap();
            assert_eq!(owned.as_bytes(), bytes);
        }
    }
    drop(cache);
    let reopened = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    for key in [
        blob(b""),
        manifest(b""),
        blob(b"same exact bytes"),
        manifest(b"same exact bytes"),
    ] {
        assert!(reopened.try_pin(&key).unwrap().is_some());
    }
}

#[test]
fn duplicate_fill_has_one_owner_and_abandoned_reservation_allows_retry() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let key = blob(b"one fill");
    let first = cache.reserve_write(key.clone(), 8).unwrap();
    assert!(cache.reserve_write(key.clone(), 8).is_err());
    assert!(cache.try_pin(&key).unwrap().is_none());
    drop(first);
    let pin = cache
        .reserve_write(key.clone(), 8)
        .unwrap()
        .publish(b"one fill")
        .unwrap();
    assert_eq!(
        failure(cache.reserve_write(key.clone(), 8)).code,
        PlatformErrorCode::AlreadyExists
    );
    assert_eq!(pin.key(), &key);
    assert!(cache.try_pin(&key).unwrap().is_some());
}

#[test]
fn file_pin_and_reserved_read_keep_root_owned_but_verified_bytes_do_not() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits::default();
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    let pin = put(&cache, b"owned bytes");
    drop(cache);
    assert!(RawArtifactCache::open(root.path(), limits).is_err());
    let read = pin.reserve_read(11).unwrap();
    assert!(RawArtifactCache::open(root.path(), limits).is_err());
    let bytes = read.read_verified().unwrap();
    let reopened = RawArtifactCache::open(root.path(), limits).unwrap();
    assert_eq!(bytes.as_bytes(), b"owned bytes");
    assert!(reopened.try_pin(&blob(b"owned bytes")).unwrap().is_some());
}

#[test]
fn abandoned_caller_does_not_release_a_worker_owned_write() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits::default();
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    let write = cache.reserve_write(blob(b"worker"), 6).unwrap();
    let (release, held) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        held.recv_timeout(Duration::from_secs(5)).unwrap();
        drop(write.publish(b"worker").unwrap());
    });
    drop(cache);
    assert!(RawArtifactCache::open(root.path(), limits).is_err());
    release.send(()).unwrap();
    worker.join().unwrap();
    let reopened = RawArtifactCache::open(root.path(), limits).unwrap();
    assert!(reopened.try_pin(&blob(b"worker")).unwrap().is_some());
}

#[test]
fn abandoned_caller_does_not_release_a_worker_owned_read() {
    let root = Root::new();
    let limits = RawArtifactCacheLimits::default();
    let cache = RawArtifactCache::open(root.path(), limits).unwrap();
    let read = put(&cache, b"worker").reserve_read(6).unwrap();
    let (release, held) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        held.recv_timeout(Duration::from_secs(5)).unwrap();
        read.read_verified().unwrap()
    });
    drop(cache);
    assert!(RawArtifactCache::open(root.path(), limits).is_err());
    release.send(()).unwrap();
    let bytes = worker.join().unwrap();
    let reopened = RawArtifactCache::open(root.path(), limits).unwrap();
    assert_eq!(bytes.as_bytes(), b"worker");
    drop(reopened);
    assert_eq!(bytes.as_bytes(), b"worker");
}

#[test]
fn worker_reservations_remain_visible_until_actual_work_and_buffer_release() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let request_owner = Arc::clone(&cache);
    let write = request_owner.reserve_write(blob(b"worker"), 6).unwrap();
    let (release, held) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        held.recv_timeout(Duration::from_secs(5)).unwrap();
        write.publish(b"worker").unwrap()
    });
    drop(request_owner);
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.active_work, 1);
    assert_eq!(snapshot.reserved_disk_bytes, 6);
    assert_eq!(snapshot.staging_entries, 1);
    assert_eq!(snapshot.entries, 0);
    release.send(()).unwrap();
    let pin = worker.join().unwrap();
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.active_work, 0);
    assert_eq!(snapshot.reserved_disk_bytes, 0);
    assert_eq!(snapshot.staging_entries, 0);
    assert_eq!(snapshot.entries, 1);
    assert_eq!(snapshot.resident_disk_bytes, 6);

    let read = pin.reserve_read(6).unwrap();
    let (release, held) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        held.recv_timeout(Duration::from_secs(5)).unwrap();
        read.read_verified().unwrap()
    });
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.active_work, 1);
    assert_eq!(snapshot.pins, 1);
    assert_eq!(snapshot.reserved_read_bytes, 6);
    assert_eq!(snapshot.retained_read_bytes, 0);
    release.send(()).unwrap();
    let bytes = worker.join().unwrap();
    let snapshot = cache.snapshot().unwrap();
    assert_eq!(snapshot.active_work, 0);
    assert_eq!(snapshot.pins, 0);
    assert_eq!(snapshot.reserved_read_bytes, 0);
    assert_eq!(snapshot.retained_read_bytes, 6);
    assert_eq!(bytes.as_bytes(), b"worker");
    drop(bytes);
    assert_eq!(cache.snapshot().unwrap().retained_read_bytes, 0);
}

#[test]
fn borrowed_read_requires_exact_destination_and_supplied_digest() {
    let root = Root::new();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    drop(put(&cache, b"abc"));
    for size in [2, 4] {
        let pin = cache.try_pin(&blob(b"abc")).unwrap().unwrap();
        assert!(pin
            .reserve_read(3)
            .unwrap()
            .read_into(&mut vec![0; size])
            .is_err());
    }
    let pin = cache.try_pin(&blob(b"abc")).unwrap().unwrap();
    assert!(pin.reserve_read(2).is_err());
    let pin = cache.try_pin(&blob(b"abc")).unwrap().unwrap();
    let mut output = [0; 3];
    pin.reserve_read(3).unwrap().read_into(&mut output).unwrap();
    assert_eq!(&output, b"abc");

    assert!(cache
        .reserve_write(blob(b"def"), 3)
        .unwrap()
        .publish(b"xyz")
        .is_err());
    assert!(cache.try_pin(&blob(b"def")).unwrap().is_none());
    assert!(cache
        .reserve_write(blob(b"long"), 3)
        .unwrap()
        .publish(b"long")
        .is_err());
    assert!(cache.try_pin(&blob(b"long")).unwrap().is_none());
}
