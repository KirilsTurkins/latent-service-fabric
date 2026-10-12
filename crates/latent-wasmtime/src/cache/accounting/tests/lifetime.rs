use std::sync::atomic::Ordering;
use std::sync::Arc;

use super::support::*;

#[test]
fn clones_eviction_recompilation_and_deferred_drop_count_actual_runtime_once() {
    let cache = cache(1);
    let observer = cache.prepared_runtime_observer();
    let (old, old_drops) = value(&cache, COST);
    let pin = Arc::clone(&old);
    assert_populations(&observer, 1, 0, 0);
    publish(&cache, "same", &old);
    assert_populations(&observer, 0, 1, 0);
    assert!(cache.remove_matching("same", |_| {
        assert_eq!(cache.snapshot().entries, 1);
        true
    }));
    assert_populations(&observer, 0, 0, 1);

    let (new, new_drops) = value(&cache, COST);
    publish(&cache, "same", &new);
    assert_populations(&observer, 0, 1, 1);
    drop(old);
    assert_eq!(old_drops.load(Ordering::SeqCst), 0);
    drop(pin);
    assert_eq!(old_drops.load(Ordering::SeqCst), 1);
    assert_populations(&observer, 0, 1, 0);

    let (replacement, _) = value(&cache, COST);
    let mut admission = reservation(&cache, "replacement", COST);
    admission.track_runtime(&replacement).unwrap();
    drop(new);
    let evicted = admission
        .publish_deferred(replacement, COST.compiled_image_bytes, COST.metadata_bytes)
        .unwrap();
    assert_eq!(evicted.len(), 1);
    assert_eq!(new_drops.load(Ordering::SeqCst), 0);
    assert_populations(&observer, 0, 1, 1);
    drop(evicted);
    assert_eq!(new_drops.load(Ordering::SeqCst), 1);
    assert_populations(&observer, 0, 1, 0);
    drop(cache);
    assert_populations(&observer, 0, 0, 0);
}

#[test]
fn dropping_cache_reclassifies_held_runtime_and_observer_does_not_retain_cache() {
    let cache = cache(2);
    let observer = cache.prepared_runtime_observer();
    let weak = Arc::downgrade(&cache);
    let (held, drops) = value(&cache, COST);
    publish(&cache, "held", &held);
    let (only_resident, resident_drops) = value(&cache, COST);
    publish(&cache, "unheld", &only_resident);
    drop(only_resident);
    drop(cache);
    assert!(weak.upgrade().is_none());
    assert_eq!(resident_drops.load(Ordering::SeqCst), 1);
    assert_eq!(drops.load(Ordering::SeqCst), 0);
    assert_populations(&observer, 0, 0, 1);
    drop(held);
    assert_populations(&observer, 0, 0, 0);
}

#[test]
fn unfinished_token_cannot_keep_runtime_charge_alive_and_unwind_refunds_reservation() {
    let cache = cache(1);
    let observer = cache.prepared_runtime_observer();
    let (runtime, drops) = value(&cache, COST);
    let mut pending = reservation(&cache, "pending", COST);
    pending.track_runtime(&runtime).unwrap();
    drop(runtime);
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert_populations(&observer, 0, 0, 0);
    assert_eq!(cache.snapshot().preparing, 1);
    drop(pending);
    assert_eq!(cache.snapshot().preparing, 0);

    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let (runtime, _) = value(&cache, COST);
        let mut pending = reservation(&cache, "unwind", COST);
        pending.track_runtime(&runtime).unwrap();
        panic!("bounded preparation failure");
    }));
    assert!(result.is_err());
    assert_populations(&observer, 0, 0, 0);
    assert_eq!(cache.snapshot().preparing, 0);
    assert_eq!(cache.snapshot().preparing_source_bytes, 0);
    assert_eq!(cache.snapshot().preparing_metadata_bytes, 0);
}

#[test]
fn invalidation_cannot_remove_a_replacement_installed_by_reentrant_predicate() {
    let cache = cache(1);
    let observer = cache.prepared_runtime_observer();
    let (old, _) = value(&cache, COST);
    publish(&cache, "identity", &old);
    let (new, _) = value(&cache, COST);
    assert!(!cache.remove_matching("identity", |_| {
        assert!(cache.remove_matching("identity", |_| true));
        publish(&cache, "identity", &new);
        true
    }));
    assert!(Arc::ptr_eq(&cache.get("identity").unwrap(), &new));
    assert_eq!(cache.snapshot().invalidations, 1);
    assert_populations(&observer, 0, 1, 1);
}
