//! A single pending upload frame. Empty queues retain no activation authority.
use bytes::Bytes;
use http_body::{Body, Frame, SizeHint};
use http_body_util::Full;
use latent_capabilities::broker::{io::IoInputChunk, streaming_http::StreamingHttpError};
use std::{
    convert::Infallible,
    pin::Pin,
    sync::{Arc, Mutex},
    task::{Context, Poll, Waker},
};
#[derive(Default)]
struct State {
    pending: Option<Bytes>,
    ended: bool,
    dropped: bool,
    waker: Option<Waker>,
}
pub(crate) struct Sender {
    state: Arc<Mutex<State>>,
}
pub(crate) struct Receiver {
    state: Arc<Mutex<State>>,
    remaining: Option<u64>,
}
pub(crate) enum RequestBody {
    Buffered(Full<Bytes>),
    Streaming(Receiver),
    Protocol(crate::protocol::ProtocolBody),
}
pub(crate) fn channel(length: Option<u64>) -> (Sender, RequestBody) {
    let state = Arc::new(Mutex::new(State::default()));
    (
        Sender {
            state: Arc::clone(&state),
        },
        RequestBody::Streaming(Receiver {
            state,
            remaining: length,
        }),
    )
}
impl Sender {
    pub fn send(&self, chunk: IoInputChunk) -> Result<(), StreamingHttpError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.ended || state.dropped || state.pending.is_some() {
            return Err(StreamingHttpError::InvalidState);
        }
        state.pending = Some(Bytes::from_owner(chunk));
        let wake = state.waker.take();
        drop(state);
        if let Some(wake) = wake {
            wake.wake();
        }
        Ok(())
    }
    pub fn end(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.ended = true;
        let wake = state.waker.take();
        drop(state);
        if let Some(wake) = wake {
            wake.wake();
        }
    }
}
impl Drop for Sender {
    fn drop(&mut self) {
        self.end();
    }
}
impl Drop for Receiver {
    fn drop(&mut self) {
        // A queued byte owner or waker can run code when its last reference
        // drops. Publish closure under the lock, then retire them outside it.
        let (pending, waker) = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.dropped = true;
            (state.pending.take(), state.waker.take())
        };
        drop(pending);
        drop(waker);
    }
}
impl Body for RequestBody {
    type Data = Bytes;
    type Error = Infallible;
    fn poll_frame(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Infallible>>> {
        match self.get_mut() {
            Self::Buffered(body) => Pin::new(body).poll_frame(cx),
            Self::Protocol(body) => Pin::new(body).poll_frame(cx),
            Self::Streaming(receiver) => {
                let mut state = receiver
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if let Some(data) = state.pending.take() {
                    if let Some(remaining) = &mut receiver.remaining {
                        *remaining -= data.len() as u64;
                    }
                    return Poll::Ready(Some(Ok(Frame::data(data))));
                }
                if state.ended {
                    Poll::Ready(None)
                } else {
                    state.waker = Some(cx.waker().clone());
                    Poll::Pending
                }
            }
        }
    }
    fn is_end_stream(&self) -> bool {
        match self {
            Self::Buffered(body) => body.is_end_stream(),
            Self::Protocol(body) => body.is_end_stream(),
            Self::Streaming(receiver) => {
                let state = receiver
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.ended && state.pending.is_none()
            }
        }
    }
    fn size_hint(&self) -> SizeHint {
        match self {
            Self::Buffered(body) => body.size_hint(),
            Self::Protocol(body) => body.size_hint(),
            Self::Streaming(receiver) => receiver
                .remaining
                .map_or_else(SizeHint::default, SizeHint::with_exact),
        }
    }
}

#[cfg(test)]
mod cancellation_lock_tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        TryLockError, Weak,
    };
    use std::task::Wake;

    // 1 means the detached receiver is visible without its queue lock;
    // 2 means this real destructor was called under that same lock.
    fn observe(queue: &Weak<Mutex<State>>, result: &AtomicUsize) {
        let Some(queue) = queue.upgrade() else {
            result.store(3, Ordering::SeqCst);
            return;
        };
        let observation = match queue.try_lock() {
            Ok(state) if state.dropped && state.pending.is_none() && state.waker.is_none() => 1,
            Ok(_) => 3,
            Err(TryLockError::WouldBlock) => 2,
            Err(TryLockError::Poisoned(_)) => 4,
        };
        result.store(observation, Ordering::SeqCst);
    }

    struct ReentrantWake {
        queue: Weak<Mutex<State>>,
        result: Arc<AtomicUsize>,
    }
    impl Wake for ReentrantWake {
        fn wake(self: Arc<Self>) {}
    }
    impl Drop for ReentrantWake {
        fn drop(&mut self) {
            observe(&self.queue, &self.result);
        }
    }

    struct ReentrantBytes {
        queue: Weak<Mutex<State>>,
        result: Arc<AtomicUsize>,
        bytes: [u8; 4],
    }
    impl AsRef<[u8]> for ReentrantBytes {
        fn as_ref(&self) -> &[u8] {
            &self.bytes
        }
    }
    impl Drop for ReentrantBytes {
        fn drop(&mut self) {
            observe(&self.queue, &self.result);
        }
    }

    #[test]
    fn receiver_drop_releases_last_waker_after_queue_unlock() {
        let (sender, mut body) = channel(None);
        let queue = match &body {
            RequestBody::Streaming(receiver) => Arc::downgrade(&receiver.state),
            _ => unreachable!("channel returns a streaming body"),
        };
        let result = Arc::new(AtomicUsize::new(0));
        let waker = Waker::from(Arc::new(ReentrantWake {
            queue,
            result: Arc::clone(&result),
        }));
        {
            let mut cx = Context::from_waker(&waker);
            assert!(Pin::new(&mut body).poll_frame(&mut cx).is_pending());
        }
        drop(waker);
        assert_eq!(result.load(Ordering::SeqCst), 0);
        drop(body);
        assert_eq!(result.load(Ordering::SeqCst), 1);
        drop(sender);
    }

    #[test]
    fn receiver_drop_releases_queued_bytes_after_queue_unlock() {
        let (sender, body) = channel(None);
        let queue = match &body {
            RequestBody::Streaming(receiver) => &receiver.state,
            _ => unreachable!("channel returns a streaming body"),
        };
        let result = Arc::new(AtomicUsize::new(0));
        let owner = ReentrantBytes {
            queue: Arc::downgrade(queue),
            result: Arc::clone(&result),
            bytes: *b"data",
        };
        queue.lock().unwrap().pending = Some(Bytes::from_owner(owner));
        drop(body);
        assert_eq!(result.load(Ordering::SeqCst), 1);
        drop(sender);
    }
}
