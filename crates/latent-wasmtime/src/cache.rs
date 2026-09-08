//! Node-shared prepared state and nonqueueing compilation reservations.
//!
//! Cached values must contain only immutable prepared state. Invocation-owned
//! stores, instances and host context belong to the backend's activation scope.

mod accounting;
mod instances;
mod limits;
#[cfg(all(test, target_os = "linux"))]
mod measurement;
#[cfg(test)]
mod tests;

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};

use latent_core::{PlatformError, PlatformErrorCode};

use crate::containment::platform_error;
pub use accounting::{
    PreparedCacheAccountingSnapshot, PreparedRuntimeObserver, PreparedRuntimePopulation,
    PreparedRuntimeSnapshot,
};
pub(crate) use instances::{ActiveInstanceGate, ActiveInstancePermit};
pub(crate) use limits::CacheLimits;
pub use limits::PreparedCacheSnapshot;

const MAXIMUM_HANDLE_BYTES: usize = 256;

pub(crate) struct PreparedCache<T> {
    limits: CacheLimits,
    state: Mutex<State<T>>,
    runtime_observer: PreparedRuntimeObserver,
}

struct State<T> {
    entries: HashMap<String, Entry<T>>,
    lru: VecDeque<String>,
    source_bytes: usize,
    metadata_bytes: usize,
    compiled_image_bytes: usize,
    preparing: HashMap<String, PreparationCost>,
    preparing_source_bytes: usize,
    preparing_metadata_bytes: usize,
    hits: u64,
    misses: u64,
    evictions: u64,
    invalidations: u64,
}

struct Entry<T> {
    runtime: Arc<T>,
    source_bytes: usize,
    metadata_bytes: usize,
    compiled_image_bytes: usize,
}

#[derive(Clone, Copy)]
struct PreparationCost {
    source_bytes: usize,
    metadata_bytes: usize,
}

pub(crate) enum PrepareAccess<T> {
    Hit(Arc<T>),
    Compile(PrepareReservation<T>),
}

/// Owns one bounded compilation slot until publication or drop.
///
/// If a caller delegates compilation, it must move this reservation into that
/// work: dropping the waiting future must not refund a still-running compiler.
pub(crate) struct PrepareReservation<T> {
    cache: Arc<PreparedCache<T>>,
    handle: String,
    active: bool,
}

