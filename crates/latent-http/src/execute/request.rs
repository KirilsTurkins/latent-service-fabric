use super::{Arc, Destination, HttpError, HttpRequest, Inner, IoMemory};
use crate::{credentials, headers};
use http::{
    header::{HeaderName, HeaderValue},
    Request, Uri,
};
use http_body_util::Full;
use latent_capabilities::broker::CapabilityRequestDigest;

pub(crate) fn digest(
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
pub(crate) fn build(
    inner: &Inner,
    request: &mut HttpRequest,
    destination: &Destination,
    memory: Arc<IoMemory>,
    credentials_allowed: bool,
) -> Result<Request<crate::streaming::wire::RequestBody>, HttpError> {
    let body = crate::streaming::wire::RequestBody::Buffered(Full::new(bytes::Bytes::from_owner(
        crate::network::OwnedRequestBody {
            bytes: request.body.take().unwrap_or_default(),
            _memory: memory,
        },
    )));
    let length = http_body::Body::size_hint(&body).exact();
    build_with_body(
        inner,
        request,
        destination,
        body,
        length,
        "gzip, deflate",
        credentials_allowed,
    )
}
pub(crate) fn build_with_body(
    inner: &Inner,
    request: &HttpRequest,
    destination: &Destination,
    body: crate::streaming::wire::RequestBody,
    length: Option<u64>,
    encoding: &str,
    credentials_allowed: bool,
) -> Result<Request<crate::streaming::wire::RequestBody>, HttpError> {
    let path = &destination.url[url::Position::BeforePath..url::Position::AfterQuery];
    let uri = path.parse::<Uri>().map_err(|_| HttpError::InvalidUrl)?;
    let mut result = Request::new(body);
    *result.method_mut() = request
        .method
        .as_str()
        .parse()
        .map_err(|_| HttpError::InvalidRequest)?;
    *result.uri_mut() = uri;
    *result.version_mut() = http::Version::HTTP_11;
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
    if let Some(length) = length {
        add("content-length", &length.to_string(), false)?;
    } else {
        add("transfer-encoding", "chunked", false)?;
    }
    add("accept-encoding", encoding, false)?;
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
    if credentials_allowed {
        for reference in &inner.credential_references {
            if reference.destination == destination.index {
                reference
                    .binding
                    .with_current_value(&mut |bytes| {
                        if bytes.is_empty() || bytes.len() > 4096 {
                            return Err(
                                latent_capabilities::broker::secrets::SecretError::Unavailable,
                            );
                        }
                        let text = std::str::from_utf8(bytes).map_err(|_| {
                            latent_capabilities::broker::secrets::SecretError::Unavailable
                        })?;
                        if !headers::valid_value(text) {
                            return Err(
                                latent_capabilities::broker::secrets::SecretError::Unavailable,
                            );
                        }
                        add(&reference.name, text, true).map_err(|_| {
                            latent_capabilities::broker::secrets::SecretError::Unavailable
                        })
                    })
                    .map_err(|_| HttpError::PermissionDenied)?;
            }
        }
    }
    // Generated fields and configured credentials use the same closed grammar.
    if result.headers().iter().any(|(name, value)| {
        !headers::valid_name(name.as_str()) || std::str::from_utf8(value.as_bytes()).is_err()
    }) {
        return Err(HttpError::InvalidRequest);
    }
    Ok(result)
}
