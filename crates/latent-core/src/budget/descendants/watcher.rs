//! Owned descendant cancellation watchers charged to their calling activation.
//!
//! This accounts requested Box layouts and the existing finite per-allocation
//! model. Transitive allocations and allocator/process RSS are separate.

use super::{capacity, denied, ActivationBudget, PlatformError};
use crate::{BoxFuture, HostMemoryReservation};
use std::{
    future::Future,
    mem::size_of,
    pin::Pin,
    task::{Context, Poll},
    time::Instant,
};

const MAX_SIGNALS: usize = 17;
const ALLOCATION_BOOKKEEPING: usize = 64;
type Signals = [Option<OwnedCancellationFuture>; MAX_SIGNALS];

fn charge(size: usize) -> Result<u64, PlatformError> {
    if size == 0 {
        return Ok(0);
    }
    size.checked_add(ALLOCATION_BOOKKEEPING)
        .and_then(|bytes| u64::try_from(bytes).ok())
        .ok_or_else(capacity)
}

// If destruction unwinds, physical retirement was not established. Preserve
// this exact guard without allocating or manufacturing a replacement charge.
struct RefundAfterRetirement(Option<HostMemoryReservation>);
impl RefundAfterRetirement {
    fn refund(mut self) {
        drop(self.0.take());
    }
}
impl Drop for RefundAfterRetirement {
    fn drop(&mut self) {
        if let Some(allocation) = self.0.take() {
            std::mem::forget(allocation);
        }
    }
}

/// A concrete owned probe future with its original parent-ledger reservation.
pub struct OwnedCancellationFuture {
    future: Option<BoxFuture<'static, ()>>,
    allocation: Option<HostMemoryReservation>,
}

impl OwnedCancellationFuture {
    /// Reserve the concrete future layout before invoking its builder or
    /// allocating its Box. The builder must not create unrelated allocations.
    pub fn new<F, Make>(budget: &ActivationBudget, make: Make) -> Result<Self, PlatformError>
    where
        F: Future<Output = ()> + Send + 'static,
        Make: FnOnce() -> F,
    {
        let bytes = charge(size_of::<F>())?;
        let allocation = if bytes == 0 {
            None
        } else {
            Some(
                budget
                    .reserve_host_memory(bytes)
                    .map_err(|error| error.to_platform_error())?,
            )
        };
        let future = Box::pin(make());
        let mut owner = Self {
            future: Some(future),
            allocation,
        };
        if let Some(allocation) = &mut owner.allocation {
            allocation.confirm();
        }
        Ok(owner)
    }

    fn belongs_to(&self, budget: &ActivationBudget) -> bool {
        self.allocation
            .as_ref()
            .is_none_or(|allocation| allocation.is_from_budget(budget))
    }
}

impl Future for OwnedCancellationFuture {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        self.get_mut()
            .future
            .as_mut()
            .expect("owned cancellation future")
            .as_mut()
            .poll(context)
    }
}

impl Drop for OwnedCancellationFuture {
    fn drop(&mut self) {
        let allocation = RefundAfterRetirement(self.allocation.take());
        drop(self.future.take());
        allocation.refund();
    }
}

/// A bounded, owned view of the original caller's cancellation ancestry.
///
/// Its fixed backing and concrete probe futures are charged to the caller's
/// original ledger. A descendant's grant is not used to pay for this watcher.
pub struct DescendantCancellation {
    signals: Option<Box<Signals>>,
    allocation: Option<HostMemoryReservation>,
    budget: ActivationBudget,
}

impl ActivationBudget {
    /// Prepare the complete bounded watcher before child delegation/admission.
    pub fn prepare_descendant_cancellation_at(
        &self,
        now: Instant,
    ) -> Result<DescendantCancellation, PlatformError> {
        // Match the first parent-cancellation/deadline check in delegate_at.
        self.check_delegation(now)?;
        let bytes = charge(size_of::<Signals>())?;
        let allocation = self
            .reserve_host_memory(bytes)
            .map_err(|error| error.to_platform_error())?;
        // The reservation precedes the single fixed-capacity Box allocation.
        // Its local is declared before the Box so unwind destroys the Box first.
        let signals = Box::new(std::array::from_fn(|_| None));
        let mut watcher = DescendantCancellation {
            signals: Some(signals),
            allocation: Some(allocation),
            budget: self.clone(),
        };
        watcher
            .allocation
            .as_mut()
            .expect("watcher allocation")
            .confirm();

        let mut cursor = self.inner.as_ref();
        for index in 0..MAX_SIGNALS {
            let lineage = cursor.lineage.get().ok_or_else(denied)?;
            let signal = lineage.cancellation.clone().cancelled_owned(self)?;
            if !signal.belongs_to(self) {
                return Err(denied());
            }
            watcher.signals.as_mut().expect("watcher signals")[index] = Some(signal);
            let Some(parent) = &lineage.parent else {
                break;
            };
            cursor = parent.parent();
        }
        Ok(watcher)
    }
}

impl Future for DescendantCancellation {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        let this = self.get_mut();
        if this.budget.descendant_is_cancelled() {
            return Poll::Ready(());
        }
        for signal in this
            .signals
            .as_mut()
            .expect("watcher signals")
            .iter_mut()
            .flatten()
        {
            if Pin::new(signal).poll(context).is_ready() {
                return Poll::Ready(());
            }
        }
        Poll::Pending
    }
}

impl Drop for DescendantCancellation {
    fn drop(&mut self) {
        let allocation = RefundAfterRetirement(self.allocation.take());
        drop(self.signals.take());
        allocation.refund();
    }
}

#[cfg(test)]
mod tests;
