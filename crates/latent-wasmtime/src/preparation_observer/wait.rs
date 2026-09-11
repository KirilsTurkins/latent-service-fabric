use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::{PlatformError, PlatformErrorCode};

use super::state::Inner;

pub(super) struct Changed {
    pub(super) inner: Arc<Inner>,
    pub(super) revision: u64,
    pub(super) registration: Option<u64>,
}

impl Future for Changed {
    type Output = Result<u64, PlatformError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let incoming = cx.waker().clone();
        let mut state = this.inner.lock();
        if state.revision != this.revision {
            let previous = if state
                .waiter
                .as_ref()
                .is_some_and(|(id, _)| Some(*id) == this.registration)
            {
                state.waiter.take()
            } else {
                None
            };
            let revision = state.revision;
            drop(state);
            drop(previous);
            return Poll::Ready(Ok(revision));
        }
        if state
            .waiter
            .as_ref()
            .is_some_and(|(id, _)| Some(*id) != this.registration)
        {
            return Poll::Ready(Err(crate::containment::platform_error(
                PlatformErrorCode::Unavailable,
                "preparation-observer-waiter-limit",
                true,
            )));
        }
        let id = if let Some(id) = this.registration {
            id
        } else {
            let Some(next) = state.next_waiter.checked_add(1) else {
                return Poll::Ready(Err(crate::containment::platform_error(
                    PlatformErrorCode::Unavailable,
                    "preparation-observer-generation-exhausted",
                    false,
                )));
            };
            state.next_waiter = next;
            this.registration = Some(next);
            next
        };
        let previous = state.waiter.replace((id, incoming));
        drop(state);
        drop(previous);
        Poll::Pending
    }
}

impl Drop for Changed {
    fn drop(&mut self) {
        let mut state = self.inner.lock();
        let previous = if state
            .waiter
            .as_ref()
            .is_some_and(|(id, _)| Some(*id) == self.registration)
        {
            state.waiter.take()
        } else {
            None
        };
        drop(state);
        drop(previous);
    }
}
