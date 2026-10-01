//! The precise WASI HTTP resource surface emitted by the pinned .NET BCL.
use super::{
    ClosedRuntime,
    exports::wasi::{
        http::{outgoing_handler, types},
        io,
    },
    http_io::{Input, Output},
    latent::http::streaming as raw,
    poll::Pollable,
    pump,
    state::{Exchange, MAX_BODY, MAX_HEADER_BYTES, MAX_HEADERS, Slot},
};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};

pub struct Fields {
    entries: Vec<(String, Vec<u8>)>,
    _slot: Slot,
}
pub struct Request {
    entries: Vec<(String, Vec<u8>)>,
    method: Cell<raw::Method>,
    authority: RefCell<Option<String>>,
    path: RefCell<Option<String>>,
    scheme: RefCell<Option<String>>,
    exchange: Rc<Exchange>,
    handled: Cell<bool>,
    _slot: Slot,
}
pub struct Options;
pub struct FutureResponse {
    exchange: Rc<Exchange>,
    consumed: Cell<bool>,
    _slot: Slot,
}
pub struct Response {
    exchange: Rc<Exchange>,
    consumed: Cell<bool>,
    _slot: Slot,
}
pub struct IncomingBody {
    exchange: Rc<Exchange>,
    _slot: Slot,
}
pub struct OutgoingBody {
    exchange: Rc<Exchange>,
    stream_taken: Cell<bool>,
    finished: Cell<bool>,
    _slot: Slot,
}
pub struct Trailers {
    _exchange: Rc<Exchange>,
    _slot: Slot,
}

impl types::Guest for ClosedRuntime {
    type Fields = Fields;
    type OutgoingRequest = Request;
    type RequestOptions = Options;
    type FutureIncomingResponse = FutureResponse;
    type IncomingResponse = Response;
    type IncomingBody = IncomingBody;
    type OutgoingBody = OutgoingBody;
    type FutureTrailers = Trailers;
}
impl types::GuestRequestOptions for Options {}
impl types::GuestFutureTrailers for Trailers {}

fn token(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte))
}
fn reserved(name: &str) -> bool {
    [
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "authorization",
        "cookie",
        "set-cookie",
        "expect",
        "content-encoding",
        "accept-encoding",
        "x-api-key",
        "x-auth-token",
        "x-amz-security-token",
    ]
    .iter()
    .any(|value| name.eq_ignore_ascii_case(value))
}

