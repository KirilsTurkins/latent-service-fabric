use super::exchange::Exchange;
use crate::{
    execute::response::{append, connection_named, validate},
    headers,
    network::{self, Network},
    HttpError, HttpLimits,
};
use bytes::{Buf, Bytes};
use http::HeaderMap;
use http_body_util::BodyExt;
use latent_capabilities::broker::{
    http::{HttpHeaderBlock, HttpResponseHead, MAXIMUM_HTTP_REASON_BYTES},
    io::IoOutputChunk,
    streaming_http::{HttpBody, StreamingHttpError as Error},
};
use latent_core::BoxFuture;
use std::{sync::Arc, task::Poll};
/// One bounded Hyper frame may be retained in addition to the explicit guest
/// window. Its backing allocation remains covered by the owned protocol reserve.
pub(super) struct Body {
    pending: Bytes,
    incoming: hyper::body::Incoming,
    head: HttpResponseHead,
    trailers: Option<HttpHeaderBlock>,
    exchange: Exchange,
    expected: Option<u64>,
    received: u64,
    trailer_limits: HttpLimits,
    trailers_seen: bool,
    eof: bool,
    failed: Option<Error>,
}
pub(super) fn begin(mut exchange: Exchange, capture_reason: bool) -> Result<Body, Error> {
    let reply = exchange.response.take().ok_or(Error::InvalidState)?;
    let limits = exchange.inner.config.limits;
    validate(reply.headers(), limits)?;
    let bodyless = exchange.head || matches!(reply.status().as_u16(), 204 | 304);
    if !bodyless
        && reply
            .headers()
            .get("content-encoding")
            .is_some_and(|v| !v.as_bytes().eq_ignore_ascii_case(b"identity"))
    {
        return Err(Error::UnsupportedEncoding);
    }
    let expected = if bodyless {
        Some(0)
    } else {
        reply
            .headers()
            .get("content-length")
            .map(|value| {
                value
                    .to_str()
                    .ok()
                    .and_then(|s| s.parse::<u64>().ok())
                    .ok_or(HttpError::ConnectionFailed)
            })
            .transpose()?
    };
    if expected.is_some_and(|n| {
        n > exchange
            .inner
            .streaming
            .expect("stream limits")
            .maximum_output_bytes
    }) {
        return Err(HttpError::ResponseTooLarge.into());
    }
    let trailer_limits = HttpLimits {
        maximum_headers: limits.maximum_headers - reply.headers().len(),
        maximum_header_bytes: limits.maximum_header_bytes
            - reply
                .headers()
                .iter()
                .map(|(n, v)| n.as_str().len() + v.as_bytes().len() + 4)
                .sum::<usize>(),
        ..limits
    };
    let mut buffer = exchange
        .call
        .io()
        .buffer(limits.maximum_header_bytes, 512)?;
    copy_headers(reply.headers(), &mut buffer, false)?;
    let reason_phrase = if capture_reason {
        match wire_reason_phrase(&reply)? {
            Some(bytes) => {
                let mut reason = exchange.call.io().buffer(MAXIMUM_HTTP_REASON_BYTES, 128)?;
                reason.spare_mut()?[..bytes.len()].copy_from_slice(bytes);
                reason.advance_written(bytes.len())?;
                Some(reason)
            }
            None => None,
        }
    } else {
        None
    };
    let head =
        HttpResponseHead::with_reason_phrase(reply.status().as_u16(), buffer, reason_phrase)?;
    Ok(Body {
        pending: Bytes::new(),
        incoming: reply.into_body(),
        head,
        trailers: None,
        exchange,
        expected,
        received: 0,
        trailer_limits,
        trailers_seen: false,
        eof: false,
        failed: None,
    })
}
fn wire_reason_phrase<T>(reply: &http::Response<T>) -> Result<Option<&[u8]>, HttpError> {
    if !matches!(
        reply.version(),
        http::Version::HTTP_10 | http::Version::HTTP_11
    ) {
        return Ok(None);
    }
    // Pinned Hyper1.11.1 stores every noncanonical HTTP/1 phrase, including
    // empty and obs-text, in this extension. Absence means the wire phrase
    // exactly equaled canonical_reason(); never infer one for other protocols.
    let bytes = reply
        .extensions()
        .get::<hyper::ext::ReasonPhrase>()
        .map(hyper::ext::ReasonPhrase::as_bytes)
        .or_else(|| reply.status().canonical_reason().map(str::as_bytes));
    if bytes.is_some_and(|value| value.len() > MAXIMUM_HTTP_REASON_BYTES) {
        return Err(HttpError::ResponseTooLarge);
    }
    Ok(bytes)
}

