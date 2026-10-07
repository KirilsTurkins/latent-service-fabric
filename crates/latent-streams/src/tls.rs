//! Protected explicit roots for direct TLS; no system roots or client secrets.
use crate::{error, StreamError, StreamErrorCode, StreamTlsConfig};
use latent_protected_files::{read, ProtectedFilePolicy};
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub(crate) const CONNECTION_ALLOWANCE: usize = 256 * 1024;
pub(crate) const ROOT_ALLOWANCE: usize = 64 * 1024;
pub(crate) const WRITE_BUFFER_BYTES: usize = 16 * 1024;
// The finite encrypted-wire cap is not a certificate-object allocation cap.
// Keep the candidate transport unavailable until the exact pinned parser and
// physical peak controls prove the unchanged original reservations sufficient.
pub(crate) const ACCOUNTING_QUALIFIED: bool = false;
pub(crate) struct InstalledTls {
    pub config: Arc<rustls::ClientConfig>,
    pub _metadata: latent_capabilities::broker::pools::ProviderMetadata,
}

pub(crate) fn configure(input: &StreamTlsConfig) -> Result<Arc<rustls::ClientConfig>, StreamError> {
    let mut roots = rustls::RootCertStore::empty();
    let mut total = 0usize;
    for root in &input.roots {
        let bytes = read(
            &root.file,
            8192,
            ProtectedFilePolicy::Integrity,
            "outboundStreams.tls.trustProtection",
        )
        .map_err(|_| error(StreamErrorCode::TlsFailed))?;
        total = total
            .checked_add(bytes.len())
            .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
        if bytes.is_empty() || total > 32 * 1024 {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let actual = format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&bytes))
        );
        if actual != root.sha256 {
            return Err(error(StreamErrorCode::TlsFailed));
        }
        roots
            .add(rustls::pki_types::CertificateDer::from(bytes))
            .map_err(|_| error(StreamErrorCode::TlsFailed))?;
    }
    let mut config = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(|_| error(StreamErrorCode::TlsFailed))?
    .with_root_certificates(roots)
    .with_no_client_auth();
    config.resumption = rustls::client::Resumption::disabled();
    config.enable_early_data = false;
    config.cert_decompressors.clear();
    config.key_log = Arc::new(rustls::NoKeyLog);
    config.max_fragment_size = Some(4096);
    Ok(Arc::new(config))
}
