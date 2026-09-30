use std::io;
use std::sync::{Arc, Mutex};

use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::sync::Notify;
use tokio::task::JoinHandle;

#[derive(Clone)]
pub(super) struct Capture {
    state: Arc<Mutex<State>>,
    changed: Arc<Notify>,
    maximum: usize,
}

#[derive(Default)]
struct State {
    bytes: Vec<u8>,
    failure: Option<Failure>,
    closed: bool,
}

#[derive(Clone, Copy)]
enum Failure {
    Overflow,
    Read,
}

impl Capture {
    pub(super) fn new(maximum: usize, changed: Arc<Notify>) -> Self {
        Self {
            state: Arc::default(),
            maximum,
            changed,
        }
    }

    pub(super) fn spawn(&self, reader: impl AsyncRead + Unpin + Send + 'static) -> JoinHandle<()> {
        let capture = self.clone();
        tokio::spawn(async move { capture.read(reader).await })
    }

    async fn read(self, mut reader: impl AsyncRead + Unpin) {
        let mut buffer = [0_u8; 4096];
        loop {
            let read = reader.read(&mut buffer).await;
            let stop = {
                let Ok(mut state) = self.state.lock() else {
                    self.changed.notify_waiters();
                    return;
                };
                match read {
                    Ok(0) => {
                        state.closed = true;
                        true
                    }
                    Ok(count) if count <= self.maximum.saturating_sub(state.bytes.len()) => {
                        state.bytes.extend_from_slice(&buffer[..count]);
                        false
                    }
                    Ok(_) => {
                        state.failure = Some(Failure::Overflow);
                        true
                    }
                    Err(_) => {
                        state.failure = Some(Failure::Read);
                        true
                    }
                }
            };
            self.changed.notify_waiters();
            if stop {
                return;
            }
        }
    }

    pub(super) fn check(&self) -> io::Result<()> {
        let state = self.state.lock().map_err(|_| poisoned())?;
        check(&state)
    }

    pub(super) fn snapshot(&self) -> io::Result<Vec<u8>> {
        let state = self.state.lock().map_err(|_| poisoned())?;
        check(&state)?;
        Ok(state.bytes.clone())
    }

    pub(super) fn line(&self) -> io::Result<Option<Vec<u8>>> {
        let state = self.state.lock().map_err(|_| poisoned())?;
        check(&state)?;
        if let Some(end) = state.bytes.iter().position(|byte| *byte == b'\n') {
            return Ok(Some(state.bytes[..=end].to_vec()));
        }
        if state.closed {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "child stdout closed before a complete record",
            ));
        }
        Ok(None)
    }
}

fn check(state: &State) -> io::Result<()> {
    match state.failure {
        Some(Failure::Overflow) => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "child output limit exceeded",
        )),
        Some(Failure::Read) => Err(io::Error::other("child output read failed")),
        None => Ok(()),
    }
}

fn poisoned() -> io::Error {
    io::Error::other("child capture state unavailable")
}
