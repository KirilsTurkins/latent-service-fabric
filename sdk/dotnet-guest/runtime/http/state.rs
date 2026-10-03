//! Physical guest owners of one original typed HTTP exchange and its readiness.
pub use super::quota::Slot;
use super::{latent, owner::Owner, pump};
use latent::{http::streaming as raw, runtime::activation as runtime};
use std::{
    cell::{Cell, RefCell},
    future::Future,
    pin::Pin,
    rc::Rc,
    task::{Context, Poll},
};

pub const CHUNK: usize = 16 * 1024;
pub const MAX_BODY: u64 = 1024 * 1024;
pub const MAX_HEADERS: usize = 32;
pub const MAX_HEADER_BYTES: usize = 8 * 1024;
type Work = Pin<Box<dyn Future<Output = Completion>>>;
enum Completion {
    Opened(Result<raw::Upload, raw::HttpError>),
    Written(Result<raw::Upload, raw::HttpError>, u64),
    Response(Result<raw::Response, raw::HttpError>),
    Read(Result<(raw::Body, Option<Vec<u8>>), raw::HttpError>),
}

pub struct Buffer {
    pub bytes: Vec<u8>,
    pub position: usize,
}

pub struct Exchange {
    request: RefCell<Option<raw::Request>>,
    work: RefCell<Option<Work>>,
    upload: RefCell<Option<raw::Upload>>,
    body: RefCell<Option<raw::Body>>,
    queued: RefCell<Option<Vec<u8>>>,
    pub input: RefCell<Option<Buffer>>,
    pub response: RefCell<Option<(u16, Vec<raw::Header>)>>,
    pub failure: Cell<Option<raw::HttpError>>,
    pub body_requested: Cell<bool>,
    pub stream_requested: Cell<bool>,
    pub input_views: Cell<usize>,
    pub output_views: Cell<usize>,
    pub output_finished: Cell<bool>,
    pub headers_ready: Cell<bool>,
    pub eof: Cell<bool>,
    pub cancelled: Cell<bool>,
    read_requested: Cell<bool>,
    expected: Cell<Option<u64>>,
    written: Cell<u64>,
    dispatch_possible: Cell<bool>,
    admitted: Cell<bool>,
    // Owner and slot follow physical futures/resources/buffers in field Drop
    // order. The host also keeps each physical socket's original reservation.
    owner: RefCell<Option<Owner>>,
    _slot: Slot,
}

impl Exchange {
    pub fn new() -> Rc<Self> {
        let slot = Slot::new();
        Rc::new(Self {
            request: RefCell::new(None),
            work: RefCell::new(None),
            upload: RefCell::new(None),
            body: RefCell::new(None),
            queued: RefCell::new(None),
            input: RefCell::new(None),
            response: RefCell::new(None),
            failure: Cell::new(None),
            body_requested: Cell::new(false),
            stream_requested: Cell::new(false),
            input_views: Cell::new(0),
            output_views: Cell::new(0),
            output_finished: Cell::new(false),
            headers_ready: Cell::new(false),
            eof: Cell::new(false),
            cancelled: Cell::new(false),
            read_requested: Cell::new(false),
            expected: Cell::new(None),
            written: Cell::new(0),
            dispatch_possible: Cell::new(false),
            admitted: Cell::new(false),
            owner: RefCell::new(None),
            _slot: slot,
        })
    }

    pub fn admit(self: &Rc<Self>, request: raw::Request) -> Result<(), runtime::Error> {
        let owner = Owner::new(runtime::OwnerKind::Task)?;
        self.expected.set(request.body_length);
        // Ordinary HttpContent can finish synchronously before Handle. Keep
        // that completion; resetting it would strand an already disposed body.
        if !self.body_requested.get() {
            self.output_finished.set(true);
        }
        *self.owner.borrow_mut() = Some(owner);
        *self.request.borrow_mut() = Some(request);
        self.admitted.set(true);
        let operation: Rc<dyn pump::Progress> = self.clone();
        pump::Pump::track(&operation);
        Ok(())
    }

    pub fn queue(&self, bytes: Vec<u8>) -> Result<(), raw::HttpError> {
        if self.cancelled.get() || self.output_finished.get() || self.queued.borrow().is_some() {
            self.local_fail(raw::HttpError::InvalidState);
            return Err(self.failure.get().expect("sticky upload failure"));
        }
        let length = bytes.len() as u64;
        if length > CHUNK as u64
            || self.written.get().saturating_add(length) > MAX_BODY
            || self
                .expected
                .get()
                .is_some_and(|maximum| self.written.get().saturating_add(length) > maximum)
        {
            self.local_fail(raw::HttpError::RequestTooLarge);
            return Err(self.failure.get().expect("sticky upload failure"));
        }
        if !bytes.is_empty() {
            *self.queued.borrow_mut() = Some(bytes);
        }
        Ok(())
    }

    pub fn writable(&self) -> bool {
        self.failure.get().is_some()
            || self.cancelled.get()
            || self.output_finished.get()
            || (self.queued.borrow().is_none() && self.work.borrow().is_none())
            || !self.admitted.get() && self.queued.borrow().is_none()
    }

    pub fn request_read(&self) {
        self.read_requested.set(true);
    }

    pub fn step(&self) {
        if self.admitted.get() {
            pump::Pump::current().step();
        }
    }

