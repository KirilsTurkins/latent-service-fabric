//! Private runtime/timer backing, paid through the last physical strong/weak.
use super::error;
use crate::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};
use std::{
    alloc::Layout,
    marker::PhantomData,
    ops::Deref,
    sync::{atomic::AtomicUsize, Arc, Weak},
};

const ALLOCATION_BOOKKEEPING: usize = 64;

#[derive(Debug)]
struct Charge {
    allocation: HostMemoryReservation,
}

// No Weak or raw Arc to Charge can escape. Every clone uses into_inner, so
// even concurrent final drops free this second Arc BEFORE refunding its guard.
#[derive(Debug)]
struct Billing(Option<Arc<Charge>>);
impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(Some(Arc::clone(self.0.as_ref().expect("live billing"))))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            drop(Arc::into_inner(charge));
        }
    }
}

// Only activation_runtime::Inner and timer::Inner are shipping payloads.
// Field order is essential: each physical Arc/Weak drops before its billing
// clone. Weak owns header capacity, never a strong reference to the payload.
#[derive(Debug)]
pub(super) struct Shared<T> {
    inner: Arc<T>,
    billing: Billing,
}
#[derive(Debug)]
pub(super) struct SharedWeak<T> {
    inner: Weak<T>,
    billing: Billing,
}
pub(super) struct Prepared<T> {
    allocation: HostMemoryReservation,
    payload: PhantomData<T>,
}

fn arc_bytes<T>() -> Option<usize> {
    // Pinned Rust1.97.1 ArcInner is repr(C): strong/weak AtomicUsize then T.
    // Include its actual padded backing and one bounded bookkeeping allowance.
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .ok()?
        .0
        .pad_to_align()
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
}
impl<T> Shared<T> {
    pub(super) fn allocation_bytes() -> Result<u64, PlatformError> {
        arc_bytes::<T>()
            .and_then(|payload| payload.checked_add(arc_bytes::<Charge>()?))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "runtime-shared-allocation-size",
                )
            })
    }

    // Both real allocations are prepaid before either Arc or a runtime owner
    // is created. Abandoning preparation returns unallocated capacity only.
    pub(super) fn reserve(budget: &ActivationBudget) -> Result<Prepared<T>, PlatformError> {
        Ok(Prepared {
            allocation: budget
                .reserve_host_memory(Self::allocation_bytes()?)
                .map_err(|failure| failure.to_platform_error())?,
            payload: PhantomData,
        })
    }

    pub(super) fn downgrade(&self) -> SharedWeak<T> {
        SharedWeak {
            inner: Arc::downgrade(&self.inner),
            billing: self.billing.clone(),
        }
    }
}
impl<T> Prepared<T> {
    pub(super) fn allocate(self, value: T) -> Shared<T> {
        let billing = Billing(Some(Arc::new(Charge {
            allocation: self.allocation,
        })));
        let mut shared = Shared {
            inner: Arc::new(value),
            billing,
        };
        // Both headers now exist and the wrapper owns their destruction order.
        Arc::get_mut(shared.billing.0.as_mut().expect("fresh billing"))
            .expect("fresh sole billing owner")
            .allocation
            .confirm();
        shared
    }
}
impl<T> Clone for Shared<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            billing: self.billing.clone(),
        }
    }
}
impl<T> Deref for Shared<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.inner
    }
}
impl<T> Clone for SharedWeak<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Weak::clone(&self.inner),
            billing: self.billing.clone(),
        }
    }
}
impl<T> SharedWeak<T> {
    pub(super) fn upgrade(&self) -> Option<Shared<T>> {
        Some(Shared {
            inner: self.inner.upgrade()?,
            billing: self.billing.clone(),
        })
    }
}

#[cfg(test)]
mod tests;
