//! An explicitly supplied caller timer, never preparation or execution authority.

use std::{
    alloc::Layout,
    future::Future,
    pin::Pin,
    task::{Context, Poll},
    time::Instant,
};

use latent_core::{
    ActivationBudget, BoxFuture, HostMemoryReservation, PlatformError, PlatformErrorCode,
};

/// One concrete future allocation paid by the original activation. This owns
/// only the Box layout: transitive allocations and shared executor/driver
/// infrastructure need their own funding and qualification.
///
/// Field order is part of the lifetime contract. The complete future and its
/// heap backing are dropped before the reservation, including cancellation.
/// This wrapper is returned by value; it introduces no second heap allocation.
#[must_use = "retain the future and its original charge through actual drop"]
pub struct OwnedPreparationWait<'a> {
    future: BoxFuture<'a, ()>,
    allocation: HostMemoryReservation,
}

impl<'a> OwnedPreparationWait<'a> {
    /// Reserve the actual concrete Box layout BEFORE calling its constructor.
    /// The constructor must separately cover any transitive allocation. Passing
    /// an already boxed future would pay only that outer pointer's new Box and
    /// is not how the maintained node timer uses this boundary.
    pub fn try_boxed<F>(
        budget: &ActivationBudget,
        create: impl FnOnce() -> F,
    ) -> Result<Self, PlatformError>
    where
        F: Future<Output = ()> + Send + 'a,
    {
        let bytes = u64::try_from(Layout::new::<F>().size()).map_err(|_| {
            PlatformError::new(
                PlatformErrorCode::ResourceExhausted,
                "owned timer future layout overflow",
            )
        })?;
        let allocation = budget
            .reserve_host_memory(bytes)
            .map_err(|failure| failure.to_host_memory_error())?;
        let mut owned = Self {
            future: Box::pin(create()),
            allocation,
        };
        owned.allocation.confirm();
        Ok(owned)
    }
}

impl Future for OwnedPreparationWait<'_> {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        self.get_mut().future.as_mut().poll(context)
    }
}

/// Executor-neutral timing for a bounded currentness-read wait. Implementations
/// must use one monotonic time domain for both methods. A wait belongs only to
/// the returned future: dropping it must retire its registration without a
/// detached task, worker or retained preparation. This interface cannot renew
/// a grant, extend the caller's deadline or authorize replaying owned work.
/// A host may also supply an owned instance to clock-call admission; it still
/// only schedules currentness checks before a single committed operation.
/// Its time domain must not be assumed to match a blocking worker's clock.
pub trait PreparationReadWait: Send + Sync {
    fn now(&self) -> Instant;

    /// Completes only once `now()` reaches the supplied deadline. Polling an
    /// unexpired wait must yield to the caller's executor rather than spin.
    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()>;

    /// Explicit activation-owned route; never fall back to the legacy method.
    /// Unknown implementations refuse before constructing or polling a timer.
    /// The original accepted caller supplies its own unchanged budget/deadline.
    fn wait_until_owned<'a>(
        &'a self,
        _deadline: Instant,
        _budget: &ActivationBudget,
    ) -> Result<OwnedPreparationWait<'a>, PlatformError> {
        Err(PlatformError::new(
            PlatformErrorCode::Unavailable,
            "activation-owned timer wait unavailable",
        ))
    }
}

#[cfg(test)]
mod tests;
