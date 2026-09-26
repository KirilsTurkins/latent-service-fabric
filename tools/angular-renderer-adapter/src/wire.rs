//! Private JSON crosses only guest memories inside the composed component.
//! Identity is sampled from sealed host context, never supplied by HTTP fields.
use super::abi::exports::latent::web::application::{Method, Request, Scheme};
use super::abi::latent::context::context;
use serde::{Deserialize, Serialize};
use std::io::{self, Write};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Input<'a> {
    format_version: u32,
    request: HttpRequest<'a>,
    context: Context,
    #[cfg(feature = "backend-http")]
    backend: Option<super::backend::Data>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HttpRequest<'a> {
    method: &'static str,
    scheme: &'static str,
    authority: &'a str,
    path: &'a str,
    query: Option<&'a str>,
    headers: Vec<BorrowedHeader<'a>>,
    media_type: Option<&'a str>,
    body_base64: &'a str,
}
#[derive(Serialize)]
struct BorrowedHeader<'a> {
    name: &'a str,
    value: &'a [u8],
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Context {
    activation_id: String,
    publication: Option<String>,
    root_activation_id: String,
    parent_activation_id: Option<String>,
    principal: Principal,
    trace: InvocationTrace,
    // Decimal string preserves exact u64 values through JavaScript JSON.
    deadline_unix_millis: Option<String>,
}
#[derive(Serialize)]
struct Principal {
    subject: String,
    kind: String,
    tenant: Option<String>,
    service: Option<String>,
    claims: Vec<(String, String)>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct InvocationTrace {
    trace_id: String,
    span_id: String,
    trace_flags: u8,
    baggage: Vec<(String, String)>,
}

pub fn request(value: &Request) -> String {
    encode(&frame(value))
}

#[cfg(feature = "backend-http")]
pub fn render_request(value: &Request, backend: Option<super::backend::Data>) -> String {
    let mut input = frame(value);
    input.backend = backend;
    encode(&input)
}

fn frame(value: &Request) -> Input<'_> {
    let principal = context::principal();
    let trace = context::trace();
    Input {
        format_version: 1,
        #[cfg(feature = "backend-http")]
        backend: None,
        request: HttpRequest {
            method: method(value.method),
            scheme: match value.scheme {
                Scheme::Http => "http",
                Scheme::Https => "https",
            },
            authority: &value.authority,
            path: &value.path,
            query: value.query.as_deref(),
            headers: value
                .headers
                .iter()
                .map(|h| BorrowedHeader {
                    name: &h.name,
                    value: &h.value,
                })
                .collect(),
            media_type: value.media_type.as_deref(),
            body_base64: &value.body_base64,
        },
        context: Context {
            activation_id: context::activation_id(),
            publication: context::metadata()
                .into_iter()
                .find_map(|(key, value)| (key == "guest.lsf.web-publication").then_some(value)),
            root_activation_id: context::root_activation_id(),
            parent_activation_id: context::parent_activation_id(),
            principal: Principal {
                subject: principal.subject,
                kind: principal.kind,
                tenant: principal.tenant,
                service: principal.service,
                claims: principal.claims,
            },
            trace: InvocationTrace {
                trace_id: trace.trace_id,
                span_id: trace.span_id,
                trace_flags: trace.trace_flags,
                baggage: trace.baggage,
            },
            deadline_unix_millis: context::deadline_unix_millis().map(|v| v.to_string()),
        },
    }
}

fn encode(input: &Input<'_>) -> String {
    let mut output = Capped(Vec::new());
    serde_json::to_writer(&mut output, input).expect("renderer-request-frame-limit");
    String::from_utf8(output.0).expect("JSON is UTF-8")
}
fn method(value: Method) -> &'static str {
    match value {
        Method::Get => "GET",
        Method::Head => "HEAD",
        Method::Post => "POST",
        Method::Put => "PUT",
        Method::Patch => "PATCH",
        Method::Delete => "DELETE",
        Method::Options => "OPTIONS",
    }
}
struct Capped(Vec<u8>);
impl Write for Capped {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > (256 * 1024usize).saturating_sub(self.0.len()) {
            return Err(io::ErrorKind::InvalidData.into());
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Document {
    pub status: u16,
    pub headers: Vec<OwnedHeader>,
    pub html: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OwnedHeader {
    pub name: String,
    pub value: Vec<u8>,
}
