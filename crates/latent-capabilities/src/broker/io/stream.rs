use super::{
    capacity, denied, error, invalid, Charge, IoBuffer, Kind, Operation, PlatformError,
    PlatformErrorCode,
};
use std::sync::{Arc, Mutex};
use tokio::sync::Notify;

/// A terminal applies after already queued chunks have been consumed. Caller
/// cancellation/expiry takes precedence and stops new delivery immediately.
/// None of these outcomes rolls back an external effect or authorizes a retry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IoStreamTerminal {
    Eof,
    Closed,
    Cancelled,
    DeadlineExceeded,
    TooLarge,
    Failed,
    Uncertain,
}
impl IoStreamTerminal {
    fn failure(self) -> PlatformError {
        let code = match self {
            Self::Cancelled => PlatformErrorCode::Cancelled,
            Self::DeadlineExceeded => PlatformErrorCode::DeadlineExceeded,
            Self::TooLarge => PlatformErrorCode::ResourceExhausted,
            _ => PlatformErrorCode::Unavailable,
        };
        error(
            code,
            match self {
                Self::Uncertain => "io-stream-uncertain",
                _ => "io-stream-terminal",
            },
        )
    }
}
pub(super) struct StreamLifetime {
    operation: Arc<Operation>,
    _metadata: Charge,
    _slot: Charge,
}
struct StreamState {
    chunks: Box<[Option<IoBuffer>]>,
    head: usize,
    length: usize,
    accepted_bytes: u64,
    terminal: Option<IoStreamTerminal>,
    reader_closed: bool,
}
struct Stream {
    state: Mutex<StreamState>,
    readable: Notify,
    writable: Notify,
    lifetime: Arc<StreamLifetime>,
}
pub struct IoStreamWriter {
    stream: Arc<Stream>,
}
pub struct IoStreamReader {
    stream: Arc<Stream>,
}

