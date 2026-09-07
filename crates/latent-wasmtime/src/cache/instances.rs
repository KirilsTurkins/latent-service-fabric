use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode};

use crate::containment::platform_error;

/// Factory-shared, nonqueueing limit acquired before pinning a prepared runtime.
pub(crate) struct ActiveInstanceGate {
    active: AtomicUsize,
    maximum: usize,
}

impl ActiveInstanceGate {
    pub(crate) fn new(maximum: usize) -> Result<Self, PlatformError> {
        if maximum == 0 {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "active Wasmtime instance capacity must be positive",
                false,
            ));
        }
        Ok(Self {
            active: AtomicUsize::new(0),
            maximum,
        })
    }

    pub(crate) fn try_acquire(self: &Arc<Self>) -> Result<ActiveInstancePermit, PlatformError> {
        self.active
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                (active < self.maximum).then(|| active + 1)
            })
            .map_err(|_| {
                platform_error(
                    PlatformErrorCode::Unavailable,
                    "active Wasmtime instance capacity is full",
                    true,
                )
            })?;
        Ok(ActiveInstancePermit {
            gate: Arc::clone(self),
        })
    }

    #[cfg(test)]
    pub(crate) fn active(&self) -> usize {
        self.active.load(Ordering::Acquire)
    }
}

/// Retained until activation cleanup, including unwind or a dropped future.
pub(crate) struct ActiveInstancePermit {
    gate: Arc<ActiveInstanceGate>,
}

impl Drop for ActiveInstancePermit {
    fn drop(&mut self) {
        let previous = self.gate.active.fetch_sub(1, Ordering::AcqRel);
        debug_assert!(previous > 0, "active Wasmtime instance capacity underflow");
    }
}
