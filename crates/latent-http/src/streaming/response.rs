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
    http::{HttpHeaderBlock, HttpResponseHead},
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
    phase_failure: Option<latent_capabilities::broker::streaming_http::HttpPhaseError>,
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
        let Network::Http(connection) = exchange
            .socket
            .as_mut()
            .ok_or(Error::InvalidState)?
            .resource()
        else {
            return Err(Error::InvalidState);
        };
        // Move the original prepaid raw buffer into the head. Hyper's parsed
        // ReasonPhrase is lossy for obs-text and is never a source substitute.
        connection.take_reason(reply.version(), reply.status().as_u16())?
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
        phase_failure: None,
    })
}
#[cfg(test)]
mod reason_tests {
    use super::*;
    use latent_capabilities::broker::http::MAXIMUM_HTTP_REASON_BYTES;

    #[tokio::test]
    async fn actual_http1_parser_preserves_canonical_custom_empty_and_non_ascii_reason_bytes() {
        for (status, expected) in [
            (&b"200 OK"[..], &b"OK"[..]),
            (&b"200 Custom phrase"[..], &b"Custom phrase"[..]),
            (&b"299 "[..], &b""[..]),
            (&b"200 Caf\xc3\xa9"[..], &b"Caf\xc3\xa9"[..]),
            (&b"200 Caf\xe9"[..], &b"Caf\xe9"[..]),
        ] {
            let mut wire = b"HTTP/1.1 ".to_vec();
            wire.extend_from_slice(status);
            wire.extend_from_slice(b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
            let reason = crate::tests::captured_wire_reason(&wire, true)
                .await
                .unwrap();
            assert_eq!(reason.as_deref(), Some(expected));
            assert_eq!(
                crate::tests::captured_wire_reason(&wire, false)
                    .await
                    .unwrap(),
                None
            );
        }
    }

    #[tokio::test]
    async fn actual_http1_oversize_reason_refuses_and_other_protocol_metadata_stays_unavailable() {
        let mut wire = b"HTTP/1.1 200 ".to_vec();
        wire.extend(std::iter::repeat_n(b'x', MAXIMUM_HTTP_REASON_BYTES + 1));
        wire.extend_from_slice(b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        assert!(matches!(
            crate::tests::captured_wire_reason(&wire, true).await,
            Err(Error::Http(HttpError::ResponseTooLarge))
        ));
        assert!(!crate::reason::supports_version(http::Version::HTTP_2));
        assert!(!crate::reason::supports_version(http::Version::HTTP_3));
        assert!(!crate::reason::supports_version(http::Version::HTTP_09));
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
    fn read_with_timeout(
        &mut self,
        maximum_bytes: usize,
        timeout_millis: Option<u32>,
    ) -> BoxFuture<
        '_,
        Result<Option<IoOutputChunk>, latent_capabilities::broker::streaming_http::HttpPhaseError>,
    > {
        use latent_capabilities::broker::streaming_http::HttpPhaseError;
        if let Err(error) = self.exchange.call.io().checkpoint() {
            return Box::pin(async move { Err(error.into()) });
        }
        if let Some(error) = self.phase_failure {
            return Box::pin(async move { Err(error) });
        }
        if timeout_millis.is_none_or(|millis| millis == 0) {
            return Box::pin(async move { self.next(maximum_bytes).await.map_err(Into::into) });
        }
        if !self.exchange.inner.phase_timing {
            return Box::pin(async { Err(HttpPhaseError::Unsupported) });
        }
        let deadline = match super::phase::Deadline::new(
            self.exchange.call.io().stop_handle(),
            timeout_millis,
        ) {
            Ok(deadline) => deadline,
            Err(error) => return Box::pin(async move { Err(error) }),
        };
        Box::pin(async move {
            match deadline
                .wait(
                    self.next(maximum_bytes),
                    HttpPhaseError::ReadTimeout {
                        external_completion_uncertain: false,
                    },
                )
                .await
            {
                Ok(result) => result.map_err(Into::into),
                Err(error) => {
                    // The borrowed read future has been destroyed. Close its
                    // actual transport before reporting any phase failure;
                    // retained chunks/body metadata keep their original charges.
                    self.phase_failure = Some(error);
                    // A retired phase stream is invalid for the legacy API;
                    // do not manufacture an original activation deadline.
                    self.failed = Some(Error::InvalidState);
                    self.pending = Bytes::new();
                    self.exchange.socket = None;
                    self.exchange.terminal_audit().await;
                    // Audit completion is an async boundary too. An original
                    // root stop during retirement still wins before reporting.
                    self.exchange.call.io().checkpoint()?;
                    Err(error)
                }
            }
        })
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
