use std::future::Future;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};

use super::state::{Control, Work};
use super::StoreIoError;

pub(super) struct Reservation<S> {
    pub control: Arc<Control<S>>,
    pub bytes: u64,
}

impl<S> Drop for Reservation<S> {
    fn drop(&mut self) {
        {
            let mut state = self
                .control
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.accepted -= 1;
            state.retained_bytes -= self.bytes;
            if state.snapshot().physically_retired() {
                state.retired_at = Some(self.control.clock.monotonic_now());
            }
        }
        self.control.notify();
    }
}

struct Completed<T> {
    result: Result<T, StoreIoError>,
    reservation: Box<dyn Send>,
}

struct Response<T> {
    ready: Option<Completed<T>>,
    detached: bool,
    delivered: bool,
    waker: Option<Waker>,
}

pub(super) struct Completion<T>(Mutex<Response<T>>);

impl<T> Completion<T> {
    pub fn new() -> Self {
        Self(Mutex::new(Response {
            ready: None,
            detached: false,
            delivered: false,
            waker: None,
        }))
    }

    fn finish(&self, result: Result<T, StoreIoError>, reservation: Box<dyn Send>) {
        let completed = Completed {
            result,
            reservation,
        };
        let waker = {
            let mut response = self
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if response.detached {
                drop(response);
                drop(completed);
                return;
            }
            response.ready = Some(completed);
            response.waker.take()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
    }
}

pub(super) struct TypedWork<S, T, F> {
    pub operation: F,
    pub completion: Arc<Completion<T>>,
    pub reservation: Reservation<S>,
}

impl<S: Send + Sync + 'static, T: Send + 'static, F: FnOnce(&S) -> T + Send> Work<S>
    for TypedWork<S, T, F>
{
    fn run(self: Box<Self>, store: &S) {
        let Self {
            operation,
            completion,
            reservation,
        } = *self;
        let result = catch_unwind(AssertUnwindSafe(|| operation(store)))
            .map_err(|_| StoreIoError::RecoveryRequired);
        if result.is_err() {
            reservation.control.fail(StoreIoError::RecoveryRequired);
        }
        completion.finish(result, Box::new(reservation));
    }

    fn reject(self: Box<Self>) {
        let Self {
            operation,
            completion,
            reservation,
        } = *self;
        drop(operation);
        completion.finish(Err(StoreIoError::NotStarted), Box::new(reservation));
    }
}

/// One bounded response waiter, independent of the accepted physical operation.
#[must_use = "dropping the waiter detaches the response; accepted store work continues"]
pub struct StoreIoJob<T> {
    completion: Arc<Completion<T>>,
}

impl<T> StoreIoJob<T> {
    pub(super) fn new(completion: Arc<Completion<T>>) -> Self {
        Self { completion }
    }
}

impl<T> Future for StoreIoJob<T> {
    type Output = Result<T, StoreIoError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let completed = {
            let mut response = self
                .completion
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if response.delivered {
                return Poll::Ready(Err(StoreIoError::AlreadyDelivered));
            }
            if let Some(completed) = response.ready.take() {
                response.delivered = true;
                Some(completed)
            } else {
                response.waker = Some(cx.waker().clone());
                None
            }
        };
        if let Some(Completed {
            result,
            reservation,
        }) = completed
        {
            drop(reservation);
            Poll::Ready(result)
        } else {
            Poll::Pending
        }
    }
}

impl<T> Drop for StoreIoJob<T> {
    fn drop(&mut self) {
        let ready = {
            let mut response = self
                .completion
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            response.detached = true;
            response.waker = None;
            response.ready.take()
        };
        // Destroy returned bytes before refunding their reservation, outside
        // response/control locks. An accepted queued/active job owns its permit.
        drop(ready);
    }
}
