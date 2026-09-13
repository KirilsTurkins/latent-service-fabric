use super::super::{invalid, RegistryConfig, RegistryCredentials, Result};
use super::Endpoint;
use base64::Engine;
use reqwest::{
    header::{HeaderMap, HeaderValue, ACCEPT},
    Client, ClientBuilder,
};
use std::{net::SocketAddr, sync::Arc};

pub(super) fn build(config: &RegistryConfig, endpoint: &Endpoint) -> Result<Client> {
    let mut headers = HeaderMap::new();
    headers.insert(
        ACCEPT,
        HeaderValue::from_static(
            "application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json",
        ),
    );
    let mut client = builder(config)?.default_headers(headers);
    if !config.addresses.is_empty() {
        client = client.resolve_to_addrs(endpoint.host(), &config.addresses);
    }
    client
        .build()
        .map_err(|_| invalid("oci-client-construction-failed"))
}

/// Separate client for one preapproved token authority. Keeping its resolver
/// table separate prevents a same-host/different-port realm from rewriting the
/// configured registry destination.
pub(super) fn build_authority(
    config: &RegistryConfig,
    host: &str,
    addresses: &[SocketAddr],
) -> Result<Client> {
    let mut client = builder(config)?;
    if !addresses.is_empty() {
        client = client.resolve_to_addrs(host, addresses);
    }
    client
        .build()
        .map_err(|_| invalid("oci-token-client-construction-failed"))
}

fn builder(config: &RegistryConfig) -> Result<ClientBuilder> {
    if config.additional_root_certificates.len() > 8
        || config
            .additional_root_certificates
            .iter()
            .any(|root| root.len() > 64 * 1024)
    {
        return Err(invalid("oci-tls-root-limit"));
    }
    let mut roots = rustls::RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    for certificate in &config.additional_root_certificates {
        roots
            .add(rustls::pki_types::CertificateDer::from(certificate.clone()))
            .map_err(|_| invalid("invalid-oci-tls-root"))?;
    }
    let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(|_| invalid("invalid-oci-tls-configuration"))?
    .with_root_certificates(roots)
    .with_no_client_auth();
    Ok(Client::builder()
        .tls_backend_preconfigured(tls)
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        // Disable decoding even if another consumer unifies compression features.
        .no_gzip()
        .no_brotli()
        .no_zstd()
        .no_deflate()
        .no_proxy()
        .http1_only()
        .connect_timeout(config.limits.connect_timeout)
        .read_timeout(config.limits.request_timeout)
        .timeout(config.limits.request_timeout)
        .pool_max_idle_per_host(config.limits.max_in_flight + 1)
        .pool_idle_timeout(std::time::Duration::from_secs(15)))
}

pub(super) fn authorization(credentials: &RegistryCredentials) -> Result<Option<HeaderValue>> {
    match credentials {
        RegistryCredentials::Anonymous | RegistryCredentials::BearerChallenge { .. } => Ok(None),
        RegistryCredentials::Basic { username, password } => {
            basic_authorization(username, password).map(Some)
        }
        RegistryCredentials::Bearer(token) => bearer_authorization(token).map(Some),
    }
}

pub(super) fn basic_authorization(username: &str, password: &str) -> Result<HeaderValue> {
    if username.is_empty()
        || username.len() > 256
        || username.contains(':')
        || password.len() > 4096
        || username
            .chars()
            .chain(password.chars())
            .any(char::is_control)
    {
        return Err(invalid("invalid-oci-credentials"));
    }
    sensitive(&format!(
        "Basic {}",
        base64::engine::general_purpose::STANDARD.encode(format!("{username}:{password}"))
    ))
}

pub(super) fn bearer_authorization(token: &str) -> Result<HeaderValue> {
    if token.is_empty() || token.len() > 8192 || !token.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(invalid("invalid-oci-credentials"));
    }
    sensitive(&format!("Bearer {token}"))
}

fn sensitive(value: &str) -> Result<HeaderValue> {
    let mut header = HeaderValue::from_str(value).map_err(|_| invalid("invalid-oci-credentials"))?;
    header.set_sensitive(true);
    Ok(header)
}
