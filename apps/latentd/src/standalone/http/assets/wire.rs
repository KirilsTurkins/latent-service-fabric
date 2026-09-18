use super::{Prepared, Request};
use crate::standalone::http::{head::Head, millis, Shared};
use latent_core::IncomingDeadline;
use latent_wire::invocation::{LocalPrincipalPolicy, PrincipalPolicy};
use std::io;
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    time::{timeout_at, Instant},
};
use zeroize::Zeroize;

pub(in crate::standalone::http) async fn exchange<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    raw: &mut [u8],
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
    // Keep the existing ingress exchange owner, including error responses,
    // until writes/shutdown finish. No activation or renderer reservation exists.
    let result = prepare_request(&head, raw);
    raw.zeroize();
    let result = match result {
        Ok(request) => serve(socket, shared, request, deadline, close).await,
        Err(code) => Err(code),
    };
    let result = match result {
        Ok(close) => Ok(close),
        Err(0) => Err(0),
        Err(code) => {
            let until = Instant::from_std(deadline.monotonic())
                .min(Instant::now() + millis(shared.settings.limits.write_timeout_millis));
            let _ = timeout_at(until, rejection(socket, code)).await;
            let _ = timeout_at(until, socket.shutdown()).await;
            Ok(true)
        }
    };
    drop(head);
    result
}
fn prepare_request(head: &Head, raw: &[u8]) -> Result<Request, u16> {
    LocalPrincipalPolicy
        .authenticate(&head.principal)
        .map_err(super::status)?;
    let tenant = head.principal.tenant.as_ref().ok_or(403u16)?;
    LocalPrincipalPolicy
        .authorize_target(&head.principal, &tenant.0)
        .map_err(super::status)?;
    if head.content_length != 0 {
        return Err(400);
    }
    Request::parse(raw, tenant)
}
async fn serve<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    request: Request,
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
    let store = shared.handle.0.assets.get().ok_or(503u16)?;
    if !shared.handle.accepting() {
        return Err(503);
    }
    let tenant = request.reference.scope.tenant().ok_or(403u16)?.clone();
    let mut work = store.begin(request)?;
    let mut unexpected = [0u8; 1];
    let prepared = tokio::select! {
        biased;
        () = tokio::time::sleep_until(deadline.monotonic().into()) => return Err(0),
        // As for activation requests, EOF/write-half-close/pipelining cancels
        // delivery. The blocking closure still owns its physical work permit.
        _ = socket.read(&mut unexpected) => return Err(0),
        result = &mut work => result.map_err(|_| 503u16)??,
    };
    prepared.accept(&tenant)?;
    let close = close || !shared.handle.accepting();
    let until = Instant::from_std(deadline.monotonic())
        .min(Instant::now() + millis(shared.settings.limits.write_timeout_millis));
    let result = timeout_at(until, delivery(socket, &prepared, close)).await;
    if close || !matches!(&result, Ok(Ok(()))) {
        // In particular a TLS flush timeout does not drop the asset buffer's
        // output reservation before the bounded shutdown attempt completes.
        let _ = timeout_at(until, socket.shutdown()).await;
    }
    drop(prepared);
    result.map_err(|_| 0u16)?.map_err(|_| 0u16)?;
    Ok(close)
}
async fn delivery<W: AsyncWrite + Unpin>(
    socket: &mut W,
    response: &Prepared,
    close: bool,
) -> io::Result<()> {
    let mut head = format!(
        "HTTP/1.1 {} Response\r\nETag: {}\r\nCache-Control: private, max-age=31536000, immutable\r\nVary: Authorization, Accept-Encoding\r\nX-Content-Type-Options: nosniff\r\nAccept-Ranges: none\r\n",
        response.code, response.etag,
    );
    if close {
        head.push_str("Connection: close\r\n");
    }
    if response.code != 304 {
        use std::fmt::Write as _;
        write!(
            &mut head,
            "Content-Length: {}\r\nContent-Type: {}\r\n",
            response.buffer.bytes.len(),
            response.media
        )
        .map_err(|_| io::ErrorKind::InvalidData)?;
    }
    head.push_str("\r\n");
    if head.len() > 1024 {
        return Err(io::ErrorKind::InvalidData.into());
    }
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await?;
    if !response.request.head && response.code != 304 {
        for chunk in response.buffer.bytes.chunks(16 * 1024) {
            socket.write_all(chunk).await?;
            socket.flush().await?;
        }
    }
    Ok(())
}
async fn rejection<W: AsyncWrite + Unpin>(socket: &mut W, code: u16) -> io::Result<()> {
    let allow = if code == 405 {
        "Allow: GET, HEAD\r\n"
    } else {
        ""
    };
    let head = format!("HTTP/1.1 {code} Rejected\r\nConnection: close\r\nContent-Length: 0\r\nCache-Control: no-store\r\n{allow}\r\n");
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await
}
