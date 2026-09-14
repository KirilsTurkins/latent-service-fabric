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
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.dropped = true;
        state.pending = None;
        state.waker = None;
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
            Self::Streaming(receiver) => receiver
                .remaining
                .map_or_else(SizeHint::default, SizeHint::with_exact),
        }
    }
}
