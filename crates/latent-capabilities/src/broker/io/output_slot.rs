//! A copied output slot and its original allocation/stream custody.
use super::{capacity, denied, PlatformError, ALLOCATION_BOOKKEEPING};
use crate::broker::network::{BoundStreamChunkReservation, StreamChunkReservation};
use latent_core::{ActivationBudget, HostMemoryReservation};
use std::{
    alloc::Layout,
    marker::PhantomData,
    ops::Deref,
    sync::{atomic::AtomicUsize, Arc},
};

fn arc_bytes<T>() -> Option<usize> {
    // The pinned ArcInner has two AtomicUsize counters followed by T.
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .ok()?
        .0
        .pad_to_align()
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
}

// The only strong Arc is created privately and moved into this trait object.
// No raw Arc or Weak escapes and the surrounding billing Arc is what is cloned.
trait OriginalStreamChunk: Send + Sync {
    fn retire(self: Arc<Self>);
}
struct StreamChunk<T> {
    _owner: T,
    _window: StreamChunkReservation,
    // This exact original-activation charge remains until the typed Arc header
    // has gone and every preceding field has completed (or unwound).
    allocation: HostMemoryReservation,
}
impl<T: Send + Sync + 'static> OriginalStreamChunk for StreamChunk<T> {
    fn retire(self: Arc<Self>) {
        // Arc::into_inner releases the private Arc header before returning T.
        // There can be only one strong owner and no Weak for this allocation.
        drop(Arc::into_inner(self).expect("private stream chunk is never cloned"));
    }
}
// Confirmation may unwind. Until installation, retain the same physical-first
// retirement rule on the stack instead of allowing an ordinary Arc drop.
struct PreparingStreamChunk<T>(Option<Arc<StreamChunk<T>>>);
impl<T> Drop for PreparingStreamChunk<T> {
    fn drop(&mut self) {
        if let Some(owner) = self.0.take() {
            drop(Arc::into_inner(owner).expect("new stream chunk is never cloned"));
        }
    }
}
struct StreamRetirement(Option<Arc<dyn OriginalStreamChunk>>);
impl Drop for StreamRetirement {
    fn drop(&mut self) {
        if let Some(owner) = self.0.take() {
            owner.retire();
        }
    }
}

/// Actual stream chunk Arc and its existing allocator allowance.
#[doc(hidden)]
pub fn stream_chunk_owner_allocation_bytes<T>() -> Option<usize> {
    arc_bytes::<StreamChunk<T>>()
}

struct OutputCharge {
    // The stream owner dies after this Arc header and before its own charge.
    stream: StreamRetirement,
    allocation: HostMemoryReservation,
}
struct Billing(Option<Arc<OutputCharge>>);
impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(billing) = self.0.take() {
            drop(Arc::into_inner(billing));
        }
    }
}

// As in session::Shared, the physical payload Arc dies before its billing.
// No Weak or raw billing Arc escapes, including during concurrent drops.
pub(super) struct OutputSlot<T> {
    value: Arc<T>,
    billing: Billing,
}
pub(super) struct PreparedOutputSlot<T> {
    allocation: Option<HostMemoryReservation>,
    value: PhantomData<T>,
}
impl<T> OutputSlot<T> {
    pub(super) fn allocation_bytes() -> Result<u64, PlatformError> {
        arc_bytes::<T>()
            .and_then(|payload| payload.checked_add(arc_bytes::<OutputCharge>()?))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(capacity)
    }
    pub(super) fn reserve(
        budget: &ActivationBudget,
    ) -> Result<PreparedOutputSlot<T>, PlatformError> {
        let allocation = if budget.profile().supports_descendants() {
            Some(
                budget
                    .reserve_host_memory(Self::allocation_bytes()?)
                    .map_err(|failure| failure.to_platform_error())?,
            )
        } else {
            None
        };
        Ok(PreparedOutputSlot {
            allocation,
            value: PhantomData,
        })
    }
    pub(super) fn has_stream(&self) -> bool {
        self.billing
            .0
            .as_ref()
            .is_some_and(|charge| charge.stream.0.is_some())
    }
    #[cfg(test)]
    pub(super) fn billing_is_absent_for_test(&self) -> bool {
        self.billing.0.is_none()
    }
    #[cfg(test)]
    pub(super) fn payload_address_for_test(&self) -> usize {
        Arc::as_ptr(&self.value) as usize
    }
    #[cfg(test)]
    pub(super) fn stream_header_for_test<U>(&self) -> Option<usize> {
        let owner = self.billing.0.as_ref()?.stream.0.as_ref()?;
        let data = Arc::as_ptr(owner) as *const () as usize;
        let (_, offset) = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<StreamChunk<U>>())
            .ok()?;
        data.checked_sub(offset)
    }
    pub(super) fn retain_stream<U: Send + Sync + 'static>(
        &mut self,
        owner: U,
        window: BoundStreamChunkReservation,
        budget: &ActivationBudget,
    ) -> Result<(), PlatformError> {
        let bytes = stream_chunk_owner_allocation_bytes::<U>()
            .filter(|bytes| *bytes <= 512)
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(capacity)?;
        let charge = self
            .billing
            .0
            .as_mut()
            .and_then(Arc::get_mut)
            .ok_or_else(denied)?;
        if charge.stream.0.is_some() {
            return Err(denied());
        }
        // The Arc's own original activation guard is separate from the stream
        // connection envelope; never infer that an arbitrary U owns that budget.
        let allocation = budget
            .reserve_host_memory(bytes)
            .map_err(|failure| failure.to_platform_error())?;
        let window = window.into_window();
        let mut prepared = PreparingStreamChunk(Some(Arc::new(StreamChunk {
            _owner: owner,
            _window: window,
            allocation,
        })));
        Arc::get_mut(prepared.0.as_mut().expect("new stream chunk"))
            .expect("new unique stream chunk")
            .allocation
            .confirm();
        charge.stream.0 = prepared
            .0
            .take()
            .map(|owner| owner as Arc<dyn OriginalStreamChunk>);
        Ok(())
    }
}
impl<T> PreparedOutputSlot<T> {
    pub(super) fn allocate(self, value: T) -> OutputSlot<T> {
        let billing = Billing(self.allocation.map(|allocation| {
            Arc::new(OutputCharge {
                stream: StreamRetirement(None),
                allocation,
            })
        }));
        let mut slot = OutputSlot {
            value: Arc::new(value),
            billing,
        };
        if let Some(billing) = slot.billing.0.as_mut() {
            Arc::get_mut(billing)
                .expect("new unique output billing")
                .allocation
                .confirm();
        }
        slot
    }
}
impl<T> Clone for OutputSlot<T> {
    fn clone(&self) -> Self {
        Self {
            value: Arc::clone(&self.value),
            billing: self.billing.clone(),
        }
    }
}
impl<T> Deref for OutputSlot<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}
