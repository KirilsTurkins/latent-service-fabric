//! Full nominal standard-WASI client resource surface over original typed HTTP.
use super::{
    exports::wasi::{
        http::{outgoing_handler, types},
        io,
    },
    fields::{Fields, ParentFields},
    http_io::{Input, Output},
    latent::http::streaming as raw,
    poll::Pollable,
    pump,
    request_options::RequestOptions,
    state::{Exchange, Slot, MAX_BODY},
    StandardRuntime,
};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};

pub struct Request {
    headers: ParentFields,
    method: RefCell<types::Method>,
    authority: RefCell<Option<String>>,
    path: RefCell<Option<String>>,
    scheme: RefCell<Option<types::Scheme>>,
    exchange: Rc<Exchange>,
    handled: Cell<bool>,
    _slot: Slot,
}
pub enum ServerOnly {}
pub struct FutureResponse {
    exchange: Rc<Exchange>,
    consumed: Cell<bool>,
    _slot: Slot,
}
pub struct Response {
    exchange: Rc<Exchange>,
    headers: ParentFields,
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
    exchange: Rc<Exchange>,
    consumed: Cell<bool>,
    headers: RefCell<Option<ParentFields>>,
    _slot: Slot,
}

fn header_error(value: super::fields::HeaderError) -> types::HeaderError {
    match value {
        super::fields::HeaderError::InvalidSyntax => types::HeaderError::InvalidSyntax,
        super::fields::HeaderError::Forbidden => types::HeaderError::Forbidden,
        super::fields::HeaderError::Immutable => types::HeaderError::Immutable,
    }
}

impl types::GuestFields for Fields {
    fn new() -> Self {
        Fields::new()
    }
    fn from_list(entries: Vec<(String, Vec<u8>)>) -> Result<types::Fields, types::HeaderError> {
        Fields::from_list(entries)
            .map(types::Fields::new)
            .map_err(header_error)
    }
    fn get(&self, name: String) -> Vec<Vec<u8>> {
        Fields::get(self, &name)
    }
    fn has(&self, name: String) -> bool {
        Fields::has(self, &name)
    }
    fn set(&self, name: String, value: Vec<Vec<u8>>) -> Result<(), types::HeaderError> {
        Fields::set(self, name, value).map_err(header_error)
    }
    fn delete(&self, name: String) -> Result<(), types::HeaderError> {
        Fields::delete(self, &name).map_err(header_error)
    }
    fn append(&self, name: String, value: Vec<u8>) -> Result<(), types::HeaderError> {
        Fields::append(self, name, value).map_err(header_error)
    }
    fn entries(&self) -> Vec<(String, Vec<u8>)> {
        Fields::entries(self)
    }
    fn clone(&self) -> types::Fields {
        types::Fields::new(self.deep_clone())
    }
}

impl types::GuestRequestOptions for RequestOptions {
    fn new() -> Self {
        RequestOptions::new()
    }
    fn connect_timeout(&self) -> Option<u64> {
        RequestOptions::connect_timeout(self)
    }
    fn first_byte_timeout(&self) -> Option<u64> {
        RequestOptions::first_byte_timeout(self)
    }
    fn between_bytes_timeout(&self) -> Option<u64> {
        RequestOptions::between_bytes_timeout(self)
    }
    fn set_connect_timeout(&self, value: Option<u64>) -> Result<(), ()> {
        RequestOptions::set_connect_timeout(self, value).map_err(|_| ())
    }
    fn set_first_byte_timeout(&self, value: Option<u64>) -> Result<(), ()> {
        RequestOptions::set_first_byte_timeout(self, value).map_err(|_| ())
    }
    fn set_between_bytes_timeout(&self, value: Option<u64>) -> Result<(), ()> {
        RequestOptions::set_between_bytes_timeout(self, value).map_err(|_| ())
    }
}

struct TrailerReady(Rc<Exchange>);
impl pump::Readiness for TrailerReady {
    fn ready(&self) -> bool {
        self.0.trailers_ready()
    }
}
impl types::GuestFutureTrailers for Trailers {
    fn subscribe(&self) -> io::poll::Pollable {
        Pollable::new(Rc::new(TrailerReady(self.exchange.clone())))
    }
    fn get(&self) -> Option<Result<Result<Option<types::Trailers>, types::ErrorCode>, ()>> {
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
        let trailers = self.exchange.trailers.borrow();
        let rows = trailers.as_ref()?;
        self.consumed.set(true);
        if rows.is_empty() {
            return Some(Ok(Ok(None)));
        }
        let parent = ParentFields::response(
            rows.iter()
                .map(|h| (h.name.clone(), h.value.as_bytes().to_vec()))
                .collect(),
        )
        .expect("invalid bounded host trailers");
        let child = types::Fields::new(parent.child());
        *self.headers.borrow_mut() = Some(parent);
        Some(Ok(Ok(Some(child))))
    }
}

