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
    preparing: bool,
    waker: Option<Waker>,
}

// The permit must fit the existing queue allocation on every build target.
// Match the former fields and their drop glue without constructing this type.
#[allow(dead_code)]
struct OriginalStateLayout {
    pending: Option<Bytes>,
    ended: bool,
    dropped: bool,
    waker: Option<Waker>,
}
const _: () = {
    assert!(std::mem::size_of::<State>() == std::mem::size_of::<OriginalStateLayout>());
    assert!(std::mem::align_of::<State>() == std::mem::align_of::<OriginalStateLayout>());
    assert!(
        std::mem::size_of::<Mutex<State>>() == std::mem::size_of::<Mutex<OriginalStateLayout>>()
    );
    assert!(
        std::mem::align_of::<Mutex<State>>() == std::mem::align_of::<Mutex<OriginalStateLayout>>()
    );
};

// No caller-owned value is held here. A preparation panic clears admission
// without running a byte owner or waker under the queue mutex.
struct SendPreparation<'a> {
    state: &'a Mutex<State>,
    active: bool,
}
impl Drop for SendPreparation<'_> {
    fn drop(&mut self) {
        if self.active {
            self.state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .preparing = false;
        }
    }
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
        self.send_with(|| chunk.into_http_bytes().map_err(Into::into))
    }

    fn send_with(
        &self,
        prepare: impl FnOnce() -> Result<Bytes, StreamingHttpError>,
    ) -> Result<(), StreamingHttpError> {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if state.ended || state.dropped || state.preparing || state.pending.is_some() {
                drop(state);
                drop(prepare);
                return Err(StreamingHttpError::InvalidState);
            }
            state.preparing = true;
        }
        // Reservation, allocation and every input-owner drop may execute host
        // code. Prepare outside the queue lock, then revalidate the state. The
        // permit prevents a second send from passing while this one prepares.
        let mut preparation = SendPreparation {
            state: &self.state,
            active: true,
        };
        let bytes = prepare()?;
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.preparing = false;
        preparation.active = false;
        if state.ended || state.dropped || state.pending.is_some() {
            drop(state);
            drop(bytes);
            return Err(StreamingHttpError::InvalidState);
        }
        state.pending = Some(bytes);
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
            Self::Streaming(receiver) => poll_stream_with(receiver, || cx.waker().clone()),
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

fn poll_stream_with(
    receiver: &mut Receiver,
    make_waker: impl FnOnce() -> Waker,
) -> Poll<Option<Result<Frame<Bytes>, Infallible>>> {
    let mut state = receiver
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    if let Some(data) = state.pending.take() {
        drop(state);
        return ready_frame(receiver, data);
    }
    if state.ended {
        return Poll::Ready(None);
    }
    // Cloning a supplied Waker and dropping the replaced owner can execute
    // arbitrary code. Neither operation may occur while the queue is locked.
    drop(state);
    let waker = make_waker();
    let mut state = receiver
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    // A sender may have queued a frame or ended while the lock was released.
    // Observe that change rather than parking with a wakeup already consumed.
    if let Some(data) = state.pending.take() {
        drop(state);
        drop(waker);
        return ready_frame(receiver, data);
    }
    if state.ended {
        drop(state);
        drop(waker);
        return Poll::Ready(None);
    }
    let previous = state.waker.replace(waker);
    drop(state);
    drop(previous);
    Poll::Pending
}

fn ready_frame(
    receiver: &mut Receiver,
    data: Bytes,
) -> Poll<Option<Result<Frame<Bytes>, Infallible>>> {
    if let Some(remaining) = &mut receiver.remaining {
        *remaining -= data.len() as u64;
    }
    Poll::Ready(Some(Ok(Frame::data(data))))
}

