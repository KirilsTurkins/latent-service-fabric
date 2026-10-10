use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll};
use std::time::Instant;

use latent_core::{ActivationClock, SystemActivationClock};

use super::{
    StoreIoDrain, StoreIoError, StoreIoJob, StoreIoKind, StoreIoLimits, StoreIoOwner,
    StoreIoSnapshot, StoreIoStartError,
};

/// Startup is one charged job on the same fixed workers that later own I/O.
/// Readiness is delivered only after protected open/engine verification returns.
#[must_use = "startup completion establishes engine readiness; detachment is not abort proof"]
pub struct StoreIoStartup<S> {
    owner: Option<StoreIoOwner<OnceLock<S>>>,
    job: StoreIoJob<Result<(), StoreIoError>>,
}

/// An initialized engine; callbacks borrow S only on the fixed I/O workers.
pub struct StoreIoReady<S> {
    owner: StoreIoOwner<OnceLock<S>>,
}

impl<S> Clone for StoreIoReady<S> {
    fn clone(&self) -> Self {
        Self {
            owner: self.owner.clone(),
        }
    }
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    pub fn initialize(
        initializer: impl FnOnce() -> Result<S, StoreIoError> + Send + 'static,
        initialization_bytes: u64,
        limits: StoreIoLimits,
        finalizer: impl FnOnce(&S) -> Result<(), StoreIoError> + Send + 'static,
    ) -> Result<StoreIoStartup<S>, StoreIoStartError<OnceLock<S>>> {
        Self::initialize_with_clock(
            initializer,
            initialization_bytes,
            limits,
            finalizer,
            Arc::new(SystemActivationClock),
        )
    }

    pub fn initialize_with_clock(
        initializer: impl FnOnce() -> Result<S, StoreIoError> + Send + 'static,
        initialization_bytes: u64,
        limits: StoreIoLimits,
        finalizer: impl FnOnce(&S) -> Result<(), StoreIoError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<StoreIoStartup<S>, StoreIoStartError<OnceLock<S>>> {
        let owner = StoreIoOwner::with_clock(
            OnceLock::new(),
            limits,
            move |slot| slot.get().map_or(Ok(()), finalizer),
            clock,
        )?;
        let monitor = Arc::clone(&owner.inner.control);
        let job = owner.submit(StoreIoKind::Write, initialization_bytes, move |slot| {
            let result = initializer()
                .and_then(|store| slot.set(store).map_err(|_| StoreIoError::RecoveryRequired));
            if let Err(error) = result {
                monitor.fail(error);
            }
            result
        });
        match job {
            Ok(job) => Ok(StoreIoStartup {
                owner: Some(owner),
                job,
            }),
            Err(error) => {
                owner.quarantine();
                Err(StoreIoStartError {
                    reason: error.reason,
                    owner: Some(owner),
                    store: None,
                })
            }
        }
    }
}

impl<S: Send + Sync + 'static> StoreIoStartup<S> {
    pub(crate) fn failure_gate(&self) -> Option<impl Fn(StoreIoError) + Send + Sync + 'static> {
        let control = Arc::clone(&self.owner.as_ref()?.inner.control);
        Some(move |error| control.fail(error))
    }

    pub fn snapshot(&self) -> Result<StoreIoSnapshot, StoreIoError> {
        self.owner
            .as_ref()
            .ok_or(StoreIoError::AlreadyDelivered)?
            .snapshot()
    }

    pub fn quarantine(&self) {
        if let Some(owner) = &self.owner {
            owner.quarantine();
        }
    }

    pub fn close(&self) {
        if let Some(owner) = &self.owner {
            owner.close();
        }
    }

    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<StoreIoDrain<OnceLock<S>, F>, StoreIoError> {
        self.owner
            .as_ref()
            .ok_or(StoreIoError::AlreadyDelivered)?
            .drain_async(deadline, wait)
    }
}