// This is an outbound-client profile. No incoming handler can manufacture
// these resources. The one public server constructor has no result channel,
// so reaching it fails explicitly rather than inventing a sent response.
impl types::GuestIncomingRequest for ServerOnly {
    fn method(&self) -> types::Method {
        match *self {}
    }
    fn path_with_query(&self) -> Option<String> {
        match *self {}
    }
    fn scheme(&self) -> Option<types::Scheme> {
        match *self {}
    }
    fn authority(&self) -> Option<String> {
        match *self {}
    }
    fn headers(&self) -> types::Headers {
        match *self {}
    }
    fn consume(&self) -> Result<types::IncomingBody, ()> {
        match *self {}
    }
}
impl types::GuestOutgoingResponse for ServerOnly {
    fn new(_headers: types::Headers) -> Self {
        panic!("unsupported-wasi-http-server-response")
    }
    fn status_code(&self) -> u16 {
        match *self {}
    }
    fn set_status_code(&self, _status: u16) -> Result<(), ()> {
        match *self {}
    }
    fn headers(&self) -> types::Headers {
        match *self {}
    }
    fn body(&self) -> Result<types::OutgoingBody, ()> {
        match *self {}
    }
}
impl types::GuestResponseOutparam for ServerOnly {
    fn set(
        param: types::ResponseOutparam,
        _response: Result<types::OutgoingResponse, types::ErrorCode>,
    ) {
        match param.into_inner::<Self>() {}
    }
}

