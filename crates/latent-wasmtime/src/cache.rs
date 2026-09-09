//! Node-shared prepared state and nonqueueing compilation reservations.
//!
//! Cached values must contain only immutable prepared state. Invocation-owned
//! stores, instances and host context belong to the backend's activation scope.

mod accounting;
mod diagnostics;
mod instances;
mod limits;
#[cfg(all(test, target_os = "linux"))]
mod measurement;
mod recency;
#[cfg(test)]
mod recency_tests;
mod reservation;
#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

use latent_core::{PlatformError, PlatformErrorCode};

use crate::containment::platform_error;
use accounting::{LedgerGuard, PreparedResidency};
pub use accounting::{
    PreparedCacheAccountingSnapshot, PreparedRuntimeObserver, PreparedRuntimePopulation,
    PreparedRuntimeSnapshot,
};
pub(crate) use accounting::{
    PreparedRuntimeCharge, PreparedRuntimeCost, PreparedRuntimeLedger, TrackedPreparedValue,
};
pub(crate) use instances::{ActiveInstanceGate, ActiveInstancePermit};
pub(crate) use limits::CacheLimits;
pub use limits::PreparedCacheSnapshot;
use recency::Recency;

const MAXIMUM_HANDLE_BYTES: usize = 256;

pub(crate) struct PreparedCache<T> {
    limits: CacheLimits,
    state: Mutex<State<T>>,
    runtime_observer: PreparedRuntimeObserver,
}

struct State<T> {
    entries: Recency<T>,
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
    residency: Option<PreparedResidency<T>>,
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
    residency: Option<PreparedResidency<T>>,
}

impl<T> PreparedCache<T> {
    pub(crate) fn new(limits: CacheLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            limits,
            runtime_observer: PreparedRuntimeObserver::default(),
            state: Mutex::new(State {
                entries: Recency::default(),
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
            residency: None,
        }))
    }

    pub(crate) fn remove_matching(&self, handle: &str, matches: impl FnOnce(&T) -> bool) -> bool {
        if handle.len() > MAXIMUM_HANDLE_BYTES {
            return false;
        }
        // Predicates can be trusted-host callbacks. Invoke them outside all
        // locks, then require the exact same runtime at removal linearization.
        let runtime = self
            .lock()
            .entries
            .peek(handle)
            .map(|entry| Arc::clone(&entry.runtime));
        let Some(runtime) = runtime else {
            return false;
        };
        if !matches(&runtime) {
            return false;
        }
        let removed = {
            let mut state = self.lock();
            if !state
                .entries
                .peek(handle)
                .is_some_and(|entry| Arc::ptr_eq(&entry.runtime, &runtime))
            {
                return false;
            }
            let mut ledger = self.runtime_observer.lock();
            let removed = state.entries.remove(handle);
            if let Some(entry) = &removed {
                state.retire(entry, ledger.as_mut());
            }
            state.invalidations = state
                .invalidations
                .saturating_add(u64::from(removed.is_some()));
            removed
        };
        // Compiler-owned destructors must not run under the cache mutex.
        removed.is_some()
    }

    pub(crate) fn snapshot(&self) -> PreparedCacheSnapshot {
        self.lock().snapshot(self.limits)
    }

    fn lock(&self) -> MutexGuard<'_, State<T>> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl<T> State<T> {
    fn get(&mut self, handle: &str) -> Option<Arc<T>> {
        let Some(runtime) = self.entries.get(handle) else {
            self.misses = self.misses.saturating_add(1);
            return None;
        };
        self.hits = self.hits.saturating_add(1);
        Some(runtime)
    }

    fn retire(&mut self, entry: &Entry<T>, ledger: Option<&mut LedgerGuard<'_>>) {
        self.source_bytes -= entry.source_bytes;
        self.metadata_bytes -= entry.metadata_bytes;
        self.compiled_image_bytes -= entry.compiled_image_bytes;
        if let Some(token) = &entry.residency {
            token.evict(ledger.expect("tracked entry belongs to tracked cache"));
        }
    }

    fn snapshot(&self, limits: CacheLimits) -> PreparedCacheSnapshot {
        PreparedCacheSnapshot {
            entries: self.entries.len(),
            source_bytes: self.source_bytes,
            maximum_entries: limits.maximum_entries,
            maximum_source_bytes: limits.maximum_source_bytes,
            metadata_bytes: self.metadata_bytes,
            maximum_metadata_bytes: limits.maximum_metadata_bytes,
            compiled_image_bytes: self.compiled_image_bytes,
            maximum_compiled_image_bytes: limits.maximum_compiled_image_bytes,
            preparing: self.preparing.len(),
            maximum_concurrent_preparations: limits.maximum_concurrent_preparations,
            preparing_source_bytes: self.preparing_source_bytes,
            preparing_metadata_bytes: self.preparing_metadata_bytes,
            hits: self.hits,
            misses: self.misses,
            evictions: self.evictions,
            invalidations: self.invalidations,
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

impl<T> Drop for PreparedCache<T> {
    fn drop(&mut self) {
        let entries = {
            let state = self
                .state
                .get_mut()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let mut ledger = self.runtime_observer.lock();
            for entry in state.entries.values() {
                if let Some(token) = &entry.residency {
                    token.evict(ledger.as_mut().expect("tracked cache ledger"));
                }
            }
            state.source_bytes = 0;
            state.metadata_bytes = 0;
            state.compiled_image_bytes = 0;
            std::mem::take(&mut state.entries)
        };
        // Every native field and runtime-owned refund runs after guards end.
        drop(entries);
    }
}

fn capacity_error() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "component exceeds the bounded prepared-cache byte capacity",
        false,
    )
}
