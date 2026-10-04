//! Complete pinned HTTP type identities with explicit denial in the closed mode.
//! No HTTP host import, network call, future completion or successful I/O exists.
use super::{
    exports::wasi::{
        http::{outgoing_handler, types},
        io,
    },
    quota::Slot,
    ClosedRuntime,
};
use std::cell::{Cell, RefCell};

pub struct Fields {
    entries: Vec<(String, Vec<u8>)>,
    _slot: Slot,
}
pub struct Request {
    _headers: Fields,
    method: RefCell<types::Method>,
    authority: RefCell<Option<String>>,
    path: RefCell<Option<String>>,
    scheme: RefCell<Option<types::Scheme>>,
    body_taken: Cell<bool>,
    _slot: Slot,
}
pub struct Options;
pub struct Future;
pub struct Response;
pub struct IncomingBody;
pub struct OutgoingBody;
pub struct Trailers;
impl types::Guest for ClosedRuntime {
    type Fields = Fields;
    type OutgoingRequest = Request;
    type RequestOptions = Options;
    type FutureIncomingResponse = Future;
    type IncomingResponse = Response;
    type IncomingBody = IncomingBody;
    type OutgoingBody = OutgoingBody;
    type FutureTrailers = Trailers;
}
impl types::GuestRequestOptions for Options {}
impl types::GuestFutureTrailers for Trailers {}
impl types::GuestFields for Fields {
    fn from_list(entries: Vec<(String, Vec<u8>)>) -> Result<types::Fields, types::HeaderError> {
        if entries.len() > 32
            || entries
                .iter()
                .map(|(name, value)| name.len() + value.len() + 4)
                .sum::<usize>()
                > 8192
            || entries.iter().any(|(name, value)| {
                name.is_empty()
                    || name.len() > 64
                    || !name.bytes().all(|byte| {
                        byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte)
                    })
                    || value
                        .iter()
                        .any(|byte| *byte < 32 && *byte != 9 || *byte == 127)
            })
        {
            return Err(types::HeaderError::InvalidSyntax);
        }
        let slot = Slot::new();
        Ok(types::Fields::new(Self {
            entries,
            _slot: slot,
        }))
    }
    fn entries(&self) -> Vec<(String, Vec<u8>)> {
        self.entries.clone()
    }
}
impl types::GuestOutgoingRequest for Request {
    fn new(headers: types::Headers) -> Self {
        let slot = Slot::new();
        Self {
            _headers: headers.into_inner::<Fields>(),
            method: RefCell::new(types::Method::Get),
            authority: RefCell::new(None),
            path: RefCell::new(None),
            scheme: RefCell::new(None),
            body_taken: Cell::new(false),
            _slot: slot,
        }
    }
    fn body(&self) -> Result<types::OutgoingBody, ()> {
        self.body_taken.set(true);
        Err(())
    }
    fn set_method(&self, method: types::Method) -> Result<(), ()> {
        if matches!(&method, types::Method::Other(value) if value.len() > 64) {
            return Err(());
        }
        *self.method.borrow_mut() = method;
        Ok(())
    }
    fn set_path_with_query(&self, value: Option<String>) -> Result<(), ()> {
        if value.as_ref().is_some_and(|value| value.len() > 2048) {
            return Err(());
        }
        *self.path.borrow_mut() = value;
        Ok(())
    }
    fn set_scheme(&self, value: Option<types::Scheme>) -> Result<(), ()> {
        if matches!(&value, Some(types::Scheme::Other(value)) if value.len() > 32) {
            return Err(());
        }
        *self.scheme.borrow_mut() = value;
        Ok(())
    }
    fn set_authority(&self, value: Option<String>) -> Result<(), ()> {
        if value.as_ref().is_some_and(|value| value.len() > 300) {
            return Err(());
        }
        *self.authority.borrow_mut() = value;
        Ok(())
    }
}
impl outgoing_handler::Guest for ClosedRuntime {
    fn handle(
        _request: types::OutgoingRequest,
        _options: Option<types::RequestOptions>,
    ) -> Result<types::FutureIncomingResponse, types::ErrorCode> {
        Err(types::ErrorCode::HttpRequestDenied)
    }
}
// These resources are never created by this closed backend. Invalid/foreign
// handles are rejected by the generated resource ABI before reaching a method.
impl types::GuestFutureIncomingResponse for Future {
    fn subscribe(&self) -> io::poll::Pollable {
        panic!("closed HTTP has no future owner")
    }
    fn get(&self) -> Option<Result<Result<types::IncomingResponse, types::ErrorCode>, ()>> {
        Some(Ok(Err(types::ErrorCode::HttpRequestDenied)))
    }
}
impl types::GuestIncomingResponse for Response {
    fn status(&self) -> u16 {
        panic!("closed HTTP has no response owner")
    }
    fn headers(&self) -> types::Headers {
        panic!("closed HTTP has no response owner")
    }
    fn consume(&self) -> Result<types::IncomingBody, ()> {
        Err(())
    }
}
impl types::GuestIncomingBody for IncomingBody {
    fn stream(&self) -> Result<io::streams::InputStream, ()> {
        Err(())
    }
    fn finish(_this: types::IncomingBody) -> types::FutureTrailers {
        panic!("closed HTTP has no body owner")
    }
}
impl types::GuestOutgoingBody for OutgoingBody {
    fn write(&self) -> Result<io::streams::OutputStream, ()> {
        Err(())
    }
    fn finish(
        _this: types::OutgoingBody,
        _trailers: Option<types::Trailers>,
    ) -> Result<(), types::ErrorCode> {
        Err(types::ErrorCode::HttpRequestDenied)
    }
}
