use super::{HttpError, HttpResponse, PoolCall};
use crate::{headers, HttpLimits};
use http::HeaderMap;
use http_body_util::BodyExt;
use latent_capabilities::broker::io::IoBuffer;
use std::io::Read;

pub(super) fn validate(headers: &HeaderMap, limits: HttpLimits) -> Result<(), HttpError> {
    if headers.len() > limits.maximum_headers {
        return Err(HttpError::ResponseTooLarge);
    }
    let mut bytes = 0usize;
    for (name, value) in headers {
        bytes = bytes
            .checked_add(name.as_str().len() + value.as_bytes().len() + 4)
            .ok_or(HttpError::ResponseTooLarge)?;
        if bytes > limits.maximum_header_bytes {
            return Err(HttpError::ResponseTooLarge);
        }
        let text =
            std::str::from_utf8(value.as_bytes()).map_err(|_| HttpError::ConnectionFailed)?;
        if !headers::valid_name(name.as_str()) || !headers::valid_value(text) {
            return Err(HttpError::ConnectionFailed);
        }
    }
    if headers.get_all("content-length").iter().count() > 1
        || headers.get_all("transfer-encoding").iter().count() > 1
        || headers.contains_key("content-length") && headers.contains_key("transfer-encoding")
        || headers.get_all("content-encoding").iter().count() > 1
        || headers.get_all("content-type").iter().count() > 1
    {
        return Err(HttpError::ConnectionFailed);
    }
    if headers
        .get("transfer-encoding")
        .is_some_and(|v| v.as_bytes() != b"chunked")
    {
        return Err(HttpError::ConnectionFailed);
    }
    Ok(())
}
#[expect(
    clippy::too_many_lines,
    reason = "keep finite encoded, decoded and canonical output owners in one ordered scope"
)]
pub(super) async fn read(
    call: &PoolCall,
    connection: &mut crate::network::HttpConnection,
    mut response: http::Response<hyper::body::Incoming>,
    limits: HttpLimits,
    head: bool,
) -> Result<HttpResponse, HttpError> {
    let mut encoded = call
        .io()
        .buffer(limits.maximum_encoded_response_bytes, 1024)?;
    if !head && response.status().as_u16() != 204 && response.status().as_u16() != 304 {
        if let Some(length) = response.headers().get("content-length") {
            let length = length
                .to_str()
                .map_err(|_| HttpError::ConnectionFailed)?
                .parse::<u64>()
                .map_err(|_| HttpError::ConnectionFailed)?;
            if length > limits.maximum_encoded_response_bytes as u64 {
                return Err(HttpError::ResponseTooLarge);
            }
        }
    }
    let trailer_limits = HttpLimits {
        maximum_headers: limits
            .maximum_headers
            .checked_sub(response.headers().len())
            .ok_or(HttpError::ResponseTooLarge)?,
        maximum_header_bytes: limits
            .maximum_header_bytes
            .checked_sub(
                response
                    .headers()
                    .iter()
                    .map(|(n, v)| n.as_str().len() + v.as_bytes().len() + 4)
                    .sum(),
            )
            .ok_or(HttpError::ResponseTooLarge)?,
        ..limits
    };
    let mut trailers_seen = false;
    loop {
        let frame = call
            .io()
            .wait_for(crate::network::drive(
                &mut connection.driver,
                response.body_mut().frame(),
            ))
            .await??;
        let Some(frame) = frame else {
            break;
        };
        let frame = frame.map_err(|_| HttpError::ConnectionFailed)?;
        match frame.into_data() {
            Ok(data) => {
                if trailers_seen || data.len() > encoded.capacity() - encoded.bytes().len() {
                    return Err(HttpError::ResponseTooLarge);
                }
                encoded.spare_mut()?[..data.len()].copy_from_slice(&data);
                encoded.advance_written(data.len())?;
            }
            Err(frame) => {
                let trailers = frame
                    .into_trailers()
                    .map_err(|_| HttpError::ConnectionFailed)?;
                if trailers_seen {
                    return Err(HttpError::ConnectionFailed);
                }
                validate(&trailers, trailer_limits)?;
                if trailers
                    .keys()
                    .any(|n| headers::hop(n.as_str()) || headers::reserved(n.as_str()))
                {
                    return Err(HttpError::ConnectionFailed);
                }
                trailers_seen = true; // validated and dropped, never treated as authority
            }
        }
    }
    let encoding = response
        .headers()
        .get("content-encoding")
        .map_or(Ok("identity"), |v| {
            v.to_str().map_err(|_| HttpError::ConnectionFailed)
        })?;
    let mut decoded = call.io().buffer(limits.maximum_response_body_bytes, 1024)?;
    if head || matches!(response.status().as_u16(), 204 | 304) {
        if !encoded.bytes().is_empty() {
            return Err(HttpError::ConnectionFailed);
        }
    } else if encoding.eq_ignore_ascii_case("identity") {
        if encoded.bytes().len() > decoded.capacity() {
            return Err(HttpError::ResponseTooLarge);
        }
        let count = encoded.bytes().len();
        decoded.spare_mut()?[..count].copy_from_slice(encoded.bytes());
        decoded.advance_written(count)?;
    } else {
        // Both encoded and decoded storage are prepaid. The decoder only reads
        // that finite slice; no network read or unbounded read_to_end is hidden.
        let _window = call.io().reserve_scratch(64 * 1024, 512)?;
        match encoding {
            name if name.eq_ignore_ascii_case("gzip") => {
                // Optional gzip filename/comment fields may allocate up to the
                // already bounded encoded input size, independently of output.
                let _gzip_headers = call
                    .io()
                    .reserve_scratch(limits.maximum_encoded_response_bytes, 512)?;
                decode(
                    call,
                    &mut decoded,
                    flate2::bufread::MultiGzDecoder::new(encoded.bytes()),
                )
                .await?;
            }
            name if name.eq_ignore_ascii_case("deflate") => {
                let mut inflater = flate2::bufread::ZlibDecoder::new(encoded.bytes());
                decode(call, &mut decoded, &mut inflater).await?;
                if inflater.total_in() != encoded.bytes().len() as u64 {
                    return Err(HttpError::ConnectionFailed);
                }
            }
            _ => return Err(HttpError::ConnectionFailed),
        }
    }
    let mut output = call.io().buffer(limits.maximum_header_bytes, 1024)?;
    for (name, value) in response.headers() {
        if headers::hop(name.as_str())
            || name == "content-length"
            || name == "content-encoding"
            || connection_named(response.headers(), name.as_str())?
        {
            continue;
        }
        append(&mut output, name.as_str().as_bytes())?;
        append(&mut output, &[0])?;
        append(&mut output, value.as_bytes())?;
        append(&mut output, &[0])?;
    }
    HttpResponse::new(response.status().as_u16(), output, decoded)
}
async fn decode(
    call: &PoolCall,
    output: &mut IoBuffer,
    mut decoder: impl Read,
) -> Result<(), HttpError> {
    loop {
        call.io().checkpoint()?;
        let capacity = (output.capacity() - output.bytes().len()).min(8192);
        if capacity == 0 {
            let mut extra = [0];
            if decoder
                .read(&mut extra)
                .map_err(|_| HttpError::ConnectionFailed)?
                != 0
            {
                return Err(HttpError::ResponseTooLarge);
            }
            return Ok(());
        }
        let count = decoder
            .read(&mut output.spare_mut()?[..capacity])
            .map_err(|_| HttpError::ConnectionFailed)?;
        output.advance_written(count)?;
        if count == 0 {
            return Ok(());
        }
        tokio::task::yield_now().await;
    }
}
fn append(buffer: &mut IoBuffer, bytes: &[u8]) -> Result<(), HttpError> {
    if bytes.len() > buffer.capacity() - buffer.bytes().len() {
        return Err(HttpError::ResponseTooLarge);
    }
    buffer.spare_mut()?[..bytes.len()].copy_from_slice(bytes);
    buffer.advance_written(bytes.len())?;
    Ok(())
}
fn connection_named(headers: &HeaderMap, name: &str) -> Result<bool, HttpError> {
    let mut found = false;
    for value in headers.get_all("connection") {
        for token in value
            .to_str()
            .map_err(|_| HttpError::ConnectionFailed)?
            .split(',')
        {
            let token = token.trim();
            if !headers::valid_name(token) {
                return Err(HttpError::ConnectionFailed);
            }
            found |= name.eq_ignore_ascii_case(token);
        }
    }
    Ok(found)
}
