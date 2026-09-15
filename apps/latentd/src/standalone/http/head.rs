//! Parse once after a bounded CRLF head; no header merging or permissive framing.
use super::Shared;
use crate::config::http::Authentication;
use latent_core::{IncomingDeadline, InvocationPrincipal};
use latent_ingress::http::{
    Collector, HeaderView, HttpVersion, RawHead, MAX_HEADERS, MAX_HEADER_BYTES, MAX_REQUEST_BODY,
};

pub(super) const MAX_HEAD: usize = 32 * 1024;
pub(super) struct Head {
    pub collector: Collector,
    pub principal: InvocationPrincipal,
    pub content_length: usize,
    pub close: bool,
    method: latent_ingress::http::Method,
}
impl Head {
    pub(super) fn method(&self) -> latent_ingress::http::Method {
        self.method
    }
}
pub(super) fn parse(
    bytes: &[u8],
    shared: &Shared,
    deadline: IncomingDeadline,
) -> Result<Head, u16> {
    require_crlf(bytes)?;
    let mut fields = [httparse::EMPTY_HEADER; MAX_HEADERS];
    let mut request = httparse::Request::new(&mut fields);
    if !matches!(request.parse(bytes), Ok(httparse::Status::Complete(n)) if n == bytes.len())
        || request.version != Some(1)
    {
        return Err(400);
    }
    let mut headers = [HeaderView {
        name: "",
        value: b"",
    }; MAX_HEADERS];
    let mut count = 0;
    let mut host = None;
    let mut authorization = None;
    let mut content_length = None;
    let mut close = None;
    let mut total = 0usize;
    for field in request.headers.iter() {
        total += field.name.len() + field.value.len();
        if total > MAX_HEADER_BYTES {
            return Err(431);
        }
        if field.name.eq_ignore_ascii_case("connection") {
            // Consume only these explicit transport options. Never honor an
            // arbitrary nomination that could strip authorization or framing.
            if close.is_some() {
                return Err(400);
            }
            close = Some(if field.value.eq_ignore_ascii_case(b"close") {
                true
            } else if field.value.eq_ignore_ascii_case(b"keep-alive") {
                false
            } else {
                return Err(400);
            });
            continue;
        }
        if field.name.eq_ignore_ascii_case("expect") {
            return Err(417);
        }
        if field.name.eq_ignore_ascii_case("forwarded")
            || field
                .name
                .get(..12)
                .is_some_and(|s| s.eq_ignore_ascii_case("x-forwarded-"))
        {
            // Even approved proxy peers cannot supply identity. A configured
            // proxy may attach transport metadata, which is discarded entirely.
            if shared.settings.peers.is_empty() {
                return Err(400);
            }
        }
        if field.name.eq_ignore_ascii_case("host") {
            if host.is_some() {
                return Err(400);
            }
            host = Some(std::str::from_utf8(field.value).map_err(|_| 400u16)?);
        }
        if field.name.eq_ignore_ascii_case("authorization") {
            if authorization.is_some() {
                return Err(400);
            }
            authorization = Some(field.value);
        }
        if field.name.eq_ignore_ascii_case("content-length") {
            if content_length.is_some() {
                return Err(400);
            }
            content_length = Some(body_length(field.value)?);
        }
        headers[count] = HeaderView {
            name: field.name,
            value: field.value,
        };
        count += 1;
    }
    let collector = shared
        .handle
        .0
        .pool
        .begin(
            RawHead {
                version: HttpVersion::Http11,
                method: request.method.ok_or(400u16)?,
                scheme: shared.settings.scheme,
                authority: host.ok_or(400u16)?,
                target: request.path.ok_or(400u16)?,
                headers: &headers[..count],
            },
            deadline,
        )
        .map_err(|e| e.status().unwrap_or(0))?;
    let principal = authenticate(shared, collector.target().authority(), authorization)?;
    let method =
        latent_ingress::http::Method::parse(request.method.ok_or(400u16)?).map_err(|_| 405u16)?;
    Ok(Head {
        collector,
        principal,
        content_length: content_length.unwrap_or(0),
        close: close.unwrap_or(false),
        method,
    })
}
fn authenticate(
    shared: &Shared,
    authority: &str,
    authorization: Option<&[u8]>,
) -> Result<InvocationPrincipal, u16> {
    match &shared.settings.authentication {
        Authentication::Bearer(credentials) => {
            let value = authorization.ok_or(401u16)?;
            if value.len() > 519 || value.len() < 8 || !value[..7].eq_ignore_ascii_case(b"Bearer ")
            {
                return Err(401);
            }
            let token = &value[7..];
            if !token.iter().all(|b| b.is_ascii_graphic() && *b != b',') {
                return Err(401);
            }
            credentials
                .iter()
                .find(|c| equal_token(c.token.as_bytes(), token))
                .map(|c| c.principal.clone())
                .ok_or(401)
        }
        Authentication::PublicOrigins(origins) => {
            if authorization.is_some() {
                return Err(401);
            }
            origins
                .iter()
                .find(|(host, _)| host == authority)
                .map(|(_, p)| p.clone())
                .ok_or(403)
        }
    }
}
fn equal_token(expected: &[u8], actual: &[u8]) -> bool {
    // Fixed token bound and no data-dependent early mismatch. Avoid logging or
    // reflecting either configured or supplied credential bytes.
    let mut difference = expected.len() ^ actual.len();
    for i in 0..512 {
        difference |= usize::from(
            expected.get(i).copied().unwrap_or(0) ^ actual.get(i).copied().unwrap_or(0),
        );
    }
    difference == 0
}

fn require_crlf(bytes: &[u8]) -> Result<(), u16> {
    // httparse intentionally tolerates bare LF. This profile requires exact CRLF
    // and no whitespace before a request line or obsolete folded field.
    for (i, byte) in bytes.iter().enumerate() {
        if (*byte == b'\n' && (i == 0 || bytes[i - 1] != b'\r'))
            || (*byte == b'\r' && bytes.get(i + 1) != Some(&b'\n'))
        {
            return Err(400);
        }
    }
    if bytes.first().is_none_or(|b| !b.is_ascii_uppercase()) {
        return Err(400);
    }
    Ok(())
}

fn body_length(bytes: &[u8]) -> Result<usize, u16> {
    if bytes.is_empty() || !bytes.iter().all(u8::is_ascii_digit) {
        return Err(400);
    }
    let mut n = 0usize;
    for b in bytes {
        n = n
            .checked_mul(10)
            .and_then(|n| n.checked_add(usize::from(*b - b'0')))
            .ok_or(413u16)?;
    }
    if n > MAX_REQUEST_BODY {
        return Err(413);
    }
    Ok(n)
}
