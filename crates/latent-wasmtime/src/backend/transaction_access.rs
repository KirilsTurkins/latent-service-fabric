//! Guest access follows either pre-Store invocation or actual `HostState` Drop.

use std::sync::Arc;

use latent_executor::{ExecutionCancellation, transaction::TransactionHost};

pub(super) struct InvocationOwnership<'a> {
    pub(super) cancellation: &'a dyn ExecutionCancellation,
    pub(super) transaction: GuestAccess,
}

impl<'a> InvocationOwnership<'a> {
    pub(super) fn new(cancellation: &'a dyn ExecutionCancellation) -> Self {
        Self {
            cancellation,
            transaction: GuestAccess(cancellation.transaction_host()),
        }
    }
}

pub(super) struct GuestAccess(Option<Arc<dyn TransactionHost>>);

impl GuestAccess {
    pub(super) fn host(&self) -> Option<&Arc<dyn TransactionHost>> {
        self.0.as_ref()
    }

    /// Transfer at the infallible Access attachment, after Store preflight.
    /// `HostState` then owns the same closure through actual guest destruction.
    pub(super) fn take_host(&mut self) -> Option<Arc<dyn TransactionHost>> {
        self.0.take()
    }
}

impl Drop for GuestAccess {
    fn drop(&mut self) {
        if let Some(host) = self.0.take() {
            // No Store ever received this host. This closes guest access only;
            // the native host still needs its independent physical I/O witness.
            host.finish_guest_access();
        }
    }
}

#[cfg(test)]
mod tests;