impl types::GuestFields for Fields {
    fn from_list(entries: Vec<(String, Vec<u8>)>) -> Result<types::Fields, types::HeaderError> {
        if entries.len() > MAX_HEADERS
            || entries
                .iter()
                .map(|(name, value)| name.len() + value.len() + 4)
                .sum::<usize>()
                > MAX_HEADER_BYTES
        {
            return Err(types::HeaderError::InvalidSyntax);
        }
        for (index, (name, value)) in entries.iter().enumerate() {
            if !token(name)
                || std::str::from_utf8(value).is_err()
                || value
                    .iter()
                    .any(|byte| *byte < 32 && *byte != 9 || *byte == 127)
                || entries[..index]
                    .iter()
                    .any(|(other, _)| name.eq_ignore_ascii_case(other))
            {
                return Err(types::HeaderError::InvalidSyntax);
            }
            if reserved(name) {
                return Err(types::HeaderError::Forbidden);
            }
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
        let fields = headers.into_inner::<Fields>();
        Self {
            entries: fields.entries,
            method: Cell::new(raw::Method::Get),
            authority: RefCell::new(None),
            path: RefCell::new(None),
            scheme: RefCell::new(None),
            exchange: Exchange::new(),
            handled: Cell::new(false),
            _slot: slot,
        }
    }
    fn body(&self) -> Result<types::OutgoingBody, ()> {
        if self.exchange.body_requested.replace(true) {
            return Err(());
        }
        let slot = Slot::new();
        Ok(types::OutgoingBody::new(OutgoingBody {
            exchange: self.exchange.clone(),
            stream_taken: Cell::new(false),
            finished: Cell::new(false),
            _slot: slot,
        }))
    }
    fn set_method(&self, method: types::Method) -> Result<(), ()> {
        self.method.set(match method {
            types::Method::Get => raw::Method::Get,
            types::Method::Head => raw::Method::Head,
            types::Method::Post => raw::Method::Post,
            types::Method::Put => raw::Method::Put,
            types::Method::Delete => raw::Method::Delete,
            types::Method::Options => raw::Method::Options,
            types::Method::Patch => raw::Method::Patch,
            _ => return Err(()),
        });
        Ok(())
    }
    fn set_path_with_query(&self, value: Option<String>) -> Result<(), ()> {
        if value.as_ref().is_some_and(|path| {
            !path.starts_with('/')
                || path.len() > 2048
                || path
                    .bytes()
                    .any(|byte| byte < 32 || byte == 127 || b"#\\".contains(&byte))
        }) {
            return Err(());
        }
        *self.path.borrow_mut() = value;
        Ok(())
    }
    fn set_scheme(&self, value: Option<types::Scheme>) -> Result<(), ()> {
        *self.scheme.borrow_mut() = match value {
            None => None,
            Some(types::Scheme::Http) => Some("http".into()),
            Some(types::Scheme::Https) => Some("https".into()),
            _ => return Err(()),
        };
        Ok(())
    }
    fn set_authority(&self, value: Option<String>) -> Result<(), ()> {
        if value.as_ref().is_some_and(|authority| {
            authority.is_empty()
                || authority.len() > 300
                || authority
                    .bytes()
                    .any(|byte| byte <= 32 || byte == 127 || b"@/#?\\".contains(&byte))
        }) {
            return Err(());
        }
        *self.authority.borrow_mut() = value;
        Ok(())
    }
}
impl Request {
    fn metadata(&self) -> Result<raw::Request, types::ErrorCode> {
        let scheme = self.scheme.borrow();
        let authority = self.authority.borrow();
        let scheme = scheme
            .as_ref()
            .ok_or(types::ErrorCode::HttpRequestUriInvalid)?;
        let authority = authority
            .as_ref()
            .ok_or(types::ErrorCode::HttpRequestUriInvalid)?;
        let path = self.path.borrow();
        let path = path.as_deref().unwrap_or("/");
        let url = format!("{scheme}://{authority}{path}");
        if url.len() > 2048 {
            return Err(types::ErrorCode::HttpRequestUriTooLong);
        }
        let mut headers = Vec::with_capacity(self.entries.len());
        let (mut body_media_type, mut idempotency_key, mut body_length) = (None, None, None);
        for (name, bytes) in &self.entries {
            let value =
                std::str::from_utf8(bytes).map_err(|_| types::ErrorCode::HttpProtocolError)?;
            match name.to_ascii_lowercase().as_str() {
                "content-type" => body_media_type = Some(value.to_owned()),
                "idempotency-key" => idempotency_key = Some(value.to_owned()),
                "content-length" => {
                    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                        return Err(types::ErrorCode::HttpProtocolError);
                    }
                    let length = value
                        .parse::<u64>()
                        .map_err(|_| types::ErrorCode::HttpRequestBodySize(Some(MAX_BODY)))?;
                    if length > MAX_BODY {
                        return Err(types::ErrorCode::HttpRequestBodySize(Some(MAX_BODY)));
                    }
                    body_length = Some(length);
                }
                _ => headers.push(raw::Header {
                    name: name.to_owned(),
                    value: value.to_owned(),
                }),
            }
        }
        if !self.exchange.body_requested.get() {
            if body_length.is_some_and(|length| length != 0) {
                return Err(types::ErrorCode::HttpRequestLengthRequired);
            }
            body_length = Some(0);
        }
        Ok(raw::Request {
            method: self.method.get(),
            url,
            headers,
            body_length,
            body_media_type,
            idempotency_key,
            timeout_millis: None,
        })
    }
}
impl Drop for Request {
    fn drop(&mut self) {
        if !self.handled.get() {
            self.exchange.abort();
        }
    }
}

