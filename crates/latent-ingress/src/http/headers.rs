use super::{
    bounded::{BoundedList, BoundedText},
    model::{Header, ResponseData},
    target::canonical_authority,
    HeaderView, HttpError, HttpVersion, Method, RawHead, MAX_HEADERS, MAX_HEADER_BYTES,
    MAX_REQUEST_BODY,
};

pub(super) struct RequestHeaders {
    pub fields: Vec<Header>,
    pub media: Option<String>,
    pub length: Option<usize>,
}

pub(super) fn token(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte)
}
fn prefix(name: &str, value: &str) -> bool {
    name.get(..value.len())
        .is_some_and(|s| s.eq_ignore_ascii_case(value))
}
fn hop(name: &str) -> bool {
    [
        "connection",
        "keep-alive",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    ]
    .iter()
    .any(|field| name.eq_ignore_ascii_case(field))
}
fn private_input(name: &str) -> bool {
    [
        "authorization",
        "proxy-authorization",
        "forwarded",
        "traceparent",
        "tracestate",
        "baggage",
        "x-real-ip",
        "remote-user",
        "x-remote-user",
        "x-original-url",
        "x-rewrite-url",
    ]
    .iter()
    .any(|field| name.eq_ignore_ascii_case(field))
        || prefix(name, "x-forwarded-")
        || prefix(name, "x-auth-request-")
        || prefix(name, "x-authenticated-")
}

fn field(header: HeaderView<'_>) -> Result<(), HttpError> {
    if header.name.is_empty()
        || header.name.len() > 64
        || !header.name.bytes().all(token)
        || header.value.len() > 4096
        || header.value.iter().any(|byte| *byte < 32 || *byte == 127)
        || header.value.first() == Some(&b' ')
        || header.value.last() == Some(&b' ')
        || hop(header.name)
        || prefix(header.name, "x-lsf-")
    {
        return Err(HttpError::InvalidHeaders);
    }
    Ok(())
}

fn preflight<'a>(headers: impl Iterator<Item = HeaderView<'a>>) -> Result<(), HttpError> {
    let mut count = 0;
    let mut bytes = 0_usize;
    for header in headers {
        count += 1;
        bytes = bytes
            .checked_add(header.name.len())
            .and_then(|v| v.checked_add(header.value.len()))
            .ok_or(HttpError::HeadersTooLarge)?;
        if count > MAX_HEADERS || bytes > MAX_HEADER_BYTES {
            return Err(HttpError::HeadersTooLarge);
        }
        field(header)?;
    }
    Ok(())
}

pub(super) fn request(head: &RawHead<'_>, method: Method) -> Result<RequestHeaders, HttpError> {
    // Complete validation precedes copying any field or allocating a body.
    preflight(head.headers.iter().copied())?;
    let mut host = None;
    let mut length = None;
    let mut media = None;
    let mut credential = false;
    for header in head.headers {
        let name = header.name;
        if name.eq_ignore_ascii_case("host") {
            if host.is_some() {
                return Err(HttpError::InvalidFraming);
            }
            let value = std::str::from_utf8(header.value).map_err(|_| HttpError::InvalidFraming)?;
            host = Some(canonical_authority(head.scheme, value)?);
        } else if name.eq_ignore_ascii_case("content-length") {
            if length.is_some() {
                return Err(HttpError::InvalidFraming);
            }
            let value = std::str::from_utf8(header.value).map_err(|_| HttpError::InvalidFraming)?;
            let value = super::bounded::decimal(value).ok_or(HttpError::InvalidFraming)?;
            if value > MAX_REQUEST_BODY as u64 {
                return Err(HttpError::BodyTooLarge);
            }
            length = Some(usize::try_from(value).map_err(|_| HttpError::BodyTooLarge)?);
        } else if name.eq_ignore_ascii_case("content-type") {
            if media.is_some() {
                return Err(HttpError::InvalidHeaders);
            }
            let value = std::str::from_utf8(header.value).map_err(|_| HttpError::InvalidHeaders)?;
            media_type(value)?;
            media = Some(value);
        } else if name.eq_ignore_ascii_case("authorization") {
            if credential {
                return Err(HttpError::InvalidHeaders);
            }
            credential = true;
        }
    }
    if (head.version == HttpVersion::Http11 && host.is_none())
        || host.is_some_and(|value| {
            canonical_authority(head.scheme, head.authority).as_ref() != Ok(&value)
        })
        || (matches!(method, Method::Get | Method::Head) && length.unwrap_or(0) != 0)
    {
        return Err(HttpError::InvalidFraming);
    }
    let fields = head
        .headers
        .iter()
        .filter(|header| {
            !["host", "content-length", "content-type"]
                .iter()
                .any(|s| header.name.eq_ignore_ascii_case(s))
                && !private_input(header.name)
        })
        .map(|header| Header {
            name: BoundedText(header.name.to_ascii_lowercase()),
            value: BoundedList(header.value.to_vec()),
        })
        .collect();
    Ok(RequestHeaders {
        fields,
        media: media.map(str::to_owned),
        length,
    })
}

