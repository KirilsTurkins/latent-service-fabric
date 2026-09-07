use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Barrier;

use super::*;

fn limits() -> CacheLimits {
    CacheLimits {
        maximum_entries: 2,
        maximum_source_bytes: 12,
        maximum_metadata_bytes: 12,
        maximum_compiled_image_bytes: 12,
        maximum_concurrent_preparations: 2,
    }
}

fn reserve<T>(
    cache: &Arc<PreparedCache<T>>,
    handle: &str,
    source: usize,
    metadata: usize,
) -> PrepareReservation<T> {
    let PrepareAccess::Compile(reservation) =
        cache.begin(handle.to_owned(), source, metadata).unwrap()
    else {
        panic!("expected uncached preparation");
    };
    reservation
}

fn publish(cache: &Arc<PreparedCache<u8>>, handle: &str, value: u8) {
    reserve(cache, handle, 2, 3)
        .publish(Arc::new(value), 4)
        .unwrap();
}

#[test]
fn shared_hits_refresh_lru_and_release_requires_matching_runtime() {
    let cache = Arc::new(PreparedCache::new(limits()).unwrap());
    let sibling = Arc::clone(&cache);
    publish(&cache, "a", 1);
    publish(&cache, "b", 2);
    let PrepareAccess::Hit(runtime) = sibling.begin("a".to_owned(), 2, 3).unwrap() else {
        panic!("another backend must reuse shared prepared state");
    };
    assert_eq!(*runtime, 1);
    publish(&cache, "c", 3);
    assert!(cache.get("b").is_none());
    assert_eq!(*cache.get("a").unwrap(), 1);
    assert!(!cache.remove_matching("a", |value| *value == 2));
    assert!(cache.remove_matching("a", |value| *value == 1));
    assert!(!cache.remove_matching("a", |_| true));
    let snapshot = cache.snapshot();
    assert_eq!(snapshot.entries, 1);
    assert_eq!(snapshot.source_bytes, 2);
    assert_eq!(snapshot.metadata_bytes, 3);
    assert_eq!(snapshot.compiled_image_bytes, 4);
    assert_eq!(snapshot.preparing, 0);
    assert_eq!(snapshot.hits, 2);
    assert_eq!(snapshot.misses, 4);
    assert_eq!(snapshot.evictions, 1);
    assert_eq!(snapshot.invalidations, 1);
}

#[test]
fn each_byte_budget_independently_evicts_without_exceeding_capacity() {
    for constrained in 0..3 {
        let mut limits = limits();
        limits.maximum_entries = 4;
        match constrained {
            0 => limits.maximum_source_bytes = 3,
            1 => limits.maximum_metadata_bytes = 5,
            _ => limits.maximum_compiled_image_bytes = 7,
        }
        let cache = Arc::new(PreparedCache::new(limits).unwrap());
        publish(&cache, "a", 1);
        publish(&cache, "b", 2);
        let snapshot = cache.snapshot();
        assert_eq!(snapshot.entries, 1);
        assert!(cache.get("a").is_none());
        assert_eq!(*cache.get("b").unwrap(), 2);
        assert!(snapshot.source_bytes <= snapshot.maximum_source_bytes);
        assert!(snapshot.metadata_bytes <= snapshot.maximum_metadata_bytes);
        assert!(snapshot.compiled_image_bytes <= snapshot.maximum_compiled_image_bytes);
    }
}

#[test]
fn impossible_entries_fail_without_evicting_existing_state_or_leaking_reservations() {
    let cache = Arc::new(PreparedCache::new(limits()).unwrap());
    publish(&cache, "existing", 1);
    for (source, metadata) in [(13, 1), (1, 13)] {
        let error = cache
            .begin("oversized".to_owned(), source, metadata)
            .err()
            .unwrap();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(cache.snapshot().preparing, 0);
    }
    let error = reserve(&cache, "image-too-large", 2, 3)
        .publish(Arc::new(2), 13)
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(cache.snapshot().preparing, 0);
    assert_eq!(*cache.get("existing").unwrap(), 1);
    assert_eq!(cache.snapshot().entries, 1);
}

#[test]
fn preparation_capacity_and_duplicate_identity_have_no_waiter_queue() {
    let cache = Arc::new(PreparedCache::<u8>::new(limits()).unwrap());
    let first = reserve(&cache, "a", 2, 3);
    let duplicate = cache.begin("a".to_owned(), 2, 3).err().unwrap();
    assert_eq!(duplicate.code, PlatformErrorCode::Unavailable);
    assert!(duplicate.retryable);
    let second = reserve(&cache, "b", 4, 5);
    let exhausted = cache.begin("c".to_owned(), 1, 1).err().unwrap();
    assert_eq!(exhausted.code, PlatformErrorCode::Unavailable);
    assert!(exhausted.retryable);
    let snapshot = cache.snapshot();
    assert_eq!(snapshot.preparing, 2);
    assert_eq!(snapshot.preparing_source_bytes, 6);
    assert_eq!(snapshot.preparing_metadata_bytes, 8);
    drop(first);
    assert_eq!(cache.snapshot().preparing_source_bytes, 4);
    let replacement = reserve(&cache, "a", 2, 3);
    drop(second);
    drop(replacement);
    let snapshot = cache.snapshot();
    assert_eq!(snapshot.preparing, 0);
    assert_eq!(snapshot.preparing_source_bytes, 0);
    assert_eq!(snapshot.preparing_metadata_bytes, 0);
}

