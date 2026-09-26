use crate::{HttpDestination, HttpError, HttpLimits};
use latent_capabilities::broker::http::HttpRequest;

pub(crate) fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
}
pub(crate) fn valid_value(value: &str) -> bool {
    value.bytes().all(|b| b >= 32 && b != 127 || b == 9)
}
pub(crate) fn hop(name: &str) -> bool {
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    ]
    .iter()
    .any(|h| name.eq_ignore_ascii_case(h))
}
pub(crate) fn reserved(name: &str) -> bool {
    hop(name)
        || [
            "host",
            "content-length",
            "content-type",
            "content-encoding",
            "accept-encoding",
            "authorization",
            "cookie",
            "set-cookie",
            "expect",
            "idempotency-key",
            "x-api-key",
            "x-auth-token",
            "x-amz-security-token",
        ]
        .iter()
        .any(|h| name.eq_ignore_ascii_case(h))
}
pub(crate) struct InputSize {
    pub logical: usize,
    pub retained: usize,
}
pub(crate) fn validate(
    request: &HttpRequest,
    destination: &HttpDestination,
    limits: HttpLimits,
) -> Result<InputSize, HttpError> {
    if request.headers.len() > limits.maximum_headers
        || request.headers.capacity() > 64
        || request.body.as_ref().is_some_and(|b| {
            b.len() > limits.maximum_request_body_bytes
                || b.capacity() > limits.maximum_request_body_bytes
        })
        || request.url.capacity() > 2048
    {
        return Err(HttpError::RequestTooLarge);
    }
    let mut bytes = 0usize;
    let mut retained = request.url.capacity()
        + request.headers.capacity()
            * std::mem::size_of::<latent_capabilities::broker::http::HttpHeader>()
        + 1024;
    for (i, header) in request.headers.iter().enumerate() {
        if header.name.capacity() > 64 || header.value.capacity() > limits.maximum_header_bytes {
            return Err(HttpError::RequestTooLarge);
        }
        if !valid_name(&header.name)
            || !valid_value(&header.value)
            || reserved(&header.name)
            || !destination
                .allowed_request_headers
                .iter()
                .any(|h| header.name.eq_ignore_ascii_case(h))
            || request.headers[..i]
                .iter()
                .any(|h| h.name.eq_ignore_ascii_case(&header.name))
        {
            return Err(HttpError::InvalidRequest);
        }
        bytes = bytes
            .checked_add(header.name.len() + header.value.len() + 4)
            .ok_or(HttpError::RequestTooLarge)?;
        retained = retained
            .checked_add(header.name.capacity())
            .and_then(|n| n.checked_add(header.value.capacity()))
            .ok_or(HttpError::RequestTooLarge)?;
        if bytes > limits.maximum_header_bytes || retained > 2 * limits.maximum_header_bytes + 4096
        {
            return Err(HttpError::RequestTooLarge);
        }
    }
    for value in [
        request.body_media_type.as_ref(),
        request.idempotency_key.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        if value.is_empty() || value.len() > 256 || value.capacity() > 256 || !valid_value(value) {
            return Err(HttpError::InvalidRequest);
        }
        retained += value.capacity();
        bytes += value.len() + 32;
    }
    if bytes > limits.maximum_header_bytes {
        return Err(HttpError::RequestTooLarge);
    }
    let body = request.body.as_ref().map_or(0, Vec::len);
    retained += request.body.as_ref().map_or(0, Vec::capacity);
    Ok(InputSize {
        logical: request.url.len() + bytes + body,
        retained,
    })
}
