use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use super::{
    state::{Inner, Token},
    CommandWaiterError,
};

/// An internal delivery hint, never a durable receipt or permission to retry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandNotification {
    ReloadDurableState,
}

/// Affine notification source moved into the existing command driver. Finish
/// and Drop have identical notification semantics and mint no outcome/proof.
pub struct CommandNotificationOwner {
    inner: Arc<Inner>,
    token: Option<Token>,
}
impl CommandNotificationOwner {
    pub(super) fn new(inner: Arc<Inner>, token: Token) -> Self {
        Self {
            inner,
            token: Some(token),
        }
    }

    /// Call after the existing owner reaches its own disposition/cleanup path.
    /// Durable lookup may still be pending, uncertain, rejected or committed.
    pub fn notify_reload(mut self) {
        self.finish();
    }

    fn finish(&mut self) {
        let Some(token) = self.token.take() else {
            return;
        };
        let wakers = {
            let Ok(mut state) = self.inner.lock() else {
                return;
            };
            state.finish(token)
        };
        for waker in wakers.into_iter().flatten() {
            // An executor callback must not unwind a command driver's Drop or
            // prevent the other bounded waiters from observing their hint.
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| waker.wake()));
        }
    }
}
impl Drop for CommandNotificationOwner {
    fn drop(&mut self) {
        self.finish();
    }
}

/// One finite delivery slot. Dropping this future detaches only this waiter;
/// the driver and its physical command owners are never reached through it.
#[must_use = "poll under the original delivery deadline, or drop this waiter"]
pub struct CommandNotificationWaiter {
    inner: Arc<Inner>,
    token: Token,
    active: bool,
}
impl CommandNotificationWaiter {
    pub(super) fn new(inner: Arc<Inner>, token: Token) -> Self {
        Self {
            inner,
            token,
            active: true,
        }
    }
}
impl Future for CommandNotificationWaiter {
    type Output = Result<CommandNotification, CommandWaiterError>;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        if !self.active {
            return Poll::Ready(Err(CommandWaiterError::Unavailable));
        }
        // Even cloning an executor-provided waker can call host code. Do it
        // before locking, and release replaced or unused wakers after unlocking.
        let new_waker = context.waker().clone();
        let inner = Arc::clone(&self.inner);
        let Ok(mut state) = inner.lock() else {
            self.active = false;
            return Poll::Ready(Err(CommandWaiterError::Unavailable));
        };
        let Some(slot) = state
            .waiters
            .get_mut(self.token.index)
            .and_then(Option::as_mut)
            .filter(|slot| slot.generation == self.token.generation)
        else {
            self.active = false;
            return Poll::Ready(Err(CommandWaiterError::Unavailable));
        };
        if slot.notified {
            let old = state.detach(self.token);
            self.active = false;
            drop(state);
            drop(old);
            drop(new_waker);
            return Poll::Ready(Ok(CommandNotification::ReloadDurableState));
        }
        if slot
            .waker
            .as_ref()
            .is_some_and(|old| old.will_wake(context.waker()))
        {
            drop(state);
            drop(new_waker);
        } else {
            // Waker destruction can reenter host code; release it after the lock.
            let old = slot.waker.replace(new_waker);
            drop(state);
            drop(old);
        }
        Poll::Pending
    }
}
impl Drop for CommandNotificationWaiter {
    fn drop(&mut self) {
        if self.active {
            let old = self
                .inner
                .lock()
                .ok()
                .and_then(|mut state| state.detach(self.token));
            drop(old);
        }
    }
}
