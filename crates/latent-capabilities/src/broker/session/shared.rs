//! Closed session/stats backing, paid through the last physical strong/weak.
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError};
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
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            drop(Arc::into_inner(charge));
        }
    }
}

// Only SessionCore, Stats, HandleEntry and io::Operation are shipping payloads.
// Field order is essential: each physical Arc/Weak drops before its billing
// clone. Weak owns header capacity, never a strong reference to the payload.
#[derive(Debug)]
pub(in crate::broker) struct Shared<T> {
    inner: Arc<T>,
    billing: Billing,
}
#[derive(Debug)]
pub(in crate::broker) struct SharedWeak<T> {
    inner: Weak<T>,
    billing: Billing,
}
pub(in crate::broker) struct Prepared<T> {
    allocation: Option<HostMemoryReservation>,
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
    pub(in crate::broker) fn allocation_bytes() -> Result<u64, PlatformError> {
        arc_bytes::<T>()
            .and_then(|payload| payload.checked_add(arc_bytes::<Charge>()?))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(super::super::capacity)
    }

    // Both real allocations are prepaid before either Arc or a session owner
    // is created. Abandoning preparation returns unallocated capacity only.
    pub(in crate::broker) fn reserve(
        budget: &ActivationBudget,
    ) -> Result<Prepared<T>, PlatformError> {
        let allocation = if budget.profile().supports_descendants() {
            Some(
                budget
                    .reserve_host_memory(Self::allocation_bytes()?)
                    .map_err(|failure| failure.to_platform_error())?,
            )
        } else {
            None
        };
        Ok(Prepared {
            allocation,
            payload: PhantomData,
        })
    }

    pub(in crate::broker) fn ptr_eq(left: &Self, right: &Self) -> bool {
        Arc::ptr_eq(&left.inner, &right.inner)
    }

    pub(in crate::broker) fn downgrade(&self) -> SharedWeak<T> {
        SharedWeak {
            inner: Arc::downgrade(&self.inner),
            billing: self.billing.clone(),
        }
    }
}
impl<T> Prepared<T> {
    pub(in crate::broker) fn allocate(self, value: T) -> Shared<T> {
        // Legacy profiles retain their original payload Arc; no auxiliary
        // billing allocation or native reservation is invented for them.
        let billing = Billing(
            self.allocation
                .map(|allocation| Arc::new(Charge { allocation })),
        );
        let mut shared = Shared {
            inner: Arc::new(value),
            billing,
        };
        // Both headers now exist and the wrapper owns their destruction order.
        if let Some(billing) = shared.billing.0.as_mut() {
            Arc::get_mut(billing)
                .expect("fresh sole billing owner")
                .allocation
                .confirm();
        }
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
impl<T> Default for SharedWeak<T> {
    fn default() -> Self {
        Self {
            inner: Weak::new(),
            billing: Billing(None),
        }
    }
}
impl<T> SharedWeak<T> {
    pub(in crate::broker) fn ptr_eq_shared(&self, owner: &Shared<T>) -> bool {
        self.inner.as_ptr() == Arc::as_ptr(&owner.inner)
    }

    pub(in crate::broker) fn strong_count(&self) -> usize {
        self.inner.strong_count()
    }

    pub(in crate::broker) fn upgrade(&self) -> Option<Shared<T>> {
        Some(Shared {
            inner: self.inner.upgrade()?,
            billing: self.billing.clone(),
        })
    }
}

#[cfg(test)]
mod tests;