#[test]
fn panic_and_dropped_work_refund_compilation_capacity() {
    let cache = Arc::new(PreparedCache::<u8>::new(limits()).unwrap());
    let result = std::panic::catch_unwind(|| {
        let _reservation = reserve(&cache, "panic", 2, 3);
        panic!("fixture compiler panic");
    });
    assert!(result.is_err());
    assert_eq!(cache.snapshot().preparing, 0);
    let reservation = reserve(&cache, "dropped", 2, 3);
    let future = async move {
        let _reservation = reservation;
        std::future::pending::<()>().await;
    };
    assert_eq!(cache.snapshot().preparing, 1);
    drop(future);
    assert_eq!(cache.snapshot().preparing, 0);
}

struct CountDrop(Arc<AtomicUsize>);

impl Drop for CountDrop {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn an_active_pin_survives_eviction_and_release_until_its_owner_drops_it() {
    let mut limits = limits();
    limits.maximum_entries = 1;
    let cache = Arc::new(PreparedCache::new(limits).unwrap());
    let dropped = Arc::new(AtomicUsize::new(0));
    reserve(&cache, "a", 2, 3)
        .publish(Arc::new(CountDrop(Arc::clone(&dropped))), 4)
        .unwrap();
    let pin = cache.get("a").unwrap();
    reserve(&cache, "b", 2, 3)
        .publish(Arc::new(CountDrop(Arc::clone(&dropped))), 4)
        .unwrap();
    assert!(cache.get("a").is_none());
    assert_eq!(dropped.load(Ordering::SeqCst), 0);
    assert!(cache.remove_matching("b", |_| true));
    assert_eq!(cache.snapshot().entries, 0);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    drop(pin);
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
}

#[test]
fn simultaneous_preparations_reserve_the_single_available_slot_atomically() {
    let mut limits = limits();
    limits.maximum_concurrent_preparations = 1;
    let cache = Arc::new(PreparedCache::<u8>::new(limits).unwrap());
    let start = Barrier::new(3);
    let acquired = Barrier::new(3);
    let release = Barrier::new(3);
    std::thread::scope(|scope| {
        let worker = |handle: &str| {
            start.wait();
            let access = cache.begin(handle.to_owned(), 2, 3);
            acquired.wait();
            release.wait();
            matches!(access, Ok(PrepareAccess::Compile(_)))
        };
        let first = scope.spawn(move || worker("a"));
        let second = scope.spawn(move || worker("b"));
        start.wait();
        acquired.wait();
        let snapshot = cache.snapshot();
        release.wait();
        let accepted = usize::from(first.join().unwrap()) + usize::from(second.join().unwrap());
        assert_eq!(snapshot.preparing, 1);
        assert_eq!(accepted, 1);
    });
    assert_eq!(cache.snapshot().preparing, 0);
}

#[test]
fn instance_permits_are_shared_affine_and_reclaimed_on_drop_and_unwind() {
    let gate = Arc::new(ActiveInstanceGate::new(1).unwrap());
    let permit = gate.try_acquire().unwrap();
    let sibling = Arc::clone(&gate);
    let error = sibling.try_acquire().err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert!(error.retryable);
    assert_eq!(gate.active(), 1);
    drop(permit);
    assert_eq!(gate.active(), 0);
    let result = std::panic::catch_unwind(|| {
        let _permit = sibling.try_acquire().unwrap();
        panic!("fixture activation panic");
    });
    assert!(result.is_err());
    assert_eq!(gate.active(), 0);
    let permit = gate.try_acquire().unwrap();
    let future = async move {
        let _permit = permit;
        std::future::pending::<()>().await;
    };
    drop(future);
    assert_eq!(gate.active(), 0);
}

#[test]
fn cached_hits_do_not_need_another_compilation_slot_and_bad_limits_are_rejected() {
    let mut bounds = limits();
    bounds.maximum_concurrent_preparations = 1;
    let cache = Arc::new(PreparedCache::new(bounds).unwrap());
    publish(&cache, "cached", 1);
    let _preparing = reserve(&cache, "other", 2, 3);
    assert!(matches!(
        cache.begin("cached".to_owned(), 2, 3),
        Ok(PrepareAccess::Hit(_))
    ));
    assert_eq!(cache.snapshot().preparing, 1);
    bounds.maximum_source_bytes = usize::MAX;
    bounds.maximum_concurrent_preparations = 2;
    assert_eq!(
        PreparedCache::<u8>::new(bounds).err().unwrap().code,
        PlatformErrorCode::InvalidArgument
    );
    assert!(ActiveInstanceGate::new(0).is_err());
}

#[test]
fn discovered_metadata_charges_actual_bytes_without_exceeding_its_reservation() {
    let mut bounds = limits();
    bounds.maximum_metadata_bytes = 5;
    let cache = Arc::new(PreparedCache::new(bounds).unwrap());
    let first = reserve(&cache, "a", 2, 5);
    assert_eq!(cache.snapshot().preparing_metadata_bytes, 5);
    first.publish_with_metadata(Arc::new(1), 4, 2).unwrap();
    reserve(&cache, "b", 2, 5)
        .publish_with_metadata(Arc::new(2), 4, 2)
        .unwrap();
    let snapshot = cache.snapshot();
    assert_eq!(snapshot.entries, 2);
    assert_eq!(snapshot.metadata_bytes, 4);
    assert_eq!(snapshot.preparing_metadata_bytes, 0);
    let error = reserve(&cache, "c", 2, 3)
        .publish_with_metadata(Arc::new(3), 4, 4)
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    let after = cache.snapshot();
    assert_eq!(after.misses, snapshot.misses + 1);
    assert_eq!(
        after,
        PreparedCacheSnapshot {
            misses: snapshot.misses + 1,
            ..snapshot
        }
    );
    assert!(cache.get("a").is_some() && cache.get("b").is_some());
}
