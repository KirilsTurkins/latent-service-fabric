//! Observes final native counters before an abandoned store is destroyed.

use std::ops::{Deref, DerefMut};

use wasmtime::Store;

use crate::host::HostState;
use crate::store_custody::{Admission, Custody};

pub(super) struct Retirement {
    admission: Option<Admission>,
    custody: Option<Custody>,
}

impl Retirement {
    pub(super) fn new(admission: Admission, custody: Option<Custody>) -> Self {
        Self {
            admission: Some(admission),
            custody,
        }
    }

    pub(super) fn verified(&mut self) {
        if let Some(custody) = &self.custody {
            custody.verified();
        }
        if let Some(admission) = self.admission.take() {
            admission.verified();
        }
    }
}

pub(super) struct AccountedStore {
    store: Option<Store<HostState>>,
    retirement: Retirement,
}

impl AccountedStore {
    pub(super) fn new(store: Store<HostState>, retirement: Retirement) -> Self {
        Self {
            store: Some(store),
            retirement,
        }
    }
}

impl Deref for AccountedStore {
    type Target = Store<HostState>;

    fn deref(&self) -> &Self::Target {
        self.store.as_ref().expect("live accounted Store")
    }
}

impl DerefMut for AccountedStore {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.store.as_mut().expect("live accounted Store")
    }
}

impl Drop for AccountedStore {
    fn drop(&mut self) {
        // Fuel is always enabled by validated engine configuration. Never invent
        // consumption if reading fails, or panic if the owner finalized early.
        // Normal completion already advanced the watermark, making this a zero
        // delta observation; future drop/unwind observes the last unsampled work.
        if let Some(store) = self.store.as_mut() {
            if let Ok(fuel) = store.get_fuel() {
                let peak = store.data().limiter.peak_memory_bytes();
                let _ = store.data_mut().accounting.observe_runtime(fuel, peak);
            }
        }
        // If actual destruction panics, Retirement's unverified admission
        // poisons this linked image and the prepaid custody anchor remains.
        drop(self.store.take());
        self.retirement.verified();
    }
}