impl outgoing_handler::Guest for ClosedRuntime {
    fn handle(
        request: types::OutgoingRequest,
        options: Option<types::RequestOptions>,
    ) -> Result<types::FutureIncomingResponse, types::ErrorCode> {
        if options.is_some() {
            return Err(types::ErrorCode::ConfigurationError);
        }
        let request = request.into_inner::<Request>();
        let metadata = request.metadata()?;
        if let Some(error) = request.exchange.failure.get() {
            return Err(error_code(error));
        }
        if request.exchange.cancelled.get() {
            return Err(marker("latent-http-cancelled"));
        }
        let slot = Slot::new();
        request
            .exchange
            .admit(metadata)
            .map_err(|_| types::ErrorCode::ConfigurationError)?;
        request.handled.set(true);
        Ok(types::FutureIncomingResponse::new(FutureResponse {
            exchange: request.exchange.clone(),
            consumed: Cell::new(false),
            _slot: slot,
        }))
    }
}
impl types::GuestFutureIncomingResponse for FutureResponse {
    fn subscribe(&self) -> io::poll::Pollable {
        Pollable::response(self.exchange.clone())
    }
    fn get(&self) -> Option<Result<Result<types::IncomingResponse, types::ErrorCode>, ()>> {
        pump::Pump::current().step();
        if self.consumed.get() {
            return Some(Err(()));
        }
        if let Some(error) = self.exchange.failure.get() {
            self.consumed.set(true);
            return Some(Ok(Err(error_code(error))));
        }
        if self.exchange.cancelled.get() {
            self.consumed.set(true);
            return Some(Ok(Err(marker("latent-http-cancelled"))));
        }
        if !self.exchange.headers_ready.get() {
            return None;
        }
        let slot = Slot::new();
        self.consumed.set(true);
        Some(Ok(Ok(types::IncomingResponse::new(Response {
            exchange: self.exchange.clone(),
            consumed: Cell::new(false),
            _slot: slot,
        }))))
    }
}
impl Drop for FutureResponse {
    fn drop(&mut self) {
        if !self.consumed.get() {
            self.exchange.abort();
        }
    }
}
impl types::GuestIncomingResponse for Response {
    fn status(&self) -> u16 {
        self.exchange
            .response
            .borrow()
            .as_ref()
            .expect("response head owner")
            .0
    }
    fn headers(&self) -> types::Headers {
        let slot = Slot::new();
        let entries = self
            .exchange
            .response
            .borrow()
            .as_ref()
            .expect("response head owner")
            .1
            .iter()
            .map(|header| (header.name.clone(), header.value.as_bytes().to_vec()))
            .collect();
        types::Fields::new(Fields {
            entries,
            _slot: slot,
        })
    }
    fn consume(&self) -> Result<types::IncomingBody, ()> {
        if self.consumed.replace(true) {
            return Err(());
        }
        let slot = Slot::new();
        Ok(types::IncomingBody::new(IncomingBody {
            exchange: self.exchange.clone(),
            _slot: slot,
        }))
    }
}
impl types::GuestIncomingBody for IncomingBody {
    fn stream(&self) -> Result<io::streams::InputStream, ()> {
        if self.exchange.stream_requested.replace(true) {
            return Err(());
        }
        Ok(io::streams::InputStream::new(Input::http(
            self.exchange.clone(),
        )))
    }
    fn finish(this: types::IncomingBody) -> types::FutureTrailers {
        let slot = Slot::new();
        let body = this.into_inner::<IncomingBody>();
        assert_eq!(
            body.exchange.input_views.get(),
            0,
            "incoming body has a live input stream"
        );
        // The pinned BCL disposes this opaque owner; it exposes no trailer get
        // API. Keep the actual body through this resource's destruction. No
        // empty trailers, verified EOF, successful drain or rollback is invented.
        types::FutureTrailers::new(Trailers {
            _exchange: body.exchange.clone(),
            _slot: slot,
        })
    }
}
impl types::GuestOutgoingBody for OutgoingBody {
    fn write(&self) -> Result<io::streams::OutputStream, ()> {
        if self.stream_taken.replace(true) {
            return Err(());
        }
        Ok(io::streams::OutputStream::new(Output::http(
            self.exchange.clone(),
        )))
    }
    fn finish(
        this: types::OutgoingBody,
        trailers: Option<types::Trailers>,
    ) -> Result<(), types::ErrorCode> {
        let body = this.into_inner::<OutgoingBody>();
        assert_eq!(
            body.exchange.output_views.get(),
            0,
            "outgoing body has a live output stream"
        );
        if trailers.is_some() {
            body.exchange.local_fail(raw::HttpError::InvalidRequest);
            return Err(error_code(
                body.exchange
                    .failure
                    .get()
                    .expect("sticky trailer rejection"),
            ));
        }
        if let Some(error) = body.exchange.failure.get() {
            return Err(error_code(error));
        }
        if body.exchange.cancelled.get() {
            return Err(types::ErrorCode::InternalError(Some(
                "latent-http-cancelled".into(),
            )));
        }
        body.finished.set(true);
        body.exchange.output_finished.set(true);
        Ok(())
    }
}
impl Drop for OutgoingBody {
    fn drop(&mut self) {
        if !self.finished.get() {
            self.exchange.abort();
        }
    }
}

fn marker(value: &str) -> types::ErrorCode {
    types::ErrorCode::InternalError(Some(value.into()))
}
fn error_code(error: raw::HttpError) -> types::ErrorCode {
    match error {
        raw::HttpError::InvalidUrl => types::ErrorCode::HttpRequestUriInvalid,
        raw::HttpError::InvalidRequest => types::ErrorCode::HttpProtocolError,
        raw::HttpError::PermissionDenied => types::ErrorCode::HttpRequestDenied,
        raw::HttpError::RequestTooLarge => marker("latent-http-request-too-large"),
        raw::HttpError::ResponseTooLarge => marker("latent-http-response-too-large"),
        raw::HttpError::DeadlineExceeded => marker("latent-http-deadline-exceeded"),
        raw::HttpError::Cancelled => marker("latent-http-cancelled"),
        raw::HttpError::BudgetExhausted => marker("latent-http-budget-exhausted"),
        raw::HttpError::DnsFailed => types::ErrorCode::DnsError(types::DnsErrorPayload {
            rcode: None,
            info_code: None,
        }),
        raw::HttpError::TlsFailed => marker("latent-http-tls-failed"),
        raw::HttpError::ConnectionFailed => marker("latent-http-connection-failed"),
        raw::HttpError::Unavailable => marker("latent-http-unavailable"),
        raw::HttpError::Uncertain => marker("latent-http-uncertain"),
        raw::HttpError::InvalidState => marker("latent-http-invalid-state"),
        raw::HttpError::UnexpectedEof => types::ErrorCode::HttpResponseIncomplete,
        raw::HttpError::UnsupportedEncoding => types::ErrorCode::HttpResponseContentCoding(None),
    }
}
