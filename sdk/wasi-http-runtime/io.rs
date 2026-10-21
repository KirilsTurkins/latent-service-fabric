//! Full standard stream methods over the original bounded typed HTTP exchange.
use super::{
    exports::wasi::io,
    poll::Pollable,
    pump::{self, Readiness},
    state::{Exchange, Slot, CHUNK},
    HttpError,
};
use io::streams::GuestInputStream;
use std::{cell::Cell, rc::Rc};

pub struct Input {
    exchange: Option<Rc<Exchange>>,
    children: Rc<Cell<usize>>,
    _slot: Slot,
}
pub struct Output {
    exchange: Option<Rc<Exchange>>,
    children: Rc<Cell<usize>>,
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
    parent: Option<Rc<Cell<usize>>>,
}
impl Drop for HttpReady {
    fn drop(&mut self) {
        if let Some(parent) = &self.parent {
            parent.set(parent.get().checked_sub(1).expect("stream pollable child"));
        }
    }
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
            parent: None,
        }))
    }
}

impl Input {
    pub fn closed() -> Self {
        Self {
            exchange: None,
            children: Rc::new(Cell::new(0)),
            _slot: Slot::new(),
        }
    }
    pub fn http(exchange: Rc<Exchange>) -> Self {
        let slot = Slot::new();
        exchange.input_views.set(exchange.input_views.get() + 1);
        Self {
            exchange: Some(exchange),
            children: Rc::new(Cell::new(0)),
            _slot: slot,
        }
    }
}
fn failed(exchange: &Exchange) -> io::streams::StreamError {
    let cause = exchange
        .failure
        .get()
        .unwrap_or(if exchange.cancelled.get() {
            super::latent::http::streaming::HttpError::Cancelled
        } else {
            super::latent::http::streaming::HttpError::InvalidState
        });
    io::streams::StreamError::LastOperationFailed(io::error::Error::new(HttpError {
        cause,
        _slot: Slot::new(),
    }))
}
impl io::streams::GuestInputStream for Input {
    fn skip(&self, length: u64) -> Result<u64, io::streams::StreamError> {
        self.read(length).map(|bytes| bytes.len() as u64)
    }
    async fn blocking_skip(&self, length: u64) -> Result<u64, io::streams::StreamError> {
        self.blocking_read(length)
            .await
            .map(|bytes| bytes.len() as u64)
    }
    fn read(&self, length: u64) -> Result<Vec<u8>, io::streams::StreamError> {
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed(exchange));
        }
        if length == 0 {
            return if exchange.eof.get() && exchange.input.borrow().is_none() {
                Err(io::streams::StreamError::Closed)
            } else {
                Ok(Vec::new())
            };
        }
        exchange.request_read();
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed(exchange));
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
    async fn blocking_read(&self, length: u64) -> Result<Vec<u8>, io::streams::StreamError> {
        let bytes = self.read(length)?;
        if length == 0 || !bytes.is_empty() {
            return Ok(bytes);
        }
        let exchange = self.exchange.as_ref().expect("HTTP stream owner");
        let source: Rc<dyn Readiness> = Rc::new(HttpReady {
            exchange: exchange.clone(),
            interest: Interest::Read,
            parent: None,
        });
        pump::Pump::current().poll(&[source]);
        self.read(length)
    }
    fn subscribe(&self) -> io::poll::Pollable {
        if let Some(exchange) = &self.exchange {
            exchange.request_read();
            self.children.set(
                self.children
                    .get()
                    .checked_add(1)
                    .expect("input pollable count"),
            );
            Pollable::new(Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Read,
                parent: Some(self.children.clone()),
            }))
        } else {
            Pollable::closed()
        }
    }
}
impl Drop for Input {
    fn drop(&mut self) {
        assert_eq!(
            self.children.get(),
            0,
            "input stream still has pollable children"
        );
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
    pub fn http(exchange: Rc<Exchange>) -> Self {
        let slot = Slot::new();
        exchange.output_views.set(exchange.output_views.get() + 1);
        Self {
            exchange: Some(exchange),
            children: Rc::new(Cell::new(0)),
            permit: Cell::new(0),
            _slot: slot,
        }
    }
}
impl io::streams::GuestOutputStream for Output {
    async fn blocking_write_and_flush(
        &self,
        contents: Vec<u8>,
    ) -> Result<(), io::streams::StreamError> {
        assert!(
            contents.len() <= 4096,
            "blocking-write-and-flush exceeds standard 4096-byte bound"
        );
        let mut position = 0;
        while position < contents.len() {
            let mut permit = self.check_write()?;
            while permit == 0 {
                let exchange = self.exchange.as_ref().expect("HTTP output owner");
                let source: Rc<dyn Readiness> = Rc::new(HttpReady {
                    exchange: exchange.clone(),
                    interest: Interest::Write,
                    parent: None,
                });
                pump::Pump::current().poll(&[source]);
                permit = self.check_write()?;
            }
            let count = permit.min((contents.len() - position) as u64) as usize;
            self.write(contents[position..position + count].to_vec())?;
            position += count;
        }
        self.blocking_flush().await
    }
    fn write_zeroes(&self, length: u64) -> Result<(), io::streams::StreamError> {
        let exchange = self.exchange.as_ref().expect("HTTP output owner");
        if length > self.permit.get() as u64 {
            exchange.local_fail(super::latent::http::streaming::HttpError::InvalidState);
            return Err(failed(exchange));
        }
        self.write(vec![0; length as usize])
    }
    async fn blocking_write_zeroes_and_flush(
        &self,
        length: u64,
    ) -> Result<(), io::streams::StreamError> {
        assert!(
            length <= 4096,
            "blocking-write-zeroes-and-flush exceeds standard 4096-byte bound"
        );
        let mut remaining = length;
        while remaining != 0 {
            let count = remaining.min(CHUNK as u64);
            self.blocking_write_and_flush(vec![0; count as usize])
                .await?;
            remaining -= count;
        }
        self.blocking_flush().await
    }
    fn splice(
        &self,
        source: io::streams::InputStreamBorrow<'_>,
        length: u64,
    ) -> Result<u64, io::streams::StreamError> {
        let permit = self.check_write()?.min(length);
        if permit == 0 {
            return Ok(0);
        }
        let bytes = source.get::<Input>().read(permit)?;
        let count = bytes.len() as u64;
        self.write(bytes)?;
        Ok(count)
    }
    async fn blocking_splice(
        &self,
        source: io::streams::InputStreamBorrow<'_>,
        length: u64,
    ) -> Result<u64, io::streams::StreamError> {
        if length == 0 {
            return Ok(0);
        }
        let mut permit = self.check_write()?.min(length);
        while permit == 0 {
            let exchange = self.exchange.as_ref().expect("HTTP output owner");
            let ready: Rc<dyn Readiness> = Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Write,
                parent: None,
            });
            pump::Pump::current().poll(&[ready]);
            permit = self.check_write()?.min(length);
        }
        let bytes = source.get::<Input>().blocking_read(permit).await?;
        let count = bytes.len() as u64;
        self.write(bytes)?;
        Ok(count)
    }
    fn check_write(&self) -> Result<u64, io::streams::StreamError> {
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed(exchange));
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
        if exchange.output_finished.get() {
            return Err(io::streams::StreamError::Closed);
        }
        if contents.len() > self.permit.replace(0) {
            exchange.local_fail(super::latent::http::streaming::HttpError::InvalidState);
            return Err(failed(exchange));
        }
        exchange.queue(contents).map_err(|_| failed(exchange))
    }
    fn flush(&self) -> Result<(), io::streams::StreamError> {
        self.permit.set(0);
        let Some(exchange) = &self.exchange else {
            return Err(io::streams::StreamError::Closed);
        };
        exchange.step();
        if exchange.failure.get().is_some() || exchange.cancelled.get() {
            return Err(failed(exchange));
        }
        // This initiates progress. The normal BCL observes completion through
        // check-write/subscribe; pending writes remain their original owners.
        Ok(())
    }
    async fn blocking_flush(&self) -> Result<(), io::streams::StreamError> {
        self.flush()?;
        let exchange = self.exchange.as_ref().expect("HTTP output owner");
        while !exchange.writable() {
            let source: Rc<dyn Readiness> = Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Write,
                parent: None,
            });
            pump::Pump::current().poll(&[source]);
        }
        self.flush()
    }
    fn subscribe(&self) -> io::poll::Pollable {
        if let Some(exchange) = &self.exchange {
            self.children.set(
                self.children
                    .get()
                    .checked_add(1)
                    .expect("output pollable count"),
            );
            Pollable::new(Rc::new(HttpReady {
                exchange: exchange.clone(),
                interest: Interest::Write,
                parent: Some(self.children.clone()),
            }))
        } else {
            Pollable::closed()
        }
    }
}
impl Drop for Output {
    fn drop(&mut self) {
        assert_eq!(
            self.children.get(),
            0,
            "output stream still has pollable children"
        );
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
