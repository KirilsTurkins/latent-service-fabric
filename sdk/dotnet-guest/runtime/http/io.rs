//! WASI resource identities shared by the BCL and this HTTP backend.
use super::{
    exports::wasi::io,
    poll::Pollable,
    pump::{self, Readiness},
    state::{Exchange, Slot, CHUNK},
    ClosedError,
};
use std::{cell::Cell, rc::Rc};

pub struct Input {
    exchange: Option<Rc<Exchange>>,
    _slot: Slot,
}
pub struct Output {
    exchange: Option<Rc<Exchange>>,
    permit: Cell<usize>,
    _slot: Slot,
}
enum Interest {
    Response,
    Read,
    Write,
}
struct HttpReady {
    exchange: Rc<Exchange>,
    interest: Interest,
}
impl Readiness for HttpReady {
    fn ready(&self) -> bool {
        match self.interest {
            Interest::Response => {
                self.exchange.headers_ready.get()
                    || self.exchange.failure.get().is_some()
                    || self.exchange.cancelled.get()
            }
            Interest::Read => self.exchange.readable(),
            Interest::Write => self.exchange.writable(),
        }
    }
}

impl Pollable {
    pub fn response(exchange: Rc<Exchange>) -> io::poll::Pollable {
        Self::new(Rc::new(HttpReady {
            exchange,
            interest: Interest::Response,
        }))
    }
}

impl Input {
    pub fn closed() -> Self {
        Self {
            exchange: None,
            _slot: Slot::new(),
        }
    }
    pub fn http(exchange: Rc<Exchange>) -> Self {
        let slot = Slot::new();
        exchange.input_views.set(exchange.input_views.get() + 1);
        Self {
            exchange: Some(exchange),
            _slot: slot,
        }
    }
}
fn failed() -> io::streams::StreamError {
    // The exact host category stays on its exchange. Do not convert a pending,
    // truncated, cancelled or uncertain operation into a successful EOF.
    io::streams::StreamError::LastOperationFailed(io::error::Error::new(ClosedError {
        _slot: Slot::new(),
    }))
}
impl io::streams::GuestInputStream for Input {
    fn read(&self, length: u64) -> Result<Vec<u8>, io::streams::StreamError> {
        if length == 0 {
            return Ok(Vec::new());
        }
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        exchange.request_read();
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed());
        }
        let mut input = exchange.input.borrow_mut();
        if let Some(buffer) = input.as_mut() {
            let count =
                (length.min(CHUNK as u64) as usize).min(buffer.bytes.len() - buffer.position);
            let result = buffer.bytes[buffer.position..buffer.position + count].to_vec();
            buffer.position += count;
            if buffer.position == buffer.bytes.len() {
                input.take();
            }
            return Ok(result);
        }
        if exchange.eof.get() {
            return Err(io::streams::StreamError::Closed);
        }
        // Empty means a genuinely pending read. Only verified host EOF above
        // becomes Closed, which the ordinary BCL maps to its stream EOF.
        Ok(Vec::new())
    }
    fn blocking_read(&self, length: u64) -> Result<Vec<u8>, io::streams::StreamError> {
        let bytes = self.read(length)?;
        if length == 0 || !bytes.is_empty() {
            return Ok(bytes);
        }
        let exchange = self.exchange.as_ref().expect("HTTP stream owner");
        let source: Rc<dyn Readiness> = Rc::new(HttpReady {
            exchange: exchange.clone(),
            interest: Interest::Read,
        });
        pump::Pump::current().poll(&[source]);
        self.read(length)
    }
    fn subscribe(&self) -> io::poll::Pollable {
        if let Some(exchange) = &self.exchange {
            exchange.request_read();
            Pollable::new(Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Read,
            }))
        } else {
            Pollable::closed()
        }
    }
}
impl Drop for Input {
    fn drop(&mut self) {
        if let Some(exchange) = &self.exchange {
            exchange.input_views.set(
                exchange
                    .input_views
                    .get()
                    .checked_sub(1)
                    .expect("HTTP input view owner"),
            );
        }
    }
}

impl Output {
    pub fn closed() -> Self {
        Self {
            exchange: None,
            permit: Cell::new(0),
            _slot: Slot::new(),
        }
    }
    pub fn http(exchange: Rc<Exchange>) -> Self {
        let slot = Slot::new();
        exchange.output_views.set(exchange.output_views.get() + 1);
        Self {
            exchange: Some(exchange),
            permit: Cell::new(0),
            _slot: slot,
        }
    }
}
impl io::streams::GuestOutputStream for Output {
    fn check_write(&self) -> Result<u64, io::streams::StreamError> {
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed());
        }
        if exchange.output_finished.get() {
            return Err(io::streams::StreamError::Closed);
        }
        let permit = if exchange.writable() { CHUNK } else { 0 };
        self.permit.set(permit);
        Ok(permit as u64)
    }
    fn write(&self, contents: Vec<u8>) -> Result<(), io::streams::StreamError> {
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        if contents.len() > self.permit.replace(0) {
            exchange.local_fail(super::latent::http::streaming::HttpError::InvalidState);
            return Err(failed());
        }
        exchange.queue(contents).map_err(|_| failed())
    }
    fn flush(&self) -> Result<(), io::streams::StreamError> {
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed());
        }
        // This initiates progress. The normal BCL observes completion through
        // check-write/subscribe; pending writes remain their original owners.
        Ok(())
    }
    fn blocking_flush(&self) -> Result<(), io::streams::StreamError> {
        self.flush()?;
        let exchange = self.exchange.as_ref().expect("HTTP output owner");
        if !exchange.writable() {
            let source: Rc<dyn Readiness> = Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Write,
            });
            pump::Pump::current().poll(&[source]);
        }
        self.flush()
    }
    fn subscribe(&self) -> io::poll::Pollable {
        if let Some(exchange) = &self.exchange {
            Pollable::new(Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Write,
            }))
        } else {
            Pollable::closed()
        }
    }
}
impl Drop for Output {
    fn drop(&mut self) {
        if let Some(exchange) = &self.exchange {
            exchange.output_views.set(
                exchange
                    .output_views
                    .get()
                    .checked_sub(1)
                    .expect("HTTP output view owner"),
            );
        }
    }
}
