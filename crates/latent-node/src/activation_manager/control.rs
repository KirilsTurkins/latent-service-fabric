use std::future::{pending, Future};
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};
use latent_executor::ExecutionReport;

use super::transport_stop::TransportStop;
use crate::CancellationToken;

pub(super) fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

pub(super) fn cancelled(token: &CancellationToken) -> PlatformError {
    error(
        PlatformErrorCode::Cancelled,
        &token
            .reason()
            .unwrap_or_else(|| "activation cancelled".to_owned()),
    )
}

pub(super) fn deadline_error() -> PlatformError {
    error(
        PlatformErrorCode::DeadlineExceeded,
        "activation deadline exceeded",
    )
}

pub(super) async fn deadline(deadline: Option<Instant>, clock: &dyn ActivationClock) {
    let Some(deadline) = deadline else {
        pending::<()>().await;
        return;
    };
    loop {
        let remaining = deadline.saturating_duration_since(clock.monotonic_now());
        if remaining.is_zero() {
            return;
        }
        let observation = clock.deadline_wait_observer();
        let wait = observation.map(latent_core::DeadlineWaitObserver::arm);
        if clock.uses_system_monotonic() {
            // A system-clock deadline shares Tokio's monotonic time domain.
            tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)).await;
        } else {
            // Arbitrary injected clocks can move independently of Tokio.
            tokio::time::sleep(remaining.min(Duration::from_millis(5))).await;
        }
        if let Some(wait) = wait {
            wait.complete();
        }
        if let Some(observation) = observation {
            observation.recheck();
        }
    }
}

#[cfg(test)]
mod tests;
#[cfg(test)]
mod transport_tests;

pub(super) async fn stage<T>(
    future: impl Future<Output = Result<T, PlatformError>>,
    token: &CancellationToken,
    expiry: Option<Instant>,
    clock: &Arc<dyn ActivationClock>,
    transport: &TransportStop,
) -> Result<T, PlatformError> {
    tokio::select! {
        biased;
        () = token.cancelled() => Err(cancelled(token)),
        () = deadline(expiry, clock.as_ref()) => Err(deadline_error()),
        () = transport.interrupted() => Err(transport.failure().expect("sticky transport stop")),
        result = future => result,
    }
}

pub(super) async fn execution(
    future: impl Future<Output = ExecutionReport>,
    token: &CancellationToken,
    expiry: Option<Instant>,
    clock: &Arc<dyn ActivationClock>,
    grace: Duration,
    transport: &TransportStop,
) -> ExecutionReport {
    tokio::pin!(future);
    let interruption = tokio::select! {
        biased;
        () = token.cancelled() => cancelled(token),
        () = deadline(expiry, clock.as_ref()) => deadline_error(),
        () = transport.interrupted() => transport.failure().expect("sticky transport stop"),
        report = &mut future => return report,
    };
    match tokio::time::timeout(grace, &mut future).await {
        Ok(report) => report,
        Err(_) => ExecutionReport::quarantine(
            Err(interruption),
            "backend cleanup acknowledgement timed out",
        ),
    }
}

/// Drop the interrupted inner future before returning a panic result, so its
/// stores and ownership guards precede terminal accounting/publication.
pub(super) struct CatchPanic<F> {
    inner: Option<Pin<Box<F>>>,
}

impl<F> CatchPanic<F> {
    pub(super) fn new(future: F) -> Self {
        Self {
            inner: Some(Box::pin(future)),
        }
    }

    fn drop_inner(&mut self) -> Result<(), ()> {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(self.inner.take())))
            .map_err(|_| ())
    }
}

impl<F> Drop for CatchPanic<F> {
    fn drop(&mut self) {
        let _ = self.drop_inner();
    }
}

impl<F: Future> Future for CatchPanic<F> {
    type Output = Result<F::Output, ()>;
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let polled = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            this.inner
                .as_mut()
                .expect("live activation future")
                .as_mut()
                .poll(context)
        }));
        match polled {
            Ok(Poll::Pending) => Poll::Pending,
            Ok(Poll::Ready(value)) => Poll::Ready(this.drop_inner().map(|()| value)),
            Err(_) => {
                let _ = this.drop_inner();
                Poll::Ready(Err(()))
            }
        }
    }
}
