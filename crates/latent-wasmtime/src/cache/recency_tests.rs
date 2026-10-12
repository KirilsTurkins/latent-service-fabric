//! Compare the real cache against a deliberately simple independent LRU model.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;

use super::{CacheLimits, PrepareAccess, PreparedCache};

struct Reference {
    entries: HashMap<String, u64>,
    oldest_first: VecDeque<String>,
    capacity: usize,
    hits: u64,
    misses: u64,
    evictions: u64,
    invalidations: u64,
}

impl Reference {
    fn new(capacity: usize) -> Self {
        Self {
            entries: HashMap::new(),
            oldest_first: VecDeque::new(),
            capacity,
            hits: 0,
            misses: 0,
            evictions: 0,
            invalidations: 0,
        }
    }

    fn get(&mut self, key: &str) -> Option<u64> {
        let Some(value) = self.entries.get(key).copied() else {
            self.misses += 1;
            return None;
        };
        self.hits += 1;
        self.oldest_first.retain(|entry| entry != key);
        self.oldest_first.push_back(key.to_owned());
        Some(value)
    }

    fn invalidate(&mut self, key: &str, matches: bool) -> bool {
        if !matches || self.entries.remove(key).is_none() {
            return false;
        }
        self.oldest_first.retain(|entry| entry != key);
        self.invalidations += 1;
        true
    }

    fn check(&self, cache: &PreparedCache<u64>) {
        let actual = cache.snapshot();
        assert_eq!(actual.entries, self.entries.len());
        assert_eq!(actual.maximum_entries, self.capacity);
        assert_eq!(actual.source_bytes, self.entries.len());
        assert_eq!(actual.metadata_bytes, self.entries.len());
        assert_eq!(actual.compiled_image_bytes, self.entries.len());
        assert_eq!(actual.preparing, 0);
        assert_eq!(actual.preparing_source_bytes, 0);
        assert_eq!(actual.preparing_metadata_bytes, 0);
        assert_eq!(actual.hits, self.hits);
        assert_eq!(actual.misses, self.misses);
        assert_eq!(actual.evictions, self.evictions);
        assert_eq!(actual.invalidations, self.invalidations);
        assert!(cache.lock().entries.allocated_slots() <= self.capacity);
        assert_eq!(self.oldest_first.len(), self.entries.len());
    }
}

fn lookup(cache: &PreparedCache<u64>, model: &mut Reference, key: &str) {
    assert_eq!(cache.get(key).as_deref().copied(), model.get(key));
}

fn publish(cache: &Arc<PreparedCache<u64>>, model: &mut Reference, key: String, value: u64) {
    let expected = model.get(&key);
    match cache.begin(key.clone(), 1, 1).expect("bounded preparation") {
        PrepareAccess::Hit(actual) => assert_eq!(Some(*actual), expected),
        PrepareAccess::Compile(reservation) => {
            assert_eq!(expected, None);
            let victim = if model.entries.len() == model.capacity {
                let victim = model.oldest_first.pop_front().expect("full reference");
                assert!(model.entries.remove(&victim).is_some());
                model.evictions += 1;
                Some(victim)
            } else {
                None
            };
            model.entries.insert(key.clone(), value);
            model.oldest_first.push_back(key);
            reservation.publish(Arc::new(value), 1).expect("refill");
            if let Some(victim) = victim {
                // Checking the expected victim is a declared miss in both
                // models; it does not disturb the remaining recency order.
                lookup(cache, model, &victim);
            }
        }
    }
}

fn invalidate(cache: &PreparedCache<u64>, model: &mut Reference, key: &str, matches: bool) {
    assert_eq!(
        cache.remove_matching(key, |_| matches),
        model.invalidate(key, matches)
    );
}

fn key(index: usize) -> String {
    format!("reference-key-{index:05}")
}

fn fixture(capacity: usize) -> (Arc<PreparedCache<u64>>, Reference) {
    let cache = Arc::new(
        PreparedCache::new(CacheLimits {
            maximum_entries: capacity,
            maximum_source_bytes: capacity,
            maximum_metadata_bytes: capacity,
            maximum_compiled_image_bytes: capacity,
            maximum_concurrent_preparations: 1,
        })
        .expect("valid equal-cost cache"),
    );
    let mut model = Reference::new(capacity);
    assert_eq!(cache.lock().entries.allocated_slots(), 0);
    for index in 0..capacity {
        publish(&cache, &mut model, key(index), index as u64);
    }
    model.check(&cache);
    (cache, model)
}

#[test]
fn mru_middle_and_lru_promotions_preserve_exact_victims_at_all_capacities() {
    for capacity in [4, 64, 4096] {
        let (cache, mut model) = fixture(capacity);
        for step in 0..96 {
            let index = match step % 3 {
                0 => model.oldest_first.len() - 1,
                1 => model.oldest_first.len() / 2,
                _ => 0,
            };
            let promoted = model.oldest_first[index].clone();
            lookup(&cache, &mut model, &promoted);
            // A refill after every promotion distinguishes moving a hit to
            // MRU from merely returning the correct runtime.
            publish(&cache, &mut model, key(capacity + step), step as u64);
            model.check(&cache);
        }
    }
}

#[test]
fn seeded_hits_misses_invalidation_and_arena_reuse_match_reference() {
    for capacity in [4, 64, 4096] {
        let (cache, mut model) = fixture(capacity);
        let mut random = 0x6c72_755f_7472_6163_u64;
        for step in 0..8192 {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            let index = usize::try_from(random & (capacity as u64 * 2 - 1)).unwrap();
            let selected = key(index);
            match step % 5 {
                0 => {
                    if let Some(mru) = model.oldest_first.back().cloned() {
                        lookup(&cache, &mut model, &mru);
                    }
                }
                1 | 4 => lookup(&cache, &mut model, &selected),
                2 => publish(&cache, &mut model, selected, step as u64 + 10_000),
                _ => {
                    invalidate(&cache, &mut model, &selected, false);
                    invalidate(&cache, &mut model, &selected, true);
                }
            }
            if step % 31 == 0 {
                model.check(&cache);
            }
        }
        while let Some(oldest) = model.oldest_first.front().cloned() {
            invalidate(&cache, &mut model, &oldest, true);
        }
        model.check(&cache);
        assert_eq!(cache.lock().entries.allocated_slots(), capacity);
        for index in 0..capacity {
            publish(&cache, &mut model, key(index), index as u64 + 20_000);
        }
        model.check(&cache);
        assert_eq!(cache.lock().entries.allocated_slots(), capacity);
    }
}
