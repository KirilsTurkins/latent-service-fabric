//! Every write poll is fenced by current publication authority, including 304.
use super::super::Prepared;
use latent_artifacts::web::WebSelection;
use latent_ingress::http::{browser, Scheme};
use std::{fmt::Write as _, future::Future, io, task::Poll};
use tokio::io::{AsyncWrite, AsyncWriteExt};

pub(in crate::standalone::http) const VARY: &str = "Origin, Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest, Access-Control-Request-Method, Access-Control-Request-Headers, Authorization, Cookie, Accept, Accept-Encoding, Sec-Fetch-User";

pub(super) struct Policy {
    pub origin: String,
    pub credentials: bool,
    pub preflight: Option<String>,
}

pub(super) async fn asset<W: AsyncWrite + Unpin>(
    socket: &mut W,
    response: &Prepared,
    policy: &Policy,
    close: bool,
    scheme: Scheme,
) -> io::Result<()> {
    let selection = response
        .request
        .route
        .as_ref()
        .and_then(|route| route.target().web_selection())
        .or(response.selection.as_ref())
        .ok_or(io::ErrorKind::PermissionDenied)?;
    let mut head = common(response.code, scheme, close, Some(policy));
    write!(
        &mut head,
        "ETag: {}\r\nAccept-Ranges: none\r\n",
        response.etag
    )
    .map_err(|_| io::ErrorKind::InvalidData)?;
    if response.code != 304 {
        write!(
            &mut head,
            "Content-Length: {}\r\nContent-Type: {}\r\n",
            response.buffer.bytes.len(),
            response.media,
        )
        .map_err(|_| io::ErrorKind::InvalidData)?;
    }
    head.push_str("\r\n");
    write_head(socket, &head, Some(selection)).await?;
    if !response.request.head && response.code != 304 {
        for chunk in response.buffer.bytes.chunks(16 * 1024) {
            current(selection, socket.write_all(chunk)).await?;
            current(selection, socket.flush()).await?;
        }
    }
    Ok(())
}

pub(super) async fn empty<W: AsyncWrite + Unpin>(
    socket: &mut W,
    code: u16,
    scheme: Scheme,
    close: bool,
    policy: Option<&Policy>,
    selection: Option<&WebSelection>,
) -> io::Result<()> {
    if policy.is_some() && selection.is_none() {
        return Err(io::ErrorKind::PermissionDenied.into());
    }
    let mut head = common(code, scheme, close, policy);
    if code != 204 && code != 304 {
        head.push_str("Content-Length: 0\r\n");
    }
    if code == 405 {
        head.push_str("Allow: GET, HEAD\r\n");
    }
    head.push_str("\r\n");
    write_head(socket, &head, selection).await
}

fn common(code: u16, scheme: Scheme, close: bool, policy: Option<&Policy>) -> String {
    let cache = if code >= 400 || policy.is_none() {
        "no-store"
    } else {
        "private, no-cache"
    };
    let mut head =
        format!("HTTP/1.1 {code} Response\r\nCache-Control: {cache}\r\nVary: {VARY}\r\n");
    if close {
        head.push_str("Connection: close\r\n");
    }
    for header in browser::security_headers(scheme) {
        if policy.is_some() && header.name == "cross-origin-resource-policy" {
            continue;
        }
        head.push_str(header.name);
        head.push_str(": ");
        head.push_str(std::str::from_utf8(header.value).expect("static security header"));
        head.push_str("\r\n");
    }
    if let Some(policy) = policy {
        head.push_str("Access-Control-Allow-Origin: ");
        head.push_str(&policy.origin);
        head.push_str("\r\nCross-Origin-Resource-Policy: cross-origin\r\nAccess-Control-Expose-Headers: ETag\r\n");
        if policy.credentials {
            head.push_str("Access-Control-Allow-Credentials: true\r\n");
        }
        if code == 204 {
            if let Some(headers) = &policy.preflight {
                head.push_str(
                    "Access-Control-Allow-Methods: GET, HEAD\r\nAccess-Control-Max-Age: 0\r\n",
                );
                if !headers.is_empty() {
                    head.push_str("Access-Control-Allow-Headers: ");
                    head.push_str(headers);
                    head.push_str("\r\n");
                }
            }
        }
    }
    head
}

async fn write_head<W: AsyncWrite + Unpin>(
    socket: &mut W,
    head: &str,
    selection: Option<&WebSelection>,
) -> io::Result<()> {
    // At most one 512-byte approved origin and 64-byte preflight header list.
    // This buffer is covered by the original ingress exchange reservation.
    if head.len() > 8192 {
        return Err(io::ErrorKind::InvalidData.into());
    }
    if let Some(selection) = selection {
        current(selection, socket.write_all(head.as_bytes())).await?;
        current(selection, socket.flush()).await
    } else {
        socket.write_all(head.as_bytes()).await?;
        socket.flush().await
    }
}

async fn current<T>(
    selection: &WebSelection,
    future: impl Future<Output = io::Result<T>>,
) -> io::Result<T> {
    let tenant = selection
        .publication()
        .scope
        .tenant()
        .ok_or(io::ErrorKind::PermissionDenied)?;
    tokio::pin!(future);
    std::future::poll_fn(|context| {
        let mut poll = None;
        match selection.with_current(tenant, &mut |checker| {
            checker.check()?;
            poll = Some(future.as_mut().poll(context));
            Ok(())
        }) {
            Ok(()) => poll.expect("current publication polled once"),
            Err(_) => Poll::Ready(Err(io::ErrorKind::PermissionDenied.into())),
        }
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cors_headers_are_exact_private_and_repeated_on_every_authorized_status() {
        for code in [200, 204, 304, 400, 404, 406, 412, 503] {
            for credentials in [false, true] {
                let policy = Policy {
                    origin: "https://portal.example".into(),
                    credentials,
                    preflight: Some("if-none-match".into()),
                };
                let text = common(code, Scheme::Https, false, Some(&policy));
                assert!(text.contains("Access-Control-Allow-Origin: https://portal.example\r\n"));
                assert!(!text.contains("Access-Control-Allow-Origin: *"));
                assert!(text.contains("Cross-Origin-Resource-Policy: cross-origin\r\n"));
                assert!(!text.contains("cross-origin-resource-policy: same-origin"));
                assert!(text.contains("Access-Control-Expose-Headers: ETag\r\n"));
                assert_eq!(
                    text.contains("Access-Control-Allow-Credentials: true"),
                    credentials
                );
                assert!(text.contains(&format!("Vary: {VARY}\r\n")));
                assert!(text.contains(if code >= 400 {
                    "Cache-Control: no-store\r\n"
                } else {
                    "Cache-Control: private, no-cache\r\n"
                }));
                assert_eq!(text.contains("Access-Control-Max-Age: 0"), code == 204);
                assert!(text.contains("x-content-type-options: nosniff\r\n"));
                assert!(!text.contains("Set-Cookie:"));
            }
            let denial = common(code, Scheme::Https, true, None);
            assert!(!denial.contains("Access-Control-Allow-"));
            assert!(denial.contains("cross-origin-resource-policy: same-origin\r\n"));
            assert!(denial.contains("Cache-Control: no-store\r\n"));
        }
    }
}