impl types::Guest for StandardRuntime {
    type Fields = Fields;
    type OutgoingRequest = Request;
    type RequestOptions = RequestOptions;
    type IncomingRequest = ServerOnly;
    type OutgoingResponse = ServerOnly;
    type ResponseOutparam = ServerOnly;
    type FutureIncomingResponse = FutureResponse;
    type IncomingResponse = Response;
    type IncomingBody = IncomingBody;
    type OutgoingBody = OutgoingBody;
    type FutureTrailers = Trailers;
    fn http_error_code(err: io::error::ErrorBorrow<'_>) -> Option<types::ErrorCode> {
        Some(error_code(err.get::<super::HttpError>().cause))
    }
}
impl types::GuestOutgoingRequest for Request {
    fn new(headers: types::Headers) -> Self {
        let fields = headers.into_inner::<Fields>();
        let headers = fields.into_parent();
        let slot = Slot::new();
        Self {
            headers,
            method: RefCell::new(types::Method::Get),
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
    fn method(&self) -> types::Method {
        self.method.borrow().clone()
    }
    fn set_method(&self, method: types::Method) -> Result<(), ()> {
        if let types::Method::Other(value) = &method {
            if !super::fields::token(value) {
                return Err(());
            }
        }
        *self.method.borrow_mut() = method;
        Ok(())
    }
    fn path_with_query(&self) -> Option<String> {
        self.path.borrow().clone()
    }
    fn scheme(&self) -> Option<types::Scheme> {
        self.scheme.borrow().clone()
    }
    fn authority(&self) -> Option<String> {
        self.authority.borrow().clone()
    }
    fn headers(&self) -> types::Headers {
        types::Fields::new(self.headers.child())
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
        if let Some(types::Scheme::Other(scheme)) = &value {
            let mut bytes = scheme.bytes();
            if !bytes.next().is_some_and(|byte| byte.is_ascii_alphabetic())
                || !bytes.all(|byte| byte.is_ascii_alphanumeric() || b"+-.".contains(&byte))
            {
                return Err(());
            }
        }
        *self.scheme.borrow_mut() = value;
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
        let scheme = match scheme.as_ref() {
            Some(types::Scheme::Http) => "http",
            Some(types::Scheme::Https) => "https",
            Some(types::Scheme::Other(value)) if value.eq_ignore_ascii_case("http") => "http",
            Some(types::Scheme::Other(value)) if value.eq_ignore_ascii_case("https") => "https",
            _ => return Err(types::ErrorCode::HttpRequestUriInvalid),
        };
        let authority = authority
            .as_ref()
            .ok_or(types::ErrorCode::HttpRequestUriInvalid)?;
        let path = self.path.borrow();
        let path = path.as_deref().unwrap_or("/");
        let url = format!("{scheme}://{authority}{path}");
        if url.len() > 2048 {
            return Err(types::ErrorCode::HttpRequestUriTooLong);
        }
        let mut headers = Vec::new();
        let (mut body_media_type, mut idempotency_key, mut body_length) = (None, None, None);
        for (name, bytes) in &self.headers.entries() {
            if super::fields::reserved(name) {
                return Err(types::ErrorCode::HttpRequestDenied);
            }
            let value =
                std::str::from_utf8(bytes).map_err(|_| types::ErrorCode::HttpProtocolError)?;
            match name.to_ascii_lowercase().as_str() {
                "content-type" => {
                    if body_media_type.is_some() {
                        return Err(types::ErrorCode::HttpProtocolError);
                    }
                    body_media_type = Some(value.to_owned());
                }
                "idempotency-key" => {
                    if idempotency_key.is_some() {
                        return Err(types::ErrorCode::HttpProtocolError);
                    }
                    idempotency_key = Some(value.to_owned());
                }
                "content-length" => {
                    if body_length.is_some() {
                        return Err(types::ErrorCode::HttpProtocolError);
                    }
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
            method: match &*self.method.borrow() {
                types::Method::Get => raw::Method::Get,
                types::Method::Head => raw::Method::Head,
                types::Method::Post => raw::Method::Post,
                types::Method::Put => raw::Method::Put,
                types::Method::Delete => raw::Method::Delete,
                types::Method::Options => raw::Method::Options,
                types::Method::Patch => raw::Method::Patch,
                types::Method::Other(value) => match value.as_str() {
                    "GET" => raw::Method::Get,
                    "HEAD" => raw::Method::Head,
                    "POST" => raw::Method::Post,
                    "PUT" => raw::Method::Put,
                    "DELETE" => raw::Method::Delete,
                    "OPTIONS" => raw::Method::Options,
                    "PATCH" => raw::Method::Patch,
                    _ => return Err(types::ErrorCode::HttpRequestMethodInvalid),
                },
                _ => return Err(types::ErrorCode::HttpRequestMethodInvalid),
            },
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

impl outgoing_handler::Guest for StandardRuntime {
    fn handle(
        request: types::OutgoingRequest,
        options: Option<types::RequestOptions>,
    ) -> Result<types::FutureIncomingResponse, types::ErrorCode> {
        let _options = options
            .map(|value| value.into_inner::<RequestOptions>().consume())
            .transpose()
            .map_err(|_| types::ErrorCode::ConfigurationError)?;
        let request = request.into_inner::<Request>();
        request.headers.require_no_children();
        let metadata = request.metadata()?;
        if let Some(error) = request.exchange.failure.get() {
            return Err(error_code(error));
        }
        if request.exchange.cancelled.get() {
            return Err(marker("latent-http-cancelled"));
        }
        let slot = Slot::new();
        request.exchange.admit(metadata).map_err(runtime_error)?;
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
            headers: ParentFields::response(
                self.exchange
                    .response
                    .borrow()
                    .as_ref()
                    .expect("response head owner")
                    .1
                    .iter()
                    .map(|header| (header.name.clone(), header.value.as_bytes().to_vec()))
                    .collect(),
            )
            .expect("host returned invalid bounded response fields"),
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
        types::Fields::new(self.headers.child())
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
        body.exchange.request_trailers();
        types::FutureTrailers::new(Trailers {
            exchange: body.exchange.clone(),
            consumed: Cell::new(false),
            headers: RefCell::new(None),
            _slot: slot,
        })
    }
}
impl Drop for IncomingBody {
    fn drop(&mut self) {
        assert_eq!(
            self.exchange.input_views.get(),
            0,
            "incoming body still has an input child"
        );
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
        assert_eq!(
            self.exchange.output_views.get(),
            0,
            "outgoing body still has an output child"
        );
        if !self.finished.get() {
            self.exchange.abort();
        }
    }
}

fn marker(value: &str) -> types::ErrorCode {
    types::ErrorCode::InternalError(Some(value.into()))
}
fn runtime_error(error: super::latent::runtime::activation::Error) -> types::ErrorCode {
    use super::latent::runtime::activation::Error;
    marker(match error {
        Error::Unavailable => "latent-runtime-unavailable",
        Error::PermissionDenied => "latent-runtime-permission-denied",
        Error::ResourceExhausted => "latent-runtime-resource-exhausted",
        Error::Cancelled => "latent-runtime-cancelled",
        Error::Deadline => "latent-runtime-deadline",
        Error::InvalidState => "latent-runtime-invalid-state",
        Error::InvalidToken => "latent-runtime-invalid-token",
    })
}
pub fn error_code(error: raw::HttpError) -> types::ErrorCode {
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
