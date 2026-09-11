use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Weak};

use crate::cache::{
    CacheLimits, PrepareAccess, PrepareReservation, PreparedCache, PreparedRuntimeCharge,
    PreparedRuntimeCost, PreparedRuntimeObserver, PreparedRuntimePopulation,
    PreparedRuntimeSnapshot, TrackedPreparedValue,
};

pub(super) const COST: PreparedRuntimeCost = PreparedRuntimeCost {
    source_bytes: 7,
    metadata_bytes: 5,
    compiled_image_bytes: 13,
};

pub(super) struct Value {
    native: Native,
    // Exercise the same final-field refund ordering as PreparedRuntime.
    charge: PreparedRuntimeCharge,
}

struct Native {
    cache: Weak<PreparedCache<Value>>,
    observer: PreparedRuntimeObserver,
    drops: Arc<AtomicUsize>,
}

impl Drop for Native {
    fn drop(&mut self) {
        if let Some(cache) = self.cache.upgrade() {
            assert!(
                cache.state.try_lock().is_ok(),
                "native drop under cache lock"
            );
        }
        let state = self.observer.state.as_ref().unwrap();
        let totals = state.try_lock().expect("native drop under ledger lock");
        assert!(totals.live.runtimes > 0, "native fields precede the refund");
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

impl TrackedPreparedValue for Value {
    fn runtime_charge(&self) -> &PreparedRuntimeCharge {
        let cache = self.native.cache.upgrade().expect("live reservation");
        assert!(cache.state.try_lock().is_ok(), "getter under cache lock");
        assert!(self
            .native
            .observer
            .state
            .as_ref()
            .unwrap()
            .try_lock()
            .is_ok());
        &self.charge
    }
}

pub(super) fn cache(entries: usize) -> Arc<PreparedCache<Value>> {
    Arc::new(
        PreparedCache::new_tracked(CacheLimits {
            maximum_entries: entries,
            maximum_source_bytes: 100,
            maximum_metadata_bytes: 100,
            maximum_compiled_image_bytes: 100,
            maximum_concurrent_preparations: 4,
        })
        .unwrap(),
    )
}

pub(super) fn value(
    cache: &Arc<PreparedCache<Value>>,
    cost: PreparedRuntimeCost,
) -> (Arc<Value>, Arc<AtomicUsize>) {
    let drops = Arc::new(AtomicUsize::new(0));
    let runtime = Arc::new(Value {
        native: Native {
            cache: Arc::downgrade(cache),
            observer: cache.prepared_runtime_observer(),
            drops: Arc::clone(&drops),
        },
        charge: cache.runtime_ledger().unwrap().register(cost).unwrap(),
    });
    (runtime, drops)
}

pub(super) fn reservation(
    cache: &Arc<PreparedCache<Value>>,
    key: &str,
    cost: PreparedRuntimeCost,
) -> PrepareReservation<Value> {
    let PrepareAccess::Compile(reservation) = cache
        .begin(key.to_owned(), cost.source_bytes, cost.metadata_bytes)
        .unwrap()
    else {
        panic!("expected a fresh reservation");
    };
    reservation
}

pub(super) fn publish(cache: &Arc<PreparedCache<Value>>, key: &str, runtime: &Arc<Value>) {
    let mut reservation = reservation(cache, key, COST);
    reservation.track_runtime(runtime).unwrap();
    reservation
        .publish_with_metadata(
            Arc::clone(runtime),
            COST.compiled_image_bytes,
            COST.metadata_bytes,
        )
        .unwrap();
}

pub(super) fn population(count: u64) -> PreparedRuntimePopulation {
    PreparedRuntimePopulation {
        runtimes: count,
        source_bytes: count * 7,
        metadata_bytes: count * 5,
        compiled_image_bytes: count * 13,
    }
}

pub(super) fn assert_populations(
    observer: &PreparedRuntimeObserver,
    unpublished: u64,
    resident: u64,
    evicted_live: u64,
) {
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot {
            live: population(unpublished + resident + evicted_live),
            unpublished: population(unpublished),
            resident: population(resident),
            evicted_live: population(evicted_live),
        })
    );
}
