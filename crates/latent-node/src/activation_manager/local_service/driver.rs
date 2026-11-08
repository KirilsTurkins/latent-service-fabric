//! Parent-charged custody of the child driver's concrete future allocation.

use super::{error, ActivationHandle, ChildBudgetOwner, DescendantCancellation, ProviderCall};
use latent_capabilities::broker::LocalServiceCompletion;
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};
use std::{
    future::Future,
    marker::PhantomData,
    mem::size_of,
    pin::Pin,
    task::{Context, Poll},
};

const ALLOCATION_BOOKKEEPING: usize = 64;

fn charge<F>() -> Result<u64, PlatformError> {
    let size = size_of::<F>();
    if size == 0 {
        return Ok(0);
    }
    size.checked_add(ALLOCATION_BOOKKEEPING)
        .and_then(|bytes| u64::try_from(bytes).ok())
        .ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "local service driver capacity",
            )
        })
}

// Conservatively preserve the same original guard when destruction unwinds.
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

/// A typed reservation prepared before child delegation, without a driver.
pub(super) struct PreparedDriver<F> {
    allocation: Option<HostMemoryReservation>,
    future: PhantomData<fn() -> F>,
}

impl<F> PreparedDriver<F>
where
    F: Future<Output = ()> + Send + 'static,
{
    pub(super) fn for_factory(
        budget: &ActivationBudget,
        _factory: fn(
            ActivationHandle,
            ChildBudgetOwner,
            ProviderCall,
            DescendantCancellation,
            tokio::sync::oneshot::Sender<LocalServiceCompletion>,
        ) -> F,
    ) -> Result<Self, PlatformError> {
        Self::new(budget)
    }

    fn new(budget: &ActivationBudget) -> Result<Self, PlatformError> {
        let bytes = charge::<F>()?;
        let allocation = if bytes == 0 {
            None
        } else {
            Some(
                budget
                    .reserve_host_memory(bytes)
                    .map_err(|failure| failure.to_platform_error())?,
            )
        };
        Ok(Self {
            allocation,
            future: PhantomData,
        })
    }

    pub(super) fn finish<Make>(mut self, make: Make) -> OwnedDriver<F>
    where
        Make: FnOnce() -> F,
    {
        let future = Box::pin(make());
        let mut driver = OwnedDriver {
            future: Some(future),
            allocation: self.allocation.take(),
        };
        // The physical-first Drop is already installed if confirmation fails.
        if let Some(allocation) = &mut driver.allocation {
            allocation.confirm();
        }
        driver
    }
}

/// Tokio owns this small wrapper; the separately boxed driver and all captured
/// watcher state retire before the original parent-ledger reservation.
pub(super) struct OwnedDriver<F> {
    future: Option<Pin<Box<F>>>,
    allocation: Option<HostMemoryReservation>,
}

impl<F: Future<Output = ()>> Future for OwnedDriver<F> {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        self.get_mut()
            .future
            .as_mut()
            .expect("local service driver")
            .as_mut()
            .poll(context)
    }
}

impl<F> Drop for OwnedDriver<F> {
    fn drop(&mut self) {
        let allocation = RefundAfterRetirement(self.allocation.take());
        drop(self.future.take());
        allocation.refund();
    }
}

#[cfg(test)]
mod tests;
