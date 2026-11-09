//! Original on-demand Store custody and linked-image retirement admission.
//!
//! An observed incomplete teardown permanently closes this library image to
//! new backend Store admissions. The bound is the cohort admitted before
//! closure; this is not a process-wide quota across independently loaded
//! library images. This does not detect pooling decommit errors that the
//! allocator itself suppresses.

use std::alloc::Layout;
use std::any::Any;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};

use crate::cache::ActiveInstancePermit;
use crate::containment::platform_error;
use crate::host::runtime::Table;

const POISON: usize = 1usize << (usize::BITS - 1);
const BOOKKEEPING: usize = 64;
static COHORT: AtomicUsize = AtomicUsize::new(0);

/// An admitted Store retains its count on an unverified teardown. No later
/// Store can enter after the sticky poison bit has been published.
pub(crate) struct Admission {
    state: &'static AtomicUsize,
    verified: bool,
}

impl Admission {
    pub(crate) fn enter() -> Result<Self, PlatformError> {
        Self::enter_at(&COHORT)
    }

    #[cfg(test)]
    pub(crate) fn enter_with_test_state(
        state: &'static AtomicUsize,
    ) -> Result<Self, PlatformError> {
        Self::enter_at(state)
    }

    fn enter_at(state: &'static AtomicUsize) -> Result<Self, PlatformError> {
        state
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                (current < POISON - 1).then(|| current + 1)
            })
            .map_err(|_| {
                platform_error(
                    PlatformErrorCode::Unavailable,
                    "store-retirement-admission-closed",
                    false,
                )
            })?;
        Ok(Self {
            state,
            verified: false,
        })
    }

    pub(crate) fn verified(mut self) {
        self.state.fetch_sub(1, Ordering::SeqCst);
        self.verified = true;
    }
}

impl Drop for Admission {
    fn drop(&mut self) {
        if !self.verified {
            self.state.fetch_or(POISON, Ordering::SeqCst);
        }
    }
}

struct Charge {
    allocation: HostMemoryReservation,
}

// No Weak reference to this Arc can escape. The final Arc backing is destroyed
// by into_inner before its original reservation is refunded.
struct Billing(Option<Arc<Charge>>);

impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(Some(Arc::clone(
            self.0.as_ref().expect("live custody billing"),
        )))
    }
}

impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            drop(Arc::into_inner(charge));
        }
    }
}

struct State {
    table: Option<Table>,
    // The prepared runtime is released before its original active permit.
    _runtime: Arc<dyn Any + Send + Sync>,
    _permit: ActiveInstancePermit,
    anchor: Option<Custody>,
}

/// The payload Arc drops before the separate billing Arc. No Weak handles or
/// allocating operations are exposed during retirement.
pub(crate) struct Custody {
    inner: Arc<Mutex<State>>,
    billing: Billing,
}

pub(crate) struct PreparedCustody {
    allocation: HostMemoryReservation,
}

impl Clone for Custody {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            billing: self.billing.clone(),
        }
    }
}

fn arc_bytes<T>() -> Option<usize> {
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .ok()?
        .0
        .pad_to_align()
        .size()
        .checked_add(BOOKKEEPING)
}

impl Custody {
    pub(crate) fn prepare(budget: &ActivationBudget) -> Result<PreparedCustody, PlatformError> {
        let bytes = arc_bytes::<Mutex<State>>()
            .and_then(|payload| payload.checked_add(arc_bytes::<Charge>()?))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "store-custody-size",
                    false,
                )
            })?;
        let allocation = budget
            .reserve_host_memory(bytes)
            .map_err(|error| error.to_host_memory_error())?;
        Ok(PreparedCustody { allocation })
    }

    pub(crate) fn retain_runtime(&self, source: &mut Option<Table>) {
        // No potentially panicking operation may leave the original Table in
        // HostState, whose fields would then be dropped during Store unwind.
        // If lock acquisition or the invariant check panics, this intentionally
        // leaks the Table's owners; the anchored permit and poisoned admission
        // fence bound that exceptional cohort until the library image exits.
        let mut pending = std::mem::ManuallyDrop::new(source.take());
        let mut state = self
            .inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // A cell belongs to one non-Clone HostState and only this method writes
        // its initially empty table slot. Leave pending protected on violation.
        assert!(state.table.is_none(), "duplicate Store runtime table");
        std::mem::swap(&mut state.table, &mut *pending);
        let signal = state
            .table
            .as_mut()
            .map(Table::detach_cancel_for_store_retirement);
        drop(state);
        if let Some(signal) = signal {
            signal.cancel();
        }
    }

    /// Called only after constructor rollback or on-demand Store destruction
    /// has returned normally. Panics leave the pre-admitted anchor intact.
    pub(crate) fn verified(&self) {
        let anchor = self
            .inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .anchor
            .take();
        drop(anchor);
    }
}

impl PreparedCustody {
    pub(crate) fn attach<T: Any + Send + Sync>(
        self,
        runtime: Arc<T>,
        permit: ActiveInstancePermit,
    ) -> Custody {
        let billing = Billing(Some(Arc::new(Charge {
            allocation: self.allocation,
        })));
        let mut custody = Custody {
            inner: Arc::new(Mutex::new(State {
                table: None,
                _runtime: runtime,
                _permit: permit,
                anchor: None,
            })),
            billing,
        };
        Arc::get_mut(custody.billing.0.as_mut().expect("fresh custody billing"))
            .expect("fresh sole custody billing owner")
            .allocation
            .confirm();
        let anchor = custody.clone();
        custody
            .inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .anchor = Some(anchor);
        custody
    }
}

struct Factory {
    budget: ActivationBudget,
    _custody: Custody,
}

impl wasmtime::NativeMemory for Factory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
        Ok(crate::native_tables::reserve(&self.budget, bytes)?
            .expect("native factory requests nonzero backing"))
    }
}

pub(crate) fn binding(
    budget: &ActivationBudget,
    custody: Custody,
) -> wasmtime::Result<wasmtime::NativeMemoryBinding> {
    let bytes = wasmtime::NativeMemoryBinding::allocation_size::<Factory>();
    let owner = crate::native_tables::reserve(budget, bytes)?
        .expect("factory Arc has a nonzero allocation layout");
    Ok(wasmtime::NativeMemoryBinding::new(
        Factory {
            budget: budget.clone(),
            _custody: custody,
        },
        owner,
    ))
}
