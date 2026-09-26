use latent_core::{PlatformError, PlatformErrorCode};
use latent_protected_files::{read, ProtectedFilePolicy};
use rustls::pki_types::{pem::PemObject, CertificateDer, PrivateKeyDer};
use std::{
    io,
    path::Path,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    net::TcpStream,
};
use zeroize::Zeroizing;

pub(crate) fn configuration(
    certificate: &Path,
    key: &Path,
) -> Result<Arc<rustls::ServerConfig>, PlatformError> {
    let failure = || {
        super::super::error(
            PlatformErrorCode::InvalidArgument,
            "http-ingress-tls-configuration",
        )
    };
    let certificate = read(
        certificate,
        64 * 1024,
        ProtectedFilePolicy::Integrity,
        "httpIngress.certificateProtection",
    )?;
    let key = Zeroizing::new(read(
        key,
        16 * 1024,
        ProtectedFilePolicy::Secret,
        "httpIngress.privateKeyProtection",
    )?);
    let certificates = CertificateDer::pem_slice_iter(&certificate)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| failure())?;
    if certificates.is_empty() || certificates.len() > 8 {
        return Err(failure());
    }
    let mut keys = PrivateKeyDer::pem_slice_iter(&key);
    let key = keys.next().ok_or_else(failure)?.map_err(|_| failure())?;
    if keys.next().is_some() {
        return Err(failure());
    }
    let mut config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_protocol_versions(&[&rustls::version::TLS13])
    .map_err(|_| failure())?
    .with_no_client_auth()
    .with_single_cert(certificates, key)
    .map_err(|_| failure())?;
    config.alpn_protocols = vec![b"http/1.1".to_vec()];
    config.max_early_data_size = 0;
    config.send_tls13_tickets = 0;
    config.max_tls13_tickets = 0;
    config.session_storage = Arc::new(rustls::server::NoServerSessionStorage {});
    config.cert_compressors.clear();
    config.cert_decompressors.clear();
    config.max_fragment_size = Some(16 * 1024);
    Ok(Arc::new(config))
}

/// Bytes, deadline and concurrent connection capacity all bound handshake work.
/// A containing connection owner retains its permit through all TLS destruction.
pub(super) struct Socket {
    pub socket: TcpStream,
    pub handshake_remaining: Option<usize>,
}
impl AsyncRead for Socket {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if let Some(remaining) = this.handshake_remaining {
            if remaining == 0 {
                return Poll::Ready(Err(io::ErrorKind::InvalidData.into()));
            }
            let limit = remaining.min(buffer.remaining());
            let mut limited = ReadBuf::new(buffer.initialize_unfilled_to(limit));
            std::task::ready!(Pin::new(&mut this.socket).poll_read(cx, &mut limited))?;
            let read = limited.filled().len();
            buffer.advance(read);
            this.handshake_remaining = Some(remaining - read);
            Poll::Ready(Ok(()))
        } else {
            Pin::new(&mut this.socket).poll_read(cx, buffer)
        }
    }
}
impl AsyncWrite for Socket {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.get_mut().socket).poll_write(cx, bytes)
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().socket).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.get_mut().socket).poll_shutdown(cx)
    }
}
