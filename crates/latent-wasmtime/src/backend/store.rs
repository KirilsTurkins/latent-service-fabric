//! Observes final native counters before an abandoned store is destroyed.

use std::ops::{Deref, DerefMut};

use wasmtime::Store;

use crate::host::HostState;

pub(super) struct AccountedStore {
    store: Store<HostState>,
}

impl AccountedStore {
    pub(super) fn new(store: Store<HostState>) -> Self {
        Self { store }
    }
}

impl Deref for AccountedStore {
    type Target = Store<HostState>;

    fn deref(&self) -> &Self::Target {
        &self.store
    }
}

impl DerefMut for AccountedStore {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.store
    }
}

impl Drop for AccountedStore {
    fn drop(&mut self) {
        // Fuel is always enabled by validated engine configuration. Never invent
        // consumption if reading fails, or panic if the owner finalized early.
        // Normal completion already advanced the watermark, making this a zero
        // delta observation; future drop/unwind observes the last unsampled work.
        if let Ok(fuel) = self.store.get_fuel() {
            let peak = self.store.data().limiter.peak_memory_bytes();
            let _ = self.store.data_mut().accounting.observe_runtime(fuel, peak);
        }
    }
}
