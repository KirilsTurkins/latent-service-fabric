use std::sync::Arc;

use crate::cache::{PreparedRuntimeCost, PreparedRuntimeSnapshot};

use super::support::*;

#[test]
fn substituted_runtime_missing_attachment_and_wrong_cost_fail_before_eviction() {
    let cache = cache(1);
    let observer = cache.prepared_runtime_observer();
    let (resident, _) = value(&cache, COST);
    publish(&cache, "resident", &resident);
    let (attached, _) = value(&cache, COST);
    let (foreign, _) = value(&cache, COST);
    let mut pending = reservation(&cache, "substitution", COST);
    pending.track_runtime(&attached).unwrap();
    assert!(pending
        .publish_with_metadata(Arc::clone(&foreign), 13, 5)
        .is_err());
    let missing = reservation(&cache, "missing", COST);
    assert!(missing
        .publish_with_metadata(Arc::clone(&attached), 13, 5)
        .is_err());
    for altered in [
        PreparedRuntimeCost {
            source_bytes: 8,
            ..COST
        },
        PreparedRuntimeCost {
            metadata_bytes: 6,
            ..COST
        },
        PreparedRuntimeCost {
            compiled_image_bytes: 14,
            ..COST
        },
    ] {
        let mut pending = reservation(&cache, "wrong-cost", altered);
        pending.track_runtime(&attached).unwrap();
        assert!(pending
            .publish_with_metadata(
                Arc::clone(&attached),
                altered.compiled_image_bytes,
                altered.metadata_bytes
            )
            .is_err());
    }
    assert!(Arc::ptr_eq(&cache.get("resident").unwrap(), &resident));
    assert_eq!(cache.snapshot().evictions, 0);
    assert_eq!(cache.snapshot().preparing, 0);
    assert_populations(&observer, 2, 1, 0);
}

#[test]
fn wrong_ledger_double_attachment_and_republication_are_rejected() {
    let cache = cache(2);
    let other = super::support::cache(1);
    let (runtime, _) = value(&cache, COST);
    let mut wrong = reservation(&other, "wrong-ledger", COST);
    assert!(wrong.track_runtime(&runtime).is_err());
    drop(wrong);
    let mut first = reservation(&cache, "first", COST);
    first.track_runtime(&runtime).unwrap();
    assert!(first.track_runtime(&runtime).is_err());
    let mut second = reservation(&cache, "second", COST);
    assert!(second.track_runtime(&runtime).is_err());
    drop(first);
    second.track_runtime(&runtime).unwrap();
    second
        .publish_with_metadata(Arc::clone(&runtime), 13, 5)
        .unwrap();
    let mut repeated = reservation(&cache, "repeated", COST);
    assert!(repeated.track_runtime(&runtime).is_err());
    drop(repeated);
    assert!(cache.remove_matching("second", |_| true));
    let mut evicted = reservation(&cache, "evicted", COST);
    assert!(evicted.track_runtime(&runtime).is_err());
}

#[test]
fn image_and_metadata_gate_errors_preserve_residents_and_refund_pending_state() {
    let cache = cache(1);
    let (resident, _) = value(&cache, COST);
    publish(&cache, "resident", &resident);
    let (new, _) = value(&cache, COST);
    for (image_bytes, metadata_bytes) in [(101, 5), (13, 6)] {
        let mut pending = reservation(&cache, "rejected", COST);
        pending.track_runtime(&new).unwrap();
        assert!(pending
            .publish_with_metadata(Arc::clone(&new), image_bytes, metadata_bytes)
            .is_err());
    }
    assert_eq!(cache.snapshot().preparing, 0);
    assert_eq!(cache.snapshot().evictions, 0);
    assert!(Arc::ptr_eq(&cache.get("resident").unwrap(), &resident));
}

#[test]
fn registration_overflow_does_not_partially_change_any_population() {
    let cache = cache(1);
    let observer = cache.prepared_runtime_observer();
    let ledger = cache.runtime_ledger().unwrap();
    let state = observer.state.as_ref().unwrap();
    let mut full = PreparedRuntimeSnapshot::default();
    full.live.source_bytes = u64::MAX;
    full.unpublished.source_bytes = u64::MAX;
    *state.lock().unwrap() = full;
    assert!(ledger.register(COST).is_err());
    assert_eq!(*state.lock().unwrap(), full);
    *state.lock().unwrap() = PreparedRuntimeSnapshot::default();
    assert_populations(&observer, 0, 0, 0);
}
