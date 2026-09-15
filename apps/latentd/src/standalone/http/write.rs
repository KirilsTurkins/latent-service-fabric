use latent_ingress::http::Delivery;
use std::io;
use tokio::io::{AsyncWrite, AsyncWriteExt};

pub(super) async fn delivery<W: AsyncWrite + Unpin>(
    socket: &mut W,
    mut delivery: Delivery,
    close: bool,
) -> io::Result<()> {
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
    }
    for header in delivery.headers() {
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
pub(super) async fn error<W: AsyncWrite + Unpin>(socket: &mut W, status: u16) -> io::Result<()> {
    // Only fixed local status numbers, never request text, token or guest error.
    let head = format!("HTTP/1.1 {status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\nCache-Control: no-store\r\n\r\n");
    socket.write_all(head.as_bytes()).await?;
    socket.flush().await
}