impl<T> PreparedCache<T> {
    pub(crate) fn new(limits: CacheLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            limits,
            runtime_observer: PreparedRuntimeObserver::default(),
            state: Mutex::new(State {
                entries: HashMap::new(),
                lru: VecDeque::new(),
                source_bytes: 0,
                metadata_bytes: 0,
                compiled_image_bytes: 0,
                preparing: HashMap::new(),
                preparing_source_bytes: 0,
                preparing_metadata_bytes: 0,
                hits: 0,
                misses: 0,
                evictions: 0,
                invalidations: 0,
            }),
        })
    }

    pub(crate) fn get(&self, handle: &str) -> Option<Arc<T>> {
        if handle.len() > MAXIMUM_HANDLE_BYTES {
            return None;
        }
        self.lock().get(handle)
    }

    pub(crate) fn begin(
        self: &Arc<Self>,
        handle: String,
        source_bytes: usize,
        metadata_bytes: usize,
    ) -> Result<PrepareAccess<T>, PlatformError> {
        if handle.is_empty() || handle.len() > MAXIMUM_HANDLE_BYTES {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "invalid prepared component handle",
                false,
            ));
        }
        if source_bytes > self.limits.maximum_source_bytes
            || metadata_bytes > self.limits.maximum_metadata_bytes
        {
            return Err(capacity_error());
        }
        let mut state = self.lock();
        if let Some(runtime) = state.get(&handle) {
            return Ok(PrepareAccess::Hit(runtime));
        }
        if state.preparing.contains_key(&handle) {
            return Err(platform_error(
                PlatformErrorCode::Unavailable,
                "component preparation is already in progress",
                true,
            ));
        }
        if state.preparing.len() >= self.limits.maximum_concurrent_preparations {
            return Err(platform_error(
                PlatformErrorCode::Unavailable,
                "component preparation capacity is full",
                true,
            ));
        }
        // Limits validation proves these sums fit for every admitted slot.
        state.preparing_source_bytes += source_bytes;
        state.preparing_metadata_bytes += metadata_bytes;
        state.preparing.insert(
            handle.clone(),
            PreparationCost {
                source_bytes,
                metadata_bytes,
            },
        );
        Ok(PrepareAccess::Compile(PrepareReservation {
            cache: Arc::clone(self),
            handle,
            active: true,
        }))
    }

    pub(crate) fn remove_matching(&self, handle: &str, matches: impl FnOnce(&T) -> bool) -> bool {
        if handle.len() > MAXIMUM_HANDLE_BYTES {
            return false;
        }
        let removed = {
            let mut state = self.lock();
            if !state
                .entries
                .get(handle)
                .is_some_and(|entry| matches(&entry.runtime))
            {
                return false;
            }
            let removed = state.remove(handle);
            state.invalidations = state
                .invalidations
                .saturating_add(u64::from(removed.is_some()));
            removed
        };
        // Compiler-owned destructors must not run under the cache mutex.
        removed.is_some()
    }

    pub(crate) fn snapshot(&self) -> PreparedCacheSnapshot {
        let state = self.lock();
        PreparedCacheSnapshot {
            entries: state.entries.len(),
            source_bytes: state.source_bytes,
            maximum_entries: self.limits.maximum_entries,
            maximum_source_bytes: self.limits.maximum_source_bytes,
            metadata_bytes: state.metadata_bytes,
            maximum_metadata_bytes: self.limits.maximum_metadata_bytes,
            compiled_image_bytes: state.compiled_image_bytes,
            maximum_compiled_image_bytes: self.limits.maximum_compiled_image_bytes,
            preparing: state.preparing.len(),
            maximum_concurrent_preparations: self.limits.maximum_concurrent_preparations,
            preparing_source_bytes: state.preparing_source_bytes,
            preparing_metadata_bytes: state.preparing_metadata_bytes,
            hits: state.hits,
            misses: state.misses,
            evictions: state.evictions,
            invalidations: state.invalidations,
        }
    }

    fn lock(&self) -> MutexGuard<'_, State<T>> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl<T> PrepareReservation<T> {
    #[cfg(test)]
    pub(crate) fn publish(
        self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
    ) -> Result<(), PlatformError> {
        let metadata_bytes = self
            .cache
            .lock()
            .preparing
            .get(&self.handle)
            .expect("live preparation reservation")
            .metadata_bytes;
        self.publish_with_metadata(runtime, compiled_image_bytes, metadata_bytes)
    }

    /// Charges the discovered immutable metadata footprint while retaining the
    /// full reservation until compilation and validation have completed.
    pub(crate) fn publish_with_metadata(
        self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
        actual_metadata_bytes: usize,
    ) -> Result<(), PlatformError> {
        drop(self.publish_deferred(runtime, compiled_image_bytes, actual_metadata_bytes)?);
        Ok(())
    }

    /// Publication is atomic; caller destroys returned evictions outside its
    /// own registry lock as well as the cache lock.
    pub(crate) fn publish_deferred(
        mut self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
        actual_metadata_bytes: usize,
    ) -> Result<Vec<Arc<T>>, PlatformError> {
        if compiled_image_bytes > self.cache.limits.maximum_compiled_image_bytes {
            return Err(capacity_error());
        }
        let mut evicted = Vec::new();
        {
            let mut state = self.cache.lock();
            let cost = *state
                .preparing
                .get(&self.handle)
                .expect("live preparation reservation");
            if actual_metadata_bytes > cost.metadata_bytes {
                return Err(capacity_error());
            }
            let limits = &self.cache.limits;
            while state.entries.len() >= limits.maximum_entries
                || cost.source_bytes > limits.maximum_source_bytes - state.source_bytes
                || actual_metadata_bytes > limits.maximum_metadata_bytes - state.metadata_bytes
                || compiled_image_bytes
                    > limits.maximum_compiled_image_bytes - state.compiled_image_bytes
            {
                let oldest = state
                    .lru
                    .front()
                    .expect("eviction requires a resident entry")
                    .clone();
                evicted.push(state.remove(&oldest).expect("resident LRU entry").runtime);
                state.evictions = state.evictions.saturating_add(1);
            }
            state.source_bytes += cost.source_bytes;
            state.metadata_bytes += actual_metadata_bytes;
            state.compiled_image_bytes += compiled_image_bytes;
            state.entries.insert(
                self.handle.clone(),
                Entry {
                    runtime,
                    source_bytes: cost.source_bytes,
                    metadata_bytes: actual_metadata_bytes,
                    compiled_image_bytes,
                },
            );
            state.lru.push_back(self.handle.clone());
            state.finish_preparing(&self.handle);
            self.active = false;
        }
        Ok(evicted)
    }

    /// Rebind a pre-read reservation after fully verified metadata determines
    /// an untrusted source's ordinary cache identity, without a second slot.
    pub(crate) fn rekey(mut self, handle: String) -> Result<PrepareAccess<T>, PlatformError> {
        if handle.is_empty() || handle.len() > MAXIMUM_HANDLE_BYTES {
            return Err(capacity_error());
        }
        let mut state = self.cache.lock();
        if handle == self.handle {
            drop(state);
            return Ok(PrepareAccess::Compile(self));
        }
        if let Some(runtime) = state.get(&handle) {
            state.finish_preparing(&self.handle);
            self.active = false;
            return Ok(PrepareAccess::Hit(runtime));
        }
        if state.preparing.contains_key(&handle) {
            return Err(platform_error(
                PlatformErrorCode::Unavailable,
                "component preparation is already in progress",
                true,
            ));
        }
        let cost = state
            .preparing
            .remove(&self.handle)
            .expect("live preparation reservation");
        state.preparing.insert(handle.clone(), cost);
        self.handle = handle;
        drop(state);
        Ok(PrepareAccess::Compile(self))
    }
}

