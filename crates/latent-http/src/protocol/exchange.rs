use super::{
    Inner, ProtocolFailure, ProtocolRequest, ProtocolResponse, ProtocolScope,
    MAXIMUM_PROTOCOL_BODY_BYTES,
};
use crate::{headers, network, HttpError};
use http::{
    header::{HeaderName, HeaderValue},
    Request, Uri,
};
use http_body_util::BodyExt;
use std::sync::atomic::Ordering;

pub(super) async fn run(
    inner: &Inner,
    scope: ProtocolScope<'_>,
    request: ProtocolRequest,
    maximum: usize,
    consume: &mut (dyn FnMut(&[u8]) -> Result<(), HttpError> + Send),
) -> Result<ProtocolResponse, ProtocolFailure> {
    scope.checkpoint()?;
    if maximum > MAXIMUM_PROTOCOL_BODY_BYTES {
        return Err(HttpError::InvalidRequest.into());
    }
    let response_memory = inner
        .pools
        .reserve_protocol_metadata(2 * inner.config.limits.maximum_header_bytes + 32768)
        .map_err(HttpError::from)?;
    let _request_memory = inner
        .pools
        .reserve_protocol_metadata(65536)
        .map_err(HttpError::from)?;
    let request = build(inner, request)?;
    let mut connection = network::connect_for(
        &inner.pools,
        &inner.client,
        scope,
        &inner.config.destinations[0],
        &inner.answers,
        &inner.tls,
        inner.config.limits.maximum_headers,
    )
    .await?;
    let network::Network::Http(connection) = connection.resource() else {
        return Err(HttpError::ConnectionFailed.into());
    };
    connection.wrote.store(false, Ordering::Release);
    let sender = &mut connection.sender;
    let future = async {
        let response = sender
            .send_request(request)
            .await
            .map_err(|_| HttpError::ConnectionFailed)?;
        let status = response.status().as_u16();
        let mut headers = Vec::with_capacity(response.headers().len());
        let mut size = 0usize;
        if response.headers().len() > inner.config.limits.maximum_headers {
            return Err(HttpError::ResponseTooLarge);
        }
        for (name, value) in response.headers() {
            size = size
                .checked_add(name.as_str().len() + value.len() + 4)
                .ok_or(HttpError::ResponseTooLarge)?;
            if size > inner.config.limits.maximum_header_bytes {
                return Err(HttpError::ResponseTooLarge);
            }
            let value =
                std::str::from_utf8(value.as_bytes()).map_err(|_| HttpError::ConnectionFailed)?;
            headers.push((name.as_str().to_owned(), value.to_owned()));
        }
        let mut body = response.into_body();
        let mut count = 0usize;
        let mut frames = 0usize;
        while let Some(frame) = body.frame().await {
            scope.checkpoint()?;
            frames += 1;
            if frames > 65536 {
                return Err(HttpError::ResponseTooLarge);
            }
            let frame = frame.map_err(|_| HttpError::ConnectionFailed)?;
            let bytes = frame.into_data().map_err(|_| HttpError::ConnectionFailed)?;
            count = count
                .checked_add(bytes.len())
                .ok_or(HttpError::ResponseTooLarge)?;
            if count > maximum {
                return Err(HttpError::ResponseTooLarge);
            }
            consume(&bytes)?;
        }
        scope.checkpoint()?;
        Ok(ProtocolResponse {
            status,
            headers,
            body_bytes: count,
            _metadata: response_memory,
        })
    };
    let result = scope
        .wait(network::drive(&mut connection.driver, future))
        .await
        .and_then(|r| r)
        .and_then(|r| r);
    let started = connection.wrote.load(Ordering::Acquire);
    // The protocol profile closes each physical connection after its response.
    // No waiter or remote side effect is mistaken for an idle client resource.
    result.map_err(|error| ProtocolFailure {
        error,
        request_started: started,
    })
}

fn build(
    inner: &Inner,
    request: ProtocolRequest,
) -> Result<Request<crate::streaming::wire::RequestBody>, HttpError> {
    if request.method.capacity() > 16
        || request.path_and_query.capacity() > 8192
        || request.headers.capacity() > 32
        || !request.path_and_query.starts_with('/')
        || request.path_and_query.starts_with("//")
        || request.path_and_query.contains('#')
        || !matches!(
            request.method.as_str(),
            "GET" | "HEAD" | "PUT" | "POST" | "DELETE"
        )
    {
        return Err(HttpError::InvalidRequest);
    }
    let uri = request
        .path_and_query
        .parse::<Uri>()
        .map_err(|_| HttpError::InvalidUrl)?;
    if uri.scheme().is_some() || uri.authority().is_some() {
        return Err(HttpError::InvalidUrl);
    }
    let mut result = Request::new(crate::streaming::wire::RequestBody::Protocol(request.body));
    *result.uri_mut() = uri;
    *result.method_mut() = request
        .method
        .parse()
        .map_err(|_| HttpError::InvalidRequest)?;
    let mut size = 0usize;
    for header in request.headers {
        if header.name.capacity() > 64
            || header.value.capacity() > 8192
            || !headers::valid_name(&header.name)
            || !headers::valid_value(&header.value)
            || headers::hop(&header.name)
            || header.name.eq_ignore_ascii_case("content-length")
        {
            return Err(HttpError::InvalidRequest);
        }
        size = size
            .checked_add(header.name.len() + header.value.len() + 4)
            .ok_or(HttpError::RequestTooLarge)?;
        if size > inner.config.limits.maximum_header_bytes
            || result.headers().len() >= inner.config.limits.maximum_headers - 1
        {
            return Err(HttpError::RequestTooLarge);
        }
        let name = HeaderName::from_bytes(header.name.as_bytes())
            .map_err(|_| HttpError::InvalidRequest)?;
        let mut value =
            HeaderValue::from_str(&header.value).map_err(|_| HttpError::InvalidRequest)?;
        value.set_sensitive(header.sensitive);
        if result.headers_mut().insert(name, value).is_some() {
            return Err(HttpError::InvalidRequest);
        }
    }
    // The signature must cover the exact host actually used by this transport.
    let origin = &inner.config.destinations[0].origin;
    let host = if origin.host.contains(':') {
        format!("[{}]:{}", origin.host, origin.port)
    } else {
        format!("{}:{}", origin.host, origin.port)
    };
    if result
        .headers()
        .get("host")
        .is_none_or(|h| h.as_bytes() != host.as_bytes())
    {
        return Err(HttpError::InvalidRequest);
    }
    let crate::streaming::wire::RequestBody::Protocol(body) = result.body() else {
        unreachable!()
    };
    let length = body.length().to_string();
    if size + length.len() + 18 > inner.config.limits.maximum_header_bytes {
        return Err(HttpError::RequestTooLarge);
    }
    result.headers_mut().insert(
        "content-length",
        HeaderValue::from_str(&length).map_err(|_| HttpError::InvalidRequest)?,
    );
    Ok(result)
}
