use crate::{HttpError, HttpProviderConfig};
use std::sync::Arc;

pub(crate) fn configure(
    config: &HttpProviderConfig,
) -> Result<Arc<rustls::ClientConfig>, HttpError> {
    let mut roots = rustls::RootCertStore::empty();
    if config.public_roots {
        roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    }
    for certificate in &config.extra_roots {
        roots
            .add(rustls::pki_types::CertificateDer::from(certificate.clone()))
            .map_err(|_| HttpError::InvalidRequest)?;
    }
    if roots.is_empty()
        && config
            .destinations
            .iter()
            .any(|d| d.origin.scheme == "https")
    {
        return Err(HttpError::InvalidRequest);
    }
    let mut tls = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(|_| HttpError::InvalidRequest)?
    .with_root_certificates(roots)
    .with_no_client_auth();
    tls.alpn_protocols = vec![b"http/1.1".to_vec()];
    tls.resumption = rustls::client::Resumption::disabled();
    tls.enable_early_data = false;
    tls.cert_decompressors.clear();
    tls.key_log = Arc::new(rustls::NoKeyLog);
    Ok(Arc::new(tls))
}