pub(super) fn create(
    op: &Arc<Operation>,
    depth: usize,
) -> Result<(IoStreamWriter, IoStreamReader), PlatformError> {
    op.check()?;
    if depth == 0 || depth > op.runtime.limits.maximum_stream_chunks {
        return Err(invalid());
    }
    let slot = op.runtime.counters.acquire(Kind::Stream, 1)?;
    let metadata = depth
        .checked_mul(std::mem::size_of::<Option<IoBuffer>>())
        .and_then(|n| n.checked_add(2048))
        .ok_or_else(capacity)?;
    let metadata = op.runtime.counters.acquire(Kind::Metadata, metadata)?;
    // Fixed ring, with no hidden channel blocks or allocation on enqueue.
    let chunks: Vec<_> = std::iter::repeat_with(|| None).take(depth).collect();
    if chunks.capacity() != depth {
        return Err(capacity());
    }
    let stream = Arc::new(Stream {
        state: Mutex::new(StreamState {
            chunks: chunks.into_boxed_slice(),
            head: 0,
            length: 0,
            accepted_bytes: 0,
            terminal: None,
            reader_closed: false,
        }),
        readable: Notify::new(),
        writable: Notify::new(),
        lifetime: Arc::new(StreamLifetime {
            operation: Arc::clone(op),
            _metadata: metadata,
            _slot: slot,
        }),
    });
    Ok((
        IoStreamWriter {
            stream: Arc::clone(&stream),
        },
        IoStreamReader { stream },
    ))
}
impl Stream {
    fn finish(&self, terminal: IoStreamTerminal) {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if state.terminal.is_none() {
                state.terminal = Some(terminal);
            }
        }
        self.readable.notify_waiters();
        self.writable.notify_waiters();
    }
    fn close_reader(&self) {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.reader_closed = true;
            if state.terminal.is_none() {
                state.terminal = Some(IoStreamTerminal::Closed);
            }
        }
        // Destroy/zero bounded chunks outside the queue lock. No I/O or caller
        // callback runs in Drop, and a delivered consumer keeps its own lease.
        loop {
            let chunk = {
                let mut state = self
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if state.length == 0 {
                    break;
                }
                let head = state.head;
                let chunk = state.chunks[head].take();
                state.head = (head + 1) % state.chunks.len();
                state.length -= 1;
                chunk
            };
            drop(chunk);
        }
        self.writable.notify_waiters();
        self.readable.notify_waiters();
    }
}
impl IoStreamWriter {
    /// Waits for ring capacity without reading further transport bytes. This
    /// single affine writer preserves order; saturation cannot create workers.
    pub async fn write(&mut self, buffer: IoBuffer) -> Result<(), PlatformError> {
        let op = &self.stream.lifetime.operation;
        if !Arc::ptr_eq(op, &buffer.operation) || buffer.stream.is_some() {
            return Err(denied());
        }
        if buffer.bytes().is_empty() {
            return Err(invalid());
        }
        let mut buffer = buffer.retain()?;
        buffer.stream = Some(Arc::clone(&self.stream.lifetime));
        loop {
            let writable = self.stream.writable.notified();
            tokio::pin!(writable);
            writable.as_mut().enable();
            op.check()?;
            {
                let mut state = self
                    .stream
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if state.reader_closed {
                    return Err(IoStreamTerminal::Closed.failure());
                }
                if let Some(terminal) = state.terminal {
                    return Err(terminal.failure());
                }
                if state.length < state.chunks.len() {
                    let next = state
                        .accepted_bytes
                        .checked_add(buffer.bytes().len() as u64)
                        .filter(|n| *n <= op.runtime.limits.maximum_stream_bytes);
                    let Some(next) = next else {
                        state.terminal = Some(IoStreamTerminal::TooLarge);
                        drop(state);
                        self.stream.readable.notify_waiters();
                        return Err(IoStreamTerminal::TooLarge.failure());
                    };
                    let index = (state.head + state.length) % state.chunks.len();
                    state.chunks[index] = Some(buffer);
                    state.length += 1;
                    state.accepted_bytes = next;
                    drop(state);
                    self.stream.readable.notify_one();
                    return Ok(());
                }
            }
            tokio::select! {
                biased;
                failure = op.stopped() => return Err(failure),
                () = &mut writable => {},
            }
        }
    }
    pub fn finish(self, terminal: IoStreamTerminal) {
        self.stream.finish(terminal);
    }
}
impl Drop for IoStreamWriter {
    fn drop(&mut self) {
        self.stream.finish(IoStreamTerminal::Uncertain);
    }
}
impl IoStreamReader {
    /// A returned chunk owns its complete capacity through partial consumption.
    /// Dropping/closing this reader cannot refund a chunk already delivered.
    pub async fn read(&mut self) -> Result<Option<IoBuffer>, PlatformError> {
        let op = &self.stream.lifetime.operation;
        loop {
            let readable = self.stream.readable.notified();
            tokio::pin!(readable);
            readable.as_mut().enable();
            if let Err(failure) = op.check() {
                self.stream.close_reader();
                return Err(failure);
            }
            {
                let mut state = self
                    .stream
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if state.reader_closed {
                    return Err(IoStreamTerminal::Closed.failure());
                }
                if state.length != 0 {
                    let head = state.head;
                    let chunk = state.chunks[head].take().expect("occupied ring slot");
                    state.head = (head + 1) % state.chunks.len();
                    state.length -= 1;
                    drop(state);
                    self.stream.writable.notify_one();
                    return Ok(Some(chunk));
                }
                if let Some(terminal) = state.terminal {
                    return match terminal {
                        IoStreamTerminal::Eof => Ok(None),
                        _ => Err(terminal.failure()),
                    };
                }
            }
            tokio::select! {
                biased;
                failure = op.stopped() => { self.stream.close_reader(); return Err(failure); },
                () = &mut readable => {},
            }
        }
    }
    #[must_use]
    pub fn terminal(&self) -> Option<IoStreamTerminal> {
        self.stream
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .terminal
    }
    pub fn close(self) {
        self.stream.close_reader();
    }
}
impl Drop for IoStreamReader {
    fn drop(&mut self) {
        self.stream.close_reader();
    }
}