#[cfg(test)]
mod send_admission_tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Barrier, TryLockError, Weak,
    };

    struct ObserveOwner {
        queue: Weak<Mutex<State>>,
        result: Arc<AtomicUsize>,
        value: u8,
    }
    impl AsRef<[u8]> for ObserveOwner {
        fn as_ref(&self) -> &[u8] {
            std::slice::from_ref(&self.value)
        }
    }
    impl Drop for ObserveOwner {
        fn drop(&mut self) {
            let queue = self.queue.upgrade().unwrap();
            let result = match queue.try_lock() {
                Ok(_) => 1,
                Err(TryLockError::WouldBlock) => 2,
                Err(TryLockError::Poisoned(_)) => 3,
            };
            self.result.store(result, Ordering::SeqCst);
        }
    }
    struct ObserveWake {
        queue: Weak<Mutex<State>>,
        result: Arc<AtomicUsize>,
    }
    impl std::task::Wake for ObserveWake {
        fn wake(self: Arc<Self>) {
            let queue = self.queue.upgrade().unwrap();
            let result = match queue.try_lock() {
                Ok(_) => 1,
                Err(TryLockError::WouldBlock) => 2,
                Err(TryLockError::Poisoned(_)) => 3,
            };
            self.result.store(result, Ordering::SeqCst);
        }
    }
    fn owner(sender: &Sender, result: &Arc<AtomicUsize>, value: u8) -> ObserveOwner {
        ObserveOwner {
            queue: Arc::downgrade(&sender.state),
            result: Arc::clone(result),
            value,
        }
    }

    #[test]
    fn preparation_flag_preserves_original_queue_allocation_layout() {
        assert_eq!(
            std::mem::size_of::<State>(),
            std::mem::size_of::<OriginalStateLayout>()
        );
        assert_eq!(
            std::mem::align_of::<State>(),
            std::mem::align_of::<OriginalStateLayout>()
        );
        assert_eq!(
            std::mem::size_of::<Mutex<State>>(),
            std::mem::size_of::<Mutex<OriginalStateLayout>>()
        );
        assert_eq!(
            std::mem::align_of::<Mutex<State>>(),
            std::mem::align_of::<Mutex<OriginalStateLayout>>()
        );
    }

    #[test]
    fn initially_invalid_send_drops_unprepared_owner_after_unlock() {
        let (sender, _body) = channel(None);
        sender.end();
        let result = Arc::new(AtomicUsize::new(0));
        let owner = owner(&sender, &result, 1);
        assert!(matches!(
            sender.send_with(move || Ok(Bytes::from_owner(owner))),
            Err(StreamingHttpError::InvalidState)
        ));
        assert_eq!(result.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn preparation_unwind_and_send_wakeup_run_after_unlock() {
        let (sender, body) = channel(None);
        let result = Arc::new(AtomicUsize::new(0));
        let owner = owner(&sender, &result, 1);
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = sender.send_with(move || -> Result<Bytes, StreamingHttpError> {
                let _original = owner;
                panic!("controlled preparation unwind");
            });
        }));
        assert!(panic.is_err());
        assert_eq!(result.load(Ordering::SeqCst), 1);
        assert!(sender.state.lock().unwrap().pending.is_none());
        let woke = Arc::new(AtomicUsize::new(0));
        sender.state.lock().unwrap().waker = Some(Waker::from(Arc::new(ObserveWake {
            queue: Arc::downgrade(&sender.state),
            result: Arc::clone(&woke),
        })));
        sender.send_with(|| Ok(Bytes::from_static(b"ok"))).unwrap();
        assert_eq!(woke.load(Ordering::SeqCst), 1);
        drop(body);
    }

    #[test]
    fn end_during_preparation_refuses_and_retires_owner_after_unlock() {
        let (sender, body) = channel(None);
        let sender = Arc::new(sender);
        let entered = Arc::new(Barrier::new(2));
        let resume = Arc::new(Barrier::new(2));
        let result = Arc::new(AtomicUsize::new(0));
        let original = owner(&sender, &result, 7);
        let worker = {
            let sender = Arc::clone(&sender);
            let entered = Arc::clone(&entered);
            let resume = Arc::clone(&resume);
            std::thread::spawn(move || {
                sender.send_with(move || {
                    entered.wait();
                    resume.wait();
                    Ok(Bytes::from_owner(original))
                })
            })
        };
        entered.wait();
        sender.end();
        resume.wait();
        assert!(matches!(
            worker.join().unwrap(),
            Err(StreamingHttpError::InvalidState)
        ));
        assert_eq!(result.load(Ordering::SeqCst), 1);
        let state = sender.state.lock().unwrap();
        assert!(state.ended && state.pending.is_none());
        drop(state);
        drop(body);
    }

    #[test]
    fn concurrent_sends_publish_at_most_one_frame_and_retire_loser_unlocked() {
        let (sender, body) = channel(None);
        let sender = Arc::new(sender);
        let entered = Arc::new(Barrier::new(2));
        let resume = Arc::new(Barrier::new(2));
        let drops = [Arc::new(AtomicUsize::new(0)), Arc::new(AtomicUsize::new(0))];
        let original = owner(&sender, &drops[0], 0);
        let worker = {
            let sender = Arc::clone(&sender);
            let entered = Arc::clone(&entered);
            let resume = Arc::clone(&resume);
            std::thread::spawn(move || {
                sender.send_with(move || {
                    entered.wait();
                    resume.wait();
                    Ok(Bytes::from_owner(original))
                })
            })
        };
        entered.wait();
        let competing = owner(&sender, &drops[1], 1);
        assert!(matches!(
            sender.send_with(move || Ok(Bytes::from_owner(competing))),
            Err(StreamingHttpError::InvalidState)
        ));
        assert_eq!(drops[1].load(Ordering::SeqCst), 1);
        assert!(sender.state.lock().unwrap().pending.is_none());
        resume.wait();
        assert!(worker.join().unwrap().is_ok());
        let pending = sender.state.lock().unwrap().pending.take().unwrap();
        assert_eq!(pending.len(), 1);
        drop(pending);
        assert!(drops.iter().all(|seen| seen.load(Ordering::SeqCst) == 1));

        // A fully published and consumed first frame does not prevent the
        // next serial write, matching the original queue behavior.
        sender
            .send_with(|| Ok(Bytes::from_static(b"next")))
            .unwrap();
        let next = sender.state.lock().unwrap().pending.take().unwrap();
        assert_eq!(&next[..], b"next");
        drop(next);
        drop(body);
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

    struct PollWakerDrop {
        queue: Weak<Mutex<State>>,
        result: Arc<AtomicUsize>,
    }
    impl Wake for PollWakerDrop {
        fn wake(self: Arc<Self>) {}
    }
    impl Drop for PollWakerDrop {
        fn drop(&mut self) {
            let Some(queue) = self.queue.upgrade() else {
                self.result.store(3, Ordering::SeqCst);
                return;
            };
            let observed = match queue.try_lock() {
                Ok(_) => 1,
                Err(TryLockError::WouldBlock) => 2,
                Err(TryLockError::Poisoned(_)) => 3,
            };
            self.result.store(observed, Ordering::SeqCst);
        }
    }

    #[test]
    fn replacing_poll_waker_drops_previous_owner_after_queue_unlock() {
        let (sender, mut body) = channel(None);
        let queue = match &body {
            RequestBody::Streaming(receiver) => Arc::downgrade(&receiver.state),
            _ => unreachable!("channel returns a streaming body"),
        };
        let result = Arc::new(AtomicUsize::new(0));
        let previous = Waker::from(Arc::new(PollWakerDrop {
            queue,
            result: Arc::clone(&result),
        }));
        assert!(Pin::new(&mut body)
            .poll_frame(&mut Context::from_waker(&previous))
            .is_pending());
        drop(previous);
        assert_eq!(result.load(Ordering::SeqCst), 0);
        assert!(Pin::new(&mut body)
            .poll_frame(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(result.load(Ordering::SeqCst), 1);
        drop(body);
        drop(sender);
    }

    #[test]
    fn frame_queued_while_cloning_waker_is_not_lost() {
        let (sender, mut body) = channel(None);
        let receiver = match &mut body {
            RequestBody::Streaming(receiver) => receiver,
            _ => unreachable!("channel returns a streaming body"),
        };
        let queue = Arc::clone(&receiver.state);
        let result = poll_stream_with(receiver, || {
            let mut state = match queue.try_lock() {
                Ok(state) => state,
                Err(_) => panic!("waker was cloned while the queue lock was held"),
            };
            state.pending = Some(Bytes::from_static(b"next"));
            Waker::noop().clone()
        });
        let Poll::Ready(Some(Ok(frame))) = result else {
            panic!("a frame queued during registration must be returned");
        };
        assert_eq!(frame.into_data().unwrap(), Bytes::from_static(b"next"));
        drop(body);
        drop(sender);
    }
}