    pub fn readable(&self) -> bool {
        self.input.borrow().is_some()
            || self.eof.get()
            || self.failure.get().is_some()
            || self.cancelled.get()
    }

    pub fn abort(&self) {
        if self.cancelled.replace(true) {
            return;
        }
        // Dropping the accepted future cancels that exact canonical subtask.
        // Its original host owner may remain pending; this is never labelled
        // physical host retirement or permission to reconnect/replay.
        if self.admitted.get() {
            pump::Pump::current().enter(|| {
                self.work.borrow_mut().take();
                self.upload.borrow_mut().take();
                self.body.borrow_mut().take();
            });
        }
    }

    pub fn fail(&self, error: raw::HttpError) {
        if self.failure.get().is_none() {
            self.failure.set(Some(error));
        }
        self.abort();
    }

    pub fn local_fail(&self, error: raw::HttpError) {
        // A local body/protocol fault after an original import was started
        // cannot establish that its remote mutation did not happen. Preserve
        // any already known host failure; never reconnect or replay it.
        self.fail(if self.dispatch_possible.get() {
            raw::HttpError::Uncertain
        } else {
            error
        });
    }

    fn complete(&self, result: Completion) {
        match result {
            Completion::Opened(Ok(value)) => *self.upload.borrow_mut() = Some(value),
            Completion::Written(Ok(value), bytes) => {
                self.written.set(self.written.get() + bytes);
                *self.upload.borrow_mut() = Some(value);
            }
            Completion::Response(Ok(response)) => {
                let header_bytes = response
                    .headers
                    .iter()
                    .map(|header| header.name.len() + header.value.len() + 4)
                    .sum::<usize>();
                if response.headers.len() > MAX_HEADERS || header_bytes > MAX_HEADER_BYTES {
                    self.fail(raw::HttpError::ResponseTooLarge);
                    return;
                }
                *self.body.borrow_mut() = Some(response.body);
                *self.response.borrow_mut() = Some((response.status, response.headers));
                self.headers_ready.set(true);
            }
            Completion::Read(Ok((body, bytes))) => {
                *self.body.borrow_mut() = Some(body);
                self.read_requested.set(false);
                if let Some(bytes) = bytes {
                    if bytes.len() > CHUNK {
                        self.fail(raw::HttpError::ResponseTooLarge);
                    } else {
                        *self.input.borrow_mut() = Some(Buffer { bytes, position: 0 });
                    }
                } else {
                    self.eof.set(true);
                }
            }
            Completion::Opened(Err(error))
            | Completion::Written(Err(error), _)
            | Completion::Response(Err(error))
            | Completion::Read(Err(error)) => self.fail(error),
        }
    }

    fn next(&self) -> Option<Work> {
        if let Some(request) = self.request.borrow_mut().take() {
            self.dispatch_possible.set(true);
            return Some(Box::pin(async move {
                Completion::Opened(raw::open(request).await)
            }));
        }
        let upload = self.upload.borrow_mut().take();
        if let Some(upload) = upload {
            if let Some(bytes) = self.queued.borrow_mut().take() {
                let length = bytes.len() as u64;
                return Some(Box::pin(async move {
                    let result = raw::write(&upload, bytes).await;
                    Completion::Written(result.map(|()| upload), length)
                }));
            }
            if self.output_finished.get() {
                if self
                    .expected
                    .get()
                    .is_some_and(|length| length != self.written.get())
                {
                    self.local_fail(raw::HttpError::InvalidRequest);
                    drop(upload);
                    return None;
                }
                return Some(Box::pin(async move {
                    Completion::Response(raw::finish(upload).await)
                }));
            }
            *self.upload.borrow_mut() = Some(upload);
        }
        if self.read_requested.get() && !self.eof.get() && self.input.borrow().is_none() {
            if let Some(body) = self.body.borrow_mut().take() {
                return Some(Box::pin(async move {
                    let result = async {
                        let chunk = raw::read(&body, CHUNK as u32).await?;
                        let bytes = if let Some(chunk) = chunk {
                            Some(raw::chunk_bytes(&chunk).await?)
                        } else {
                            None
                        };
                        Ok((body, bytes))
                    }
                    .await;
                    Completion::Read(result)
                }));
            }
        }
        None
    }
}

impl pump::Progress for Exchange {
    fn progress(&self, context: &mut Context<'_>) {
        // Bound immediate metadata/body state transitions per poll; canonical
        // waits suspend the caller while the node keeps the original owners.
        for _ in 0..4 {
            if self.cancelled.get() || self.failure.get().is_some() {
                return;
            }
            // End the RefCell borrow before next can abort a malformed body.
            let work = self.work.borrow_mut().take();
            let work = work.or_else(|| self.next());
            let Some(mut work) = work else {
                return;
            };
            match work.as_mut().poll(context) {
                Poll::Pending => {
                    *self.work.borrow_mut() = Some(work);
                    return;
                }
                Poll::Ready(result) => {
                    drop(work);
                    self.complete(result);
                }
            }
        }
    }
}
impl Drop for Exchange {
    fn drop(&mut self) {
        if self.admitted.get() {
            pump::Pump::current().enter(|| {
                self.work.get_mut().take();
                self.upload.get_mut().take();
                self.body.get_mut().take();
            });
        }
    }
}
