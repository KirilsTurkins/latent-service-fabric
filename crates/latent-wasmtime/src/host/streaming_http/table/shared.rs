//! Closed shared table allocations: every clone retires via Arc::into_inner.
use super::{Error, HttpError};
use latent_core::HostMemoryReservation;
use std::{
    alloc::Layout,
    ops::Deref,
    sync::{atomic::AtomicUsize, Arc},
};

pub(super) const ALLOCATION_BOOKKEEPING: usize = 64;

// The only shipping T are AtomicU64 and SessionResourceTableReservation.
// No Weak, raw Arc, owner mutation or inner Arc can escape this private module.
struct Inner<T> {
    value: T,
    // Payload first, reservation last, AFTER the Arc backing itself was freed.
    memory: Option<HostMemoryReservation>,
}
pub(super) struct Shared<T> {
    inner: Option<Arc<Inner<T>>>,
}
impl<T> Shared<T> {
    pub(super) fn allocation_bytes() -> Result<u64, Error> {
        // Pinned Rust1.97.1 alloc/sync.rs ArcInner is repr(C), with strong and
        // weak AtomicUsize followed by T. Its allocator uses extend/pad_to_align.
        // [AtomicUsize;2] is that exact finite header, not Arc<T>'s handle size.
        Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<Inner<T>>())
            .ok()
            .and_then(|(layout, _)| {
                layout
                    .pad_to_align()
                    .size()
                    .checked_add(ALLOCATION_BOOKKEEPING)
            })
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(|| HttpError::BudgetExhausted.into())
    }

    // The caller obtains this exact capacity from the original sealed table
    // reservation before allocation. None is returned by that API only for
    // Phase1; selected execution has no unaccounted retry/fallback.
    pub(super) fn new(value: T, memory: Option<HostMemoryReservation>) -> Result<Self, Error> {
        let bytes = Self::allocation_bytes()?;
        if memory.as_ref().is_some_and(|owner| owner.bytes() < bytes) {
            return Err(HttpError::BudgetExhausted.into());
        }
        let mut shared = Self {
            inner: Some(Arc::new(Inner { value, memory })),
        };
        // Install the closed wrapper before confirmation, so even an unwind
        // retires via into_inner instead of ordinary Arc-inner destruction.
        let inner = Arc::get_mut(shared.inner.as_mut().unwrap()).unwrap();
        if let Some(memory) = &mut inner.memory {
            memory.confirm();
        }
        Ok(shared)
    }
}
impl<T> Clone for Shared<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Some(Arc::clone(self.inner.as_ref().unwrap())),
        }
    }
}
impl<T> Deref for Shared<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.inner.as_ref().unwrap().value
    }
}
impl<T> Drop for Shared<T> {
    fn drop(&mut self) {
        if let Some(inner) = self.inner.take() {
            // Every private clone takes this path. Unlike try_unwrap().ok(),
            // concurrent final drops guarantee one returned Inner. With no Weak,
            // into_inner frees the allocation BEFORE returning the payload.
            drop(Arc::into_inner(inner));
        }
    }
}

#[cfg(test)]
mod tests;
