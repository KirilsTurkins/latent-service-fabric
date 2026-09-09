//! Bounded continuation of an existing lifecycle after its transport disappears.
mod driver;
mod snapshot;
mod state;
#[cfg(test)]
mod tests;
mod unwind;

use std::sync::Arc;
use std::time::Duration;

use latent_core::{DeadlineDiagnosticObserver, PlatformError, PlatformErrorCode};
use tokio::runtime::Handle;
use tokio::task::{AbortHandle, JoinHandle};
use tokio::time::Instant;

use super::errors::boundary_error;
use driver::Driver;
pub use snapshot::ActivationCleanupSnapshot;
pub(super) use state::CleanupSlot;
use state::Shared;

/// The unique task owner must be drained on the same live invocation runtime.
/// Drop seals and aborts conservatively; only awaited shutdown records a join.
#[must_use = "retain and shut down the cleanup driver before stopping its runtime"]
pub struct ActivationCleanupOwner {
    handle: ActivationCleanupHandle,
    task: Option<JoinHandle<()>>,
    // Shared keeps only a Weak: callback failure can abort the owned task
    // without creating a task -> Shared -> task ownership cycle.
    _abort: Arc<AbortHandle>,
}

/// Cloneable reservation/observation port. It never owns the driver task.
#[derive(Clone)]
pub struct ActivationCleanupHandle {
    shared: Arc<Shared>,
}

impl ActivationCleanupOwner {
    /// Capacity is bounded to the standalone node's existing 1..=1024 slots.
    /// The absolute handoff allowance is twice the validated backend cleanup
    /// grace, including driver scheduling and the pool disposition stage.
    pub fn start(
        capacity: usize,
        cleanup_grace: Duration,
        runtime: &Handle,
    ) -> Result<Self, PlatformError> {
        Self::start_with_observer(capacity, cleanup_grace, runtime, None)
    }

    /// Immutable, bounded diagnostic observer for an explicitly measured node.
    /// Ordinary production construction retains no observer or activation IDs.
    pub fn start_with_observer(
        capacity: usize,
        cleanup_grace: Duration,
        runtime: &Handle,
        observer: Option<DeadlineDiagnosticObserver>,
    ) -> Result<Self, PlatformError> {
        if !(1..=1024).contains(&capacity)
            || cleanup_grace.is_zero()
            || cleanup_grace > Duration::from_secs(1)
        {
            return Err(boundary_error(
                PlatformErrorCode::InvalidArgument,
                "invalid activation cleanup limits",
            ));
        }
        let allowance = cleanup_grace.checked_mul(2).ok_or_else(|| {
            boundary_error(
                PlatformErrorCode::InvalidArgument,
                "activation cleanup duration overflow",
            )
        })?;
        let mut shared = Shared::new(capacity, allowance);
        shared.observer = observer;
        let shared = Arc::new(shared);
        // Construct the Drop guard before spawn: an unpolled aborted task must
        // still seal transfers and destroy every queued lifecycle owner.
        let driver = Driver::new(Arc::clone(&shared), capacity);
        let task = runtime.spawn(driver);
        let abort = Arc::new(task.abort_handle());
        *shared
            .abort
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Arc::downgrade(&abort);
        Ok(Self {
            handle: ActivationCleanupHandle { shared },
            task: Some(task),
            _abort: abort,
        })
    }

    #[must_use]
    pub fn handle(&self) -> ActivationCleanupHandle {
        self.handle.clone()
    }

    #[must_use]
    pub fn snapshot(&self) -> ActivationCleanupSnapshot {
        self.handle.snapshot()
    }

    pub fn stop_accepting(&self) {
        self.handle.stop_accepting();
    }

    /// Uses the caller's one absolute forced-cleanup cutoff. No owner receives
    /// another useful-work budget or a renewed per-slot shutdown allowance.
    pub async fn shutdown(
        mut self,
        deadline: Instant,
    ) -> Result<ActivationCleanupSnapshot, PlatformError> {
        self.stop_accepting();
        // Keep the join in self across await so cancellation of shutdown still
        // invokes the abort fallback instead of detaching a taken JoinHandle.
        let task = self.task.as_mut().expect("owned cleanup driver");
        let result = tokio::time::timeout_at(deadline, &mut *task).await;
        let mut failed = false;
        match result {
            Ok(Ok(())) => {}
            Ok(Err(_)) => failed = true,
            Err(_) => {
                failed = true;
                self.handle.shared.seal();
                task.abort();
                let _ = task.await;
            }
        }
        self.task.take();
        failed |= self.handle.shared.retired_after(deadline);
        self.handle.shared.joined(failed);
        let snapshot = self.snapshot();
        if snapshot.failed || snapshot.reserved + snapshot.queued + snapshot.running != 0 {
            Err(boundary_error(
                PlatformErrorCode::Unavailable,
                "activation cleanup did not finish cleanly",
            ))
        } else {
            Ok(snapshot)
        }
    }
}

impl Drop for ActivationCleanupOwner {
    fn drop(&mut self) {
        if let Some(task) = self.task.take() {
            self.handle.shared.seal();
            task.abort();
        }
    }
}

impl ActivationCleanupHandle {
    #[must_use]
    pub fn snapshot(&self) -> ActivationCleanupSnapshot {
        self.shared.snapshot()
    }

    pub fn stop_accepting(&self) {
        self.shared.close();
    }

    pub(super) fn try_reserve(&self) -> Result<CleanupSlot, PlatformError> {
        self.shared.reserve()
    }
}
