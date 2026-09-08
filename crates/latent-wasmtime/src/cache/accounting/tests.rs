use std::sync::Arc;

use crate::cache::{CacheLimits, PrepareAccess, PreparedCache};

#[test]
fn untracked_cache_exposes_actual_residency_without_inventing_unique_costs() {
    let cache = Arc::new(
        PreparedCache::<u8>::new(CacheLimits {
            maximum_entries: 2,
            maximum_source_bytes: 100,
            maximum_metadata_bytes: 100,
            maximum_compiled_image_bytes: 100,
            maximum_concurrent_preparations: 1,
        })
        .expect("bounded untracked cache"),
    );
    let observer = cache.prepared_runtime_observer();
    let PrepareAccess::Compile(reservation) = cache
        .begin("actual-resident".to_owned(), 7, 11)
        .expect("preparation reservation")
    else {
        panic!("new cache has no resident hit");
    };
    let preparing = cache.accounting_snapshot();
    assert_eq!(preparing.resident.preparing, 1);
    assert_eq!(preparing.resident.preparing_source_bytes, 7);
    assert_eq!(preparing.runtimes, None);

    reservation
        .publish_with_metadata(Arc::new(9), 13, 5)
        .expect("actual publication");
    let published = cache.accounting_snapshot();
    assert_eq!(published.resident, cache.snapshot());
    assert_eq!(published.resident.entries, 1);
    assert_eq!(published.resident.source_bytes, 7);
    assert_eq!(published.resident.metadata_bytes, 5);
    assert_eq!(published.resident.compiled_image_bytes, 13);
    assert_eq!(published.resident.preparing, 0);
    assert_eq!(published.runtimes, None);

    let weak_cache = Arc::downgrade(&cache);
    drop(cache);
    assert!(weak_cache.upgrade().is_none());
    assert_eq!(observer.snapshot(), None);
}