impl<T> Drop for PrepareReservation<T> {
    fn drop(&mut self) {
        if self.active {
            self.cache.lock().finish_preparing(&self.handle);
        }
    }
}

impl<T> State<T> {
    fn get(&mut self, handle: &str) -> Option<Arc<T>> {
        let Some(entry) = self.entries.get(handle) else {
            self.misses = self.misses.saturating_add(1);
            return None;
        };
        self.hits = self.hits.saturating_add(1);
        let runtime = Arc::clone(&entry.runtime);
        self.remove_lru(handle);
        self.lru.push_back(handle.to_owned());
        Some(runtime)
    }

    fn remove(&mut self, handle: &str) -> Option<Entry<T>> {
        let entry = self.entries.remove(handle)?;
        self.source_bytes -= entry.source_bytes;
        self.metadata_bytes -= entry.metadata_bytes;
        self.compiled_image_bytes -= entry.compiled_image_bytes;
        self.remove_lru(handle);
        Some(entry)
    }

    fn remove_lru(&mut self, handle: &str) {
        if let Some(position) = self.lru.iter().position(|candidate| candidate == handle) {
            self.lru.remove(position);
        }
    }

    fn finish_preparing(&mut self, handle: &str) {
        let cost = self
            .preparing
            .remove(handle)
            .expect("live preparation reservation");
        self.preparing_source_bytes -= cost.source_bytes;
        self.preparing_metadata_bytes -= cost.metadata_bytes;
    }
}

fn capacity_error() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "component exceeds the bounded prepared-cache byte capacity",
        false,
    )
}
