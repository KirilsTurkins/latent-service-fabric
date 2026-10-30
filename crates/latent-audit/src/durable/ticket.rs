use super::{
    memory::{AuditArc, AuditCallMemory},
    unavailable, Result,
};
use std::{
    future::Future,
    pin::Pin,
    sync::{Condvar, Mutex},
    task::{Context, Poll, Waker},
};
struct Value<T> {
    value: Option<Result<T>>,
    waker: Option<Waker>,
}
type Channel<T> = (Mutex<Value<T>>, Condvar);
pub(super) struct Reply<T> {
    inner: AuditArc<Channel<T>>,
}
pub(super) struct Ticket<T> {
    state: TicketState<T>,
}
enum TicketState<T> {
    Pending(AuditArc<Channel<T>>),
    Ready(Option<Result<T>>),
}
// No projection ever exposes a pinned T; ready values may move out on poll.
impl<T> Unpin for Ticket<T> {}
pub(super) fn channel<T>(memory: &AuditCallMemory) -> Result<(Reply<T>, Ticket<T>)> {
    let prepared = memory.prepare_arc::<Channel<T>>(256)?;
    let inner = prepared.allocate(
        (
            Mutex::new(Value {
                value: None,
                waker: None,
            }),
            Condvar::new(),
        ),
        0,
    );
    Ok((
        Reply {
            inner: inner.clone(),
        },
        Ticket {
            state: TicketState::Pending(inner),
        },
    ))
}
pub(super) fn failed<T>(error: latent_core::PlatformError) -> Ticket<T> {
    Ticket {
        state: TicketState::Ready(Some(Err(error))),
    }
}
impl<T> Reply<T> {
    pub fn send(self, result: Result<T>) {
        let mut v = self
            .inner
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        v.value = Some(result);
        let w = v.waker.take();
        drop(v);
        self.inner.1.notify_all();
        if let Some(w) = w {
            w.wake();
        }
    }
}
impl<T> Drop for Reply<T> {
    fn drop(&mut self) {
        let mut v = self
            .inner
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if v.value.is_some() {
            return;
        }
        v.value = Some(Err(unavailable()));
        let w = v.waker.take();
        drop(v);
        self.inner.1.notify_all();
        if let Some(w) = w {
            w.wake();
        }
    }
}
impl<T> Future for Ticket<T> {
    type Output = Result<T>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let inner = match &mut self.get_mut().state {
            TicketState::Ready(value) => {
                return Poll::Ready(value.take().expect("completed audit ticket polled twice"))
            }
            TicketState::Pending(inner) => inner,
        };
        let mut v = inner
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(result) = v.value.take() {
            Poll::Ready(result)
        } else {
            v.waker = Some(cx.waker().clone());
            Poll::Pending
        }
    }
}
impl<T> Ticket<T> {
    fn blocking(self) -> Result<T> {
        let inner = match self.state {
            TicketState::Ready(mut value) => return value.take().expect("ready audit ticket"),
            TicketState::Pending(inner) => inner,
        };
        let mut v = inner.0.lock().map_err(|_| unavailable())?;
        loop {
            if let Some(result) = v.value.take() {
                return result;
            }
            v = inner.1.wait(v).map_err(|_| unavailable())?;
        }
    }
}
macro_rules! public_ticket {
    ($name:ident,$value:ty) => {
        pub struct $name(pub(super) Ticket<$value>);
        impl $name {
            pub async fn wait(self) -> Result<$value> {
                self.0.await
            }
            /// Only on a bounded control worker; never on Invoke or an async executor.
            pub fn blocking_wait(self) -> Result<$value> {
                self.0.blocking()
            }
        }
    };
}
public_ticket!(AuditBeginTicket, super::AuditAttempt);
public_ticket!(AuditAppendTicket, super::OwnedDurableAuditAck);
public_ticket!(AuditQueryTicket, super::AuditPage);