pub(super) fn response(value: &ResponseData, method: Method) -> Result<(), HttpError> {
    preflight(value.headers.0.iter().map(Header::view))?;
    if !(200..=599).contains(&value.status) {
        return Err(HttpError::InvalidResponse);
    }
    for header in &value.headers.0 {
        let name = &header.name.0;
        if name.bytes().any(|b| b.is_ascii_uppercase())
            || private_input(name)
            || [
                "host",
                "content-length",
                "content-type",
                "server",
                "date",
                "via",
                "alt-svc",
            ]
            .iter()
            .any(|field| name == field)
        {
            return Err(HttpError::InvalidResponse);
        }
    }
    if let Some(media) = value.media_type.as_ref() {
        media_type(&media.0)?;
    }
    if (method == Method::Head || matches!(value.status, 204 | 205 | 304))
        && !value.body.0.is_empty()
    {
        return Err(HttpError::InvalidResponse);
    }
    if value.representation_length.as_ref().is_some()
        && ((method != Method::Head && value.status != 304) || matches!(value.status, 204 | 205))
    {
        return Err(HttpError::InvalidResponse);
    }
    Ok(())
}

/// A deliberately bounded MIME grammar: type/subtype and unique token or quoted
/// parameters. No commas, controls, obs-text, escapes or ambiguous duplicate keys.
pub(super) fn media_type(value: &str) -> Result<(), HttpError> {
    if value.len() > 256 || !value.is_ascii() {
        return Err(HttpError::InvalidHeaders);
    }
    let mut parts = value.split(';');
    let (kind, subtype) = parts
        .next()
        .unwrap_or("")
        .split_once('/')
        .ok_or(HttpError::InvalidHeaders)?;
    if [kind, subtype]
        .iter()
        .any(|v| v.is_empty() || !v.bytes().all(token))
    {
        return Err(HttpError::InvalidHeaders);
    }
    let mut names = [""; 16];
    for (index, parameter) in parts.enumerate() {
        let parameter = parameter.trim_start_matches(' ');
        let (name, value) = parameter.split_once('=').ok_or(HttpError::InvalidHeaders)?;
        if index == names.len()
            || name.is_empty()
            || !name.bytes().all(token)
            || names[..index].iter().any(|n| name.eq_ignore_ascii_case(n))
        {
            return Err(HttpError::InvalidHeaders);
        }
        names[index] = name;
        let valid = if let Some(quoted) = value.strip_prefix('"').and_then(|v| v.strip_suffix('"'))
        {
            quoted
                .bytes()
                .all(|b| (32..127).contains(&b) && !matches!(b, b'"' | b'\\' | b','))
        } else {
            !value.is_empty() && value.bytes().all(token)
        };
        if !valid {
            return Err(HttpError::InvalidHeaders);
        }
    }
    Ok(())
}
