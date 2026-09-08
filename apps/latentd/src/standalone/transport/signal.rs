use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};

use tokio::sync::Notify;

#[derive(Default)]
pub(super) struct Signal {
    set: AtomicBool,
    notify: Arc<Notify>,
}

impl Signal {
    pub(super) fn trigger(&self) {
        self.set.store(true, Ordering::Release);
        self.notify.notify_waiters();
    }

    pub(super) fn is_set(&self) -> bool {
        self.set.load(Ordering::Acquire)
    }

    pub(super) fn listen(self: &Arc<Self>) -> SignalWaiter {
        SignalWaiter {
            signal: Arc::clone(self),
            notified: Box::pin(Arc::clone(&self.notify).notified_owned()),
        }
    }
}

pub(super) struct SignalWaiter {
    signal: Arc<Signal>,
    notified: Pin<Box<dyn Future<Output = ()> + Send>>,
}

impl Future for SignalWaiter {
    type Output = ();
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        if self.signal.is_set()
            || self.notified.as_mut().poll(cx).is_ready()
            || self.signal.is_set()
        {
            Poll::Ready(())
        } else {
            Poll::Pending
        }
    }
}
