use super::{Arc, Destination, HttpError, HttpRequest, Inner, IoMemory};
use crate::{credentials, headers};
use http::{
    header::{HeaderName, HeaderValue},
    Request, Uri,
};
use http_body_util::Full;
use latent_capabilities::broker::CapabilityRequestDigest;

pub(super) fn digest(
    request: &HttpRequest,
    destination: &Destination,
) -> Result<CapabilityRequestDigest, HttpError> {
    let mut parts = Vec::with_capacity(8 + request.headers.len() * 2);
    parts.push(request.method.as_str().as_bytes());
    parts.push(destination.url.as_str().as_bytes());
    parts.push(request.body.as_deref().unwrap_or_default());
    parts.push(
        request
            .body_media_type
            .as_deref()
            .unwrap_or_default()
            .as_bytes(),
    );
    parts.push(
        request
            .idempotency_key
            .as_deref()
            .unwrap_or_default()
            .as_bytes(),
    );
    for header in &request.headers {
        parts.push(header.name.as_bytes());
        parts.push(header.value.as_bytes());
    }
    CapabilityRequestDigest::from_parts(&parts).map_err(Into::into)
}
pub(super) fn build(
    inner: &Inner,
    request: &mut HttpRequest,
    destination: &Destination,
    memory: Arc<IoMemory>,
    credentials_allowed: bool,
) -> Result<Request<Full<bytes::Bytes>>, HttpError> {
    let path = &destination.url[url::Position::BeforePath..url::Position::AfterQuery];
    let uri = path.parse::<Uri>().map_err(|_| HttpError::InvalidUrl)?;
    let mut result = Request::new(Full::new(bytes::Bytes::from_owner(
        crate::network::OwnedRequestBody {
            bytes: request.body.take().unwrap_or_default(),
            _memory: memory,
        },
    )));
    *result.method_mut() = request
        .method
        .as_str()
        .parse()
        .map_err(|_| HttpError::InvalidRequest)?;
    *result.uri_mut() = uri;
    *result.version_mut() = http::Version::HTTP_11;
    let length = http_body::Body::size_hint(result.body())
        .exact()
        .ok_or(HttpError::InvalidRequest)?;
    let mut count = 0usize;
    let mut bytes = 0usize;
    let mut add = |name: &str, value: &str, sensitive| -> Result<(), HttpError> {
        count += 1;
        bytes = bytes
            .checked_add(name.len() + value.len() + 4)
            .ok_or(HttpError::RequestTooLarge)?;
        if count > inner.config.limits.maximum_headers
            || bytes > inner.config.limits.maximum_header_bytes
        {
            return Err(HttpError::RequestTooLarge);
        }
        let name =
            HeaderName::from_bytes(name.as_bytes()).map_err(|_| HttpError::InvalidRequest)?;
        let mut value = HeaderValue::from_str(value).map_err(|_| HttpError::InvalidRequest)?;
        value.set_sensitive(sensitive);
        if result.headers_mut().insert(name, value).is_some() {
            return Err(HttpError::InvalidRequest);
        }
        Ok(())
    };
    let authority = &destination.url[url::Position::BeforeHost..url::Position::AfterPort];
    add("host", authority, false)?;
    // Known body length prevents implicit Transfer-Encoding or framing inference.
    add("content-length", &length.to_string(), false)?;
    add("accept-encoding", "gzip, deflate", false)?;
    for header in &request.headers {
        add(&header.name, &header.value, false)?;
    }
    if let Some(value) = &request.body_media_type {
        add("content-type", value, false)?;
    }
    if let Some(value) = &request.idempotency_key {
        add("idempotency-key", value, true)?;
    }
    if credentials_allowed {
        inner.installed.with_credentials(|encoded| {
            for (index, name, value) in credentials::entries(encoded) {
                if index == destination.index {
                    add(name, value, true)?;
                }
            }
            Ok::<_, HttpError>(())
        })?;
    }
    // Generated fields and configured credentials use the same closed grammar.
    if result.headers().iter().any(|(name, value)| {
        !headers::valid_name(name.as_str()) || std::str::from_utf8(value.as_bytes()).is_err()
    }) {
        return Err(HttpError::InvalidRequest);
    }
    Ok(result)
}
