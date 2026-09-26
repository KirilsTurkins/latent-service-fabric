use super::{Prepared, Request};
use crate::standalone::http::{head::Head, millis, Shared};
use latent_core::IncomingDeadline;
use latent_ingress::http::{browser, Scheme};
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
    exchange_prepared(socket, shared, head, result, deadline, close).await
}

pub(in crate::standalone::http) async fn exchange_routed<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    raw: &mut [u8],
    deadline: IncomingDeadline,
    close: bool,
    request: Request,
) -> Result<bool, u16> {
    raw.zeroize();
    exchange_prepared(socket, shared, head, Ok(request), deadline, close).await
}

pub(in crate::standalone::http) async fn exchange_static<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    raw: &mut [u8],
    deadline: IncomingDeadline,
    close: bool,
    selected: latent_control_store::http_routes::AcceptedHttpRoute,
) -> Result<bool, u16> {
    let request = super::static_site::select(&head, &selected, raw).map(|mut request| {
        request.route = Some(selected);
        request
    });
    raw.zeroize();
    exchange_prepared(socket, shared, head, request, deadline, close).await
}

async fn exchange_prepared<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    result: Result<Request, u16>,
    deadline: IncomingDeadline,
    close: bool,
) -> Result<bool, u16> {
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
            let _ = timeout_at(until, rejection(socket, code, shared.settings.scheme)).await;
            let _ = timeout_at(until, socket.shutdown()).await;
            Ok(true)
        }
    };
    drop(head);
    result
}
pub(in crate::standalone::http) async fn reject<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    head: Head,
    raw: &mut [u8],
    deadline: IncomingDeadline,
    code: u16,
) -> Result<bool, u16> {
    raw.zeroize();
    exchange_prepared(socket, shared, head, Err(code), deadline, true).await
}
fn prepare_request(head: &Head, raw: &[u8]) -> Result<Request, u16> {
    LocalPrincipalPolicy
        .authenticate(&head.principal)
        .map_err(|error| super::status(&error))?;
    let tenant = head.principal.tenant.as_ref().ok_or(403u16)?;
    LocalPrincipalPolicy
        .authorize_target(&head.principal, &tenant.0)
        .map_err(|error| super::status(&error))?;
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
    let result = timeout_at(
        until,
        delivery(socket, &prepared, close, shared.settings.scheme),
    )
    .await;
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
    scheme: Scheme,
) -> io::Result<()> {
    let cache_control = if response.request.route.is_some() {
        "private, no-cache"
    } else {
        "private, max-age=31536000, immutable"
    };
    let vary = if response
        .request
        .route
        .as_ref()
        .is_some_and(|route| route.target().web_selection().is_some())
    {
        "Authorization, Accept-Encoding, Accept, Sec-Fetch-Mode, Sec-Fetch-Dest, Sec-Fetch-Site, Sec-Fetch-User"
    } else {
        "Authorization, Accept-Encoding"
    };
    let mut head = format!(
        "HTTP/1.1 {} Response\r\nETag: {}\r\nCache-Control: {cache_control}\r\nVary: {vary}\r\nAccept-Ranges: none\r\n",
        response.code, response.etag,
    );
    if close {
        head.push_str("Connection: close\r\n");
    }
    if let Some(location) = &response.request.redirect {
        head.push_str("Content-Length: 0\r\nLocation: ");
        head.push_str(location);
        head.push_str("\r\n");
    } else if response.code != 304 {
        use std::fmt::Write as _;
        write!(
            &mut head,
            "Content-Length: {}\r\nContent-Type: {}\r\n",
            response.buffer.bytes.len(),
            response.media
        )
        .map_err(|_| io::ErrorKind::InvalidData)?;
    }
    security(&mut head, scheme);
    head.push_str("\r\n");
    if head.len() > latent_ingress::http::MAX_TARGET_BYTES + 2048 {
        return Err(io::ErrorKind::InvalidData.into());
    }
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await?;
    if !response.request.head && response.code != 304 && response.request.redirect.is_none() {
        for chunk in response.buffer.bytes.chunks(16 * 1024) {
            socket.write_all(chunk).await?;
            socket.flush().await?;
        }
    }
    Ok(())
}
async fn rejection<W: AsyncWrite + Unpin>(
    socket: &mut W,
    code: u16,
    scheme: Scheme,
) -> io::Result<()> {
    let allow = if code == 405 {
        "Allow: GET, HEAD\r\n"
    } else {
        ""
    };
    let mut head = format!("HTTP/1.1 {code} Rejected\r\nConnection: close\r\nContent-Length: 0\r\nCache-Control: no-store\r\n{allow}");
    security(&mut head, scheme);
    head.push_str("\r\n");
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await
}
fn security(head: &mut String, scheme: Scheme) {
    for header in browser::security_headers(scheme) {
        head.push_str(header.name);
        head.push_str(": ");
        head.push_str(std::str::from_utf8(header.value).expect("static security header"));
        head.push_str("\r\n");
    }
}
