use super::{unavailable, Result};
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, Condvar, Mutex},
    task::{Context, Poll, Waker},
};
struct Value<T> {
    value: Option<Result<T>>,
    waker: Option<Waker>,
}
pub(super) struct Reply<T> {
    inner: Arc<(Mutex<Value<T>>, Condvar)>,
}
pub(super) struct Ticket<T> {
    inner: Arc<(Mutex<Value<T>>, Condvar)>,
}
pub(super) fn channel<T>() -> (Reply<T>, Ticket<T>) {
    let inner = Arc::new((
        Mutex::new(Value {
            value: None,
            waker: None,
        }),
        Condvar::new(),
    ));
    (
        Reply {
            inner: inner.clone(),
        },
        Ticket { inner },
    )
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
        let mut v = self
            .inner
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
        let mut v = self.inner.0.lock().map_err(|_| unavailable())?;
        loop {
            if let Some(result) = v.value.take() {
                return result;
            }
            v = self.inner.1.wait(v).map_err(|_| unavailable())?;
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
public_ticket!(AuditAppendTicket, super::DurableAuditAck);
public_ticket!(AuditQueryTicket, super::AuditPage);