impl<S> Future for StoreIoStartup<S> {
    type Output = Result<StoreIoReady<S>, StoreIoError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        match Pin::new(&mut this.job).poll(cx) {
            Poll::Ready(Ok(Ok(()))) => {
                if let Some(owner) = &this.owner {
                    let state = owner
                        .inner
                        .control
                        .state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner);
                    if state.closed || state.quarantined || state.failure.is_some() {
                        return Poll::Ready(Err(state
                            .failure
                            .unwrap_or(StoreIoError::AdmissionClosed)));
                    }
                }
                let Some(owner) = this.owner.take() else {
                    return Poll::Ready(Err(StoreIoError::AlreadyDelivered));
                };
                Poll::Ready(Ok(StoreIoReady { owner }))
            }
            Poll::Ready(Ok(Err(error)) | Err(error)) => {
                if let Some(owner) = &this.owner {
                    owner.inner.control.close(true);
                }
                Poll::Ready(Err(error))
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

impl<S: Send + Sync + 'static> StoreIoReady<S> {
    #[cfg(test)]
    pub(crate) fn wait_for_snapshot(
        &self,
        timeout: std::time::Duration,
        ready: impl Fn(StoreIoSnapshot) -> bool,
    ) {
        self.owner.wait_for_snapshot(timeout, ready);
    }

    /// Validate the original immutable recovery partition; never create workers
    /// or change the ownership of admitted physical work.
    pub fn install_recovery_capacity(
        &self,
        reserve: super::StoreIoRecoveryCapacity,
    ) -> Result<(), StoreIoError> {
        self.owner.install_recovery_capacity(reserve)
    }

    pub fn recovery_snapshot(&self) -> Result<super::StoreIoRecoverySnapshot, StoreIoError> {
        self.owner.recovery_snapshot()
    }

    pub fn submit_recovery<T: Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(&S) -> T + Send + 'static,
    ) -> Result<StoreIoJob<T>, StoreIoError> {
        self.owner
            .submit_recovery(kind, bytes, move |slot| {
                operation(slot.get().expect("initialized store owner"))
            })
            .map_err(|error| error.reason)
    }

    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(crate) fn wait_test_metadata_retirement(&self, deadline: Instant) {
        let control = &self.owner.inner.control;
        let mut state = control.state.lock().unwrap();
        while state.accepted != 0
            || state.active_reads != 0
            || state.active_writes != 0
            || state.active_recovery_reads != 0
        {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .expect("actual native metadata retirement deadline expired");
            let (next, timeout) = control.changed.wait_timeout(state, remaining).unwrap();
            state = next;
            assert!(
                !timeout.timed_out(),
                "actual native metadata did not retire"
            );
        }
        // Test synchronization only. Production custody independently reserves
        // under this SAME lock and still rejects newly arrived work/native pins.
    }

    pub(crate) fn failure_gate(&self) -> impl Fn(StoreIoError) + Send + Sync + 'static {
        let control = Arc::clone(&self.owner.inner.control);
        move |error| control.fail(error)
    }

    pub fn reserve_retained<T: Send + 'static>(
        &self,
        bytes: u64,
    ) -> Result<super::StoreIoRetained<OnceLock<S>, T>, StoreIoError> {
        self.owner.reserve_retained(bytes)
    }

    pub fn reserve_recovery_retained<T: Send + 'static>(
        &self,
        bytes: u64,
    ) -> Result<super::StoreIoRetained<OnceLock<S>, T>, StoreIoError> {
        self.owner.reserve_recovery_retained(bytes)
    }

    pub(crate) fn reserve_custody<T: Send + 'static>(
        &self,
        bytes: u64,
        deadline: Instant,
        keeper: Arc<dyn std::any::Any + Send + Sync>,
    ) -> Result<super::StoreIoCustody<OnceLock<S>, T>, StoreIoError> {
        self.owner.reserve_custody(bytes, deadline, keeper)
    }

    pub(crate) fn submit_custody<T: Send + 'static, R: Send + 'static>(
        &self,
        custody: super::StoreIoCustody<OnceLock<S>, T>,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(&mut super::StoreIoCustody<OnceLock<S>, T>, &S) -> R + Send + 'static,
    ) -> Result<StoreIoJob<(super::StoreIoCustody<OnceLock<S>, T>, R)>, StoreIoError> {
        self.owner
            .submit_custody(custody, kind, bytes, move |custody, slot| {
                operation(custody, slot.get().expect("initialized store owner"))
            })
    }

    pub(crate) fn owns_retained<T: Send + 'static>(
        &self,
        retained: &super::StoreIoRetained<OnceLock<S>, T>,
    ) -> bool {
        retained.belongs_to(&self.owner)
    }

    pub fn submit<T: Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(&S) -> T + Send + 'static,
    ) -> Result<StoreIoJob<T>, StoreIoError> {
        self.owner
            .submit(kind, bytes, move |slot| {
                operation(slot.get().expect("initialized store owner"))
            })
            .map_err(|error| error.reason)
    }

    pub fn submit_retaining<T: Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        keeper: Arc<dyn std::any::Any + Send + Sync>,
        operation: impl FnOnce(&S) -> T + Send + 'static,
    ) -> Result<StoreIoJob<T>, StoreIoError> {
        self.owner
            .submit_retaining(kind, bytes, keeper, move |slot| {
                operation(slot.get().expect("initialized store owner"))
            })
            .map_err(|error| error.reason)
    }

    pub fn snapshot(&self) -> Result<StoreIoSnapshot, StoreIoError> {
        self.owner.snapshot()
    }
    pub fn close(&self) {
        self.owner.close();
    }
    pub fn quarantine(&self) {
        self.owner.quarantine();
    }
    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<StoreIoDrain<OnceLock<S>, F>, StoreIoError> {
        self.owner.drain_async(deadline, wait)
    }
    pub fn reap_retired_threads(&self) -> Result<usize, StoreIoError> {
        self.owner.reap_retired_threads()
    }
}