#[cfg(test)]
mod reason_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    async fn parsed(wire: &[u8]) -> http::Response<hyper::body::Incoming> {
        let (client, mut server) = tokio::io::duplex(4096);
        let wire = wire.to_vec();
        let peer = tokio::spawn(async move {
            let mut input = [0; 4096];
            server.read(&mut input).await.unwrap();
            server.write_all(&wire).await.unwrap();
        });
        let (mut sender, driver) =
            hyper::client::conn::http1::handshake(hyper_util::rt::TokioIo::new(client))
                .await
                .unwrap();
        let driver = tokio::spawn(async move { driver.await.unwrap() });
        let response = sender
            .send_request(
                http::Request::builder()
                    .uri("/")
                    .header("host", "reason.fixture.invalid")
                    .body(http_body_util::Empty::<Bytes>::new())
                    .unwrap(),
            )
            .await
            .unwrap();
        drop(sender);
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            peer.await.unwrap();
            driver.await.unwrap();
        })
        .await
        .unwrap();
        response
    }

    #[tokio::test]
    async fn actual_http1_parser_preserves_canonical_custom_empty_and_non_ascii_reason_bytes() {
        for (status, expected) in [
            (&b"200 OK"[..], &b"OK"[..]),
            (&b"200 Custom phrase"[..], &b"Custom phrase"[..]),
            (&b"299 "[..], &b""[..]),
            (&b"200 Caf\xc3\xa9"[..], &b"Caf\xc3\xa9"[..]),
        ] {
            let mut wire = b"HTTP/1.1 ".to_vec();
            wire.extend_from_slice(status);
            wire.extend_from_slice(b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
            let response = parsed(&wire).await;
            assert_eq!(wire_reason_phrase(&response).unwrap(), Some(expected));
        }
    }

    #[tokio::test]
    async fn actual_http1_oversize_reason_refuses_and_other_protocol_metadata_stays_unavailable() {
        let mut wire = b"HTTP/1.1 200 ".to_vec();
        wire.extend(std::iter::repeat_n(b'x', MAXIMUM_HTTP_REASON_BYTES + 1));
        wire.extend_from_slice(b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        let response = parsed(&wire).await;
        assert!(matches!(
            wire_reason_phrase(&response),
            Err(HttpError::ResponseTooLarge)
        ));
        let response = http::Response::builder()
            .version(http::Version::HTTP_2)
            .body(())
            .unwrap();
        assert_eq!(wire_reason_phrase(&response).unwrap(), None);
    }
}
fn copy_headers(
    headers: &HeaderMap,
    target: &mut latent_capabilities::broker::io::IoBuffer,
    trailers: bool,
) -> Result<(), HttpError> {
    for (name, value) in headers {
        if trailers && (headers::hop(name.as_str()) || headers::reserved(name.as_str())) {
            return Err(HttpError::ConnectionFailed);
        }
        if !trailers && (headers::hop(name.as_str()) || connection_named(headers, name.as_str())?) {
            continue;
        }
        append(target, name.as_str().as_bytes())?;
        append(target, &[0])?;
        append(target, value.as_bytes())?;
        append(target, &[0])?;
    }
    Ok(())
}
impl Body {
    async fn next(&mut self, maximum: usize) -> Result<Option<IoOutputChunk>, Error> {
        self.exchange.call.io().checkpoint()?;
        if let Some(error) = self.failed {
            return Err(error);
        }
        if self.eof {
            return Ok(None);
        }
        // Reserve before transport work. A capacity rejection is retryable after
        // guest chunk Drop and must neither poll the socket nor poison framing.
        let mut chunk = self.exchange.transfer.output_buffer(maximum)?;
        let result = async {
            loop {
                if !self.pending.is_empty() {
                    let n = maximum.min(self.pending.len());
                    chunk.spare_mut()?[..n].copy_from_slice(&self.pending[..n]);
                    chunk.advance_written(n)?;
                    self.pending.advance(n);
                    if self.pending.is_empty() {
                        self.pending = Bytes::new();
                    }
                    return chunk.finish().map(Some).map_err(Into::into);
                }
                let connection = match self
                    .exchange
                    .socket
                    .as_mut()
                    .ok_or(Error::InvalidState)?
                    .resource()
                {
                    Network::Http(c) => c,
                    Network::Dns(_) => unreachable!("HTTP"),
                };
                let frame = self
                    .exchange
                    .call
                    .io()
                    .wait_for(network::drive(
                        &mut connection.driver,
                        self.incoming.frame(),
                    ))
                    .await??;
                let Some(frame) = frame else {
                    if self.expected.is_some_and(|n| n != self.received) {
                        return Err(Error::UnexpectedEof);
                    }
                    if self.trailers.is_none() {
                        let empty = self.exchange.call.io().buffer(1, 512)?;
                        self.trailers = Some(HttpHeaderBlock::new(empty)?);
                    }
                    self.eof = true;
                    drop(chunk);
                    self.complete().await;
                    return Ok(None);
                };
                let frame = frame.map_err(|_| Error::UnexpectedEof)?;
                match frame.into_data() {
                    Ok(data) => {
                        self.accept_data(data)?;
                    }
                    Err(frame) => {
                        let trailers = frame
                            .into_trailers()
                            .map_err(|_| HttpError::ConnectionFailed)?;
                        if self.trailers_seen {
                            return Err(HttpError::ConnectionFailed.into());
                        }
                        validate(&trailers, self.trailer_limits)?;
                        let mut buffer = self
                            .exchange
                            .call
                            .io()
                            .buffer(self.trailer_limits.maximum_header_bytes.max(1), 512)?;
                        copy_headers(&trailers, &mut buffer, true)?;
                        self.trailers = Some(HttpHeaderBlock::new(buffer)?);
                        self.trailers_seen = true;
                    }
                }
            }
        }
        .await;
        if let Err(error) = result {
            self.failed = Some(error);
            self.pending = Bytes::new();
            self.exchange.socket = None;
            self.exchange.terminal_audit().await;
        }
        result
    }
    fn accept_data(&mut self, data: Bytes) -> Result<(), Error> {
        if self.trailers_seen {
            return Err(HttpError::ConnectionFailed.into());
        }
        // Defensive validation of the pinned Hyper 32 KiB read-buffer profile.
        if data.len() > 32768 {
            return Err(HttpError::ResponseTooLarge.into());
        }
        self.received = self
            .received
            .checked_add(data.len() as u64)
            .ok_or(HttpError::ResponseTooLarge)?;
        if self.received
            > self
                .exchange
                .inner
                .streaming
                .expect("stream limits")
                .maximum_output_bytes
            || self.expected.is_some_and(|n| self.received > n)
        {
            return Err(HttpError::ResponseTooLarge.into());
        }
        self.pending = data;
        Ok(())
    }
    async fn complete(&mut self) {
        // An idle entry must retain no activation input/transfer reference.
        // Retained chunks conservatively prevent reuse of this physical socket.
        if let Some(mut socket) = self.exchange.socket.take() {
            let Network::Http(connection) = socket.resource() else {
                unreachable!("HTTP")
            };
            let ready =
                std::future::poll_fn(|cx| Poll::Ready(connection.sender.poll_ready(cx))).await;
            if matches!(ready, Poll::Ready(Ok(())))
                && connection.driver.is_some()
                && self.exchange.transfer.outstanding_chunks() == 0
                && self
                    .exchange
                    .input
                    .as_ref()
                    .is_some_and(|m| Arc::strong_count(m) == 2)
            {
                connection.input = None;
                self.exchange.input = None;
                let _ = socket.park();
            }
        }
        self.exchange.terminal_audit().await;
    }
}
impl HttpBody for Body {
    fn head(&self) -> &HttpResponseHead {
        &self.head
    }
    fn read(
        &mut self,
        maximum_bytes: usize,
    ) -> BoxFuture<'_, Result<Option<IoOutputChunk>, Error>> {
        Box::pin(self.next(maximum_bytes))
    }
    fn trailers(&self) -> Result<&HttpHeaderBlock, Error> {
        self.exchange.call.io().checkpoint()?;
        if let Some(error) = self.failed {
            return Err(error);
        }
        if !self.eof {
            return Err(Error::InvalidState);
        }
        self.trailers.as_ref().ok_or(Error::InvalidState)
    }
}
