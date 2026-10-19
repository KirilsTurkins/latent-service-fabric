//! Bounded textual stdio below the unchanged BCL Console implementation.
//! The containing stream retains its original quota Slot until actual drop.
use super::{exports::wasi::io, latent::log::log};
use std::cell::{Cell, RefCell};

const MAX_MESSAGE: usize = 256;
pub struct Stream {
    stderr: bool,
    permit: Cell<usize>,
    pending: RefCell<Vec<u8>>,
    failed: Cell<bool>,
    busy: Cell<bool>,
}
pub fn stdout() -> Option<Stream> {
    Some(Stream::new(false))
}
pub fn stderr() -> Option<Stream> {
    Some(Stream::new(true))
}
impl Stream {
    fn new(stderr: bool) -> Self {
        Self {
            stderr,
            permit: Cell::new(0),
            pending: RefCell::new(Vec::new()),
            failed: Cell::new(false),
            busy: Cell::new(false),
        }
    }
    fn error(&self) -> io::streams::StreamError {
        self.failed.set(true);
        self.pending.borrow_mut().clear();
        io::streams::StreamError::LastOperationFailed(io::error::Error::new(super::ClosedError {
            _slot: super::quota::Slot::new(),
        }))
    }
    pub fn check_write(&self) -> Result<u64, io::streams::StreamError> {
        if self.failed.get() || self.busy.get() {
            return Err(self.error());
        }
        let count = MAX_MESSAGE - self.pending.borrow().len();
        self.permit.set(count);
        Ok(count as u64)
    }
    pub fn write(&self, contents: Vec<u8>) -> Result<(), io::streams::StreamError> {
        if self.failed.get() || self.busy.get() || contents.len() > self.permit.replace(0) {
            return Err(self.error());
        }
        let mut bytes = self.pending.take();
        bytes.extend(contents);
        if bytes.len() > MAX_MESSAGE {
            return Err(self.error());
        }
        let complete = match std::str::from_utf8(&bytes) {
            Ok(_) => bytes.len(),
            Err(error) if error.error_len().is_none() && bytes.len() - error.valid_up_to() <= 3 => {
                error.valid_up_to()
            }
            Err(_) => return Err(self.error()),
        };
        if complete != 0 {
            self.busy.set(true);
            let level = if self.stderr {
                log::Level::Error
            } else {
                log::Level::Info
            };
            // No RefCell borrow survives a canonical host call. Failure does not
            // retain a retry queue or acknowledge a host policy drop as delivery.
            let accepted = log::write(
                level,
                std::str::from_utf8(&bytes[..complete]).expect("validated log UTF-8"),
                &[],
            );
            self.busy.set(false);
            if !matches!(accepted, Ok(true)) || self.failed.get() {
                return Err(self.error());
            }
        }
        self.pending.replace(bytes[complete..].to_vec());
        Ok(())
    }
    pub fn flush(&self) -> Result<(), io::streams::StreamError> {
        let incomplete = !self.pending.borrow().is_empty();
        if self.failed.get() || self.busy.get() || incomplete {
            return Err(self.error());
        }
        // Every complete prefix was synchronously accepted by the current host
        // sink. There is no pending worker, durable export or remote flush claim.
        Ok(())
    }
}
