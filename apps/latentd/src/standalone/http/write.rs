use latent_ingress::http::{browser, Delivery, Scheme};
use std::io;
use tokio::io::{AsyncWrite, AsyncWriteExt};

pub(super) async fn delivery<W: AsyncWrite + Unpin>(
    socket: &mut W,
    mut delivery: Delivery,
    close: bool,
    scheme: Scheme,
) -> io::Result<()> {
    delivery
        .enforce_browser_profile(scheme)
        .map_err(|_| io::ErrorKind::InvalidData)?;
    let mut head = Vec::with_capacity(32 * 1024);
    head.extend_from_slice(format!("HTTP/1.1 {} Response\r\n", delivery.status()).as_bytes());
    if close {
        head.extend_from_slice(b"Connection: close\r\n");
    }
    if let Some(length) = delivery.content_length() {
        head.extend_from_slice(format!("Content-Length: {length}\r\n").as_bytes());
    }
    if let Some(media) = delivery.media_type() {
        head.extend_from_slice(b"Content-Type: ");
        head.extend_from_slice(media.as_bytes());
        head.extend_from_slice(b"\r\n");
    } else {
        head.extend_from_slice(b"Content-Type: application/octet-stream\r\n");
    }
    for header in delivery.headers().chain(browser::security_headers(scheme)) {
        head.extend_from_slice(header.name.as_bytes());
        head.extend_from_slice(b": ");
        head.extend_from_slice(header.value);
        head.extend_from_slice(b"\r\n");
    }
    head.extend_from_slice(b"\r\n");
    if head.len() > super::head::MAX_HEAD {
        return Err(io::ErrorKind::InvalidData.into());
    }
    socket.write_all(&head).await?;
    socket.flush().await?;
    delivery
        .mark_headers_written()
        .map_err(|_| io::ErrorKind::TimedOut)?;
    loop {
        let remaining = delivery
            .remaining_body()
            .map_err(|_| io::ErrorKind::TimedOut)?;
        if remaining.is_empty() {
            break;
        }
        let n = socket
            .write(&remaining[..remaining.len().min(16 * 1024)])
            .await?;
        if n == 0 {
            return Err(io::ErrorKind::WriteZero.into());
        }
        // TLS write accepts plaintext into its own finite buffer. Advance the
        // delivery only after flushing the corresponding encrypted socket writes.
        socket.flush().await?;
        delivery.advance(n).map_err(|_| io::ErrorKind::TimedOut)?;
    }
    delivery.finish().map_err(|_| io::ErrorKind::TimedOut)?;
    Ok(())
}
pub(super) async fn error<W: AsyncWrite + Unpin>(
    socket: &mut W,
    status: u16,
    scheme: Scheme,
) -> io::Result<()> {
    // Only fixed local status numbers, never request text, token or guest error.
    let mut head = format!("HTTP/1.1 {status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\nCache-Control: no-store\r\n");
    for header in browser::security_headers(scheme) {
        head.push_str(header.name);
        head.push_str(": ");
        head.push_str(std::str::from_utf8(header.value).expect("static security header"));
        head.push_str("\r\n");
    }
    head.push_str("\r\n");
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await
}
