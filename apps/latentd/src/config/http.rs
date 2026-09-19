//! Explicit node-owned HTTP/1.1 transport and identity profiles.
mod browser;
use super::{invalid, CredentialRole, NodeConfig};
use crate::standalone::http::tls;
pub use browser::BrowserOrigin;
use latent_core::{InvocationPrincipal, Metadata, PlatformError, PrincipalKind, TenantId};
use latent_ingress::http::{
    cache::PublicCachePolicy, CanonicalTarget, Scheme, EXCHANGE_RESERVATION_BYTES,
};
use serde::{Deserialize, Deserializer};
use std::{
    collections::BTreeSet,
    net::{IpAddr, SocketAddr},
    path::{Path, PathBuf},
    sync::Arc,
};

/// Conservative user-space socket/TLS/parser reservation, distinct from runtime
/// memory and OS socket buffers. A connection slot is reserved before allocation.
pub(crate) const CONNECTION_BYTES: usize = 512 * 1024;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpIngressConfig {
    pub format_version: u32,
    pub bind: SocketAddr,
    pub transport: HttpTransport,
    pub authentication: HttpAuthentication,
    #[serde(default)]
    pub limits: HttpIngressLimits,
    #[serde(default)]
    pub response_cache: Vec<PublicCachePolicy>,
    #[serde(default)]
    pub browser_origins: Vec<BrowserOrigin>,
}

#[derive(Clone, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum HttpTransport {
    Tls {
        #[serde(rename = "certificateFile")]
        certificate_file: PathBuf,
        #[serde(rename = "privateKeyFile")]
        private_key_file: PathBuf,
    },
    /// Cleartext is restricted to a loopback bind and loopback peers.
    Loopback,
    /// A separately secured proxy-to-node link. Scheme is fixed by configuration;
    /// forwarded headers never create identity, tenant, authority or deadline.
    TrustedProxy { peers: Vec<IpAddr> },
}

#[derive(Clone, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum HttpAuthentication {
    /// Only explicit invoke-role node credentials; no administrator tokens.
    Bearer,
    /// Deliberately public origins get an operator-selected low-privilege
    /// identity. Host selection must still match the route's tenant.
    PublicOrigins { origins: Vec<HttpOrigin> },
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpOrigin {
    pub authority: String,
    pub subject: String,
    pub tenant: String,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct HttpIngressLimits {
    pub maximum_connections: usize,
    pub maximum_exchanges: usize,
    pub maximum_buffer_bytes: usize,
    pub handshake_timeout_millis: u64,
    pub header_timeout_millis: u64,
    pub body_timeout_millis: u64,
    pub idle_timeout_millis: u64,
    pub write_timeout_millis: u64,
    pub maximum_connection_age_millis: u64,
    pub maximum_requests_per_connection: u32,
}
impl Default for HttpIngressLimits {
    fn default() -> Self {
        Self {
            maximum_connections: 32,
            maximum_exchanges: 8,
            maximum_buffer_bytes: 48 * 1024 * 1024,
            handshake_timeout_millis: 2000,
            header_timeout_millis: 2000,
            body_timeout_millis: 5000,
            idle_timeout_millis: 5000,
            write_timeout_millis: 5000,
            maximum_connection_age_millis: 60_000,
            maximum_requests_per_connection: 100,
        }
    }
}

#[derive(Clone)]
pub(crate) enum Authentication {
    Bearer(Vec<crate::standalone::transport::TransportCredential>),
    PublicOrigins(Vec<(String, InvocationPrincipal)>),
}
#[derive(Clone)]
pub(crate) struct HttpSettings {
    pub bind: SocketAddr,
    pub tls: Option<Arc<rustls::ServerConfig>>,
    pub peers: Vec<IpAddr>,
    pub scheme: Scheme,
    pub authentication: Authentication,
    pub limits: HttpIngressLimits,
    pub request_timeout_millis: u64,
    pub response_cache: Vec<PublicCachePolicy>,
    pub browser_origins: Vec<BrowserOrigin>,
}
pub(super) fn present<'de, D: Deserializer<'de>>(
    d: D,
) -> Result<Option<HttpIngressConfig>, D::Error> {
    HttpIngressConfig::deserialize(d).map(Some)
}
pub(super) fn anchor(config: &mut HttpIngressConfig, parent: &Path) -> Result<(), PlatformError> {
    if let HttpTransport::Tls {
        certificate_file,
        private_key_file,
    } = &mut config.transport
    {
        for path in [certificate_file, private_key_file] {
            if path.as_os_str().is_empty() {
                return Err(invalid("httpIngress.tlsPath"));
            }
            if path.is_relative() {
                *path = parent.join(&*path);
            }
        }
    }
    Ok(())
}
pub(super) fn derive(
    config: &NodeConfig,
    reservations: usize,
) -> Result<Option<HttpSettings>, PlatformError> {
    let Some(http) = &config.http_ingress else {
        return Ok(None);
    };
    validate_limits(http, reservations)?;
    validate_cache(http)?;
    let limits = http.limits;
    let (tls, scheme, peers) = match &http.transport {
        HttpTransport::Loopback if http.bind.ip().is_loopback() => (None, Scheme::Http, Vec::new()),
        HttpTransport::Loopback => return Err(invalid("httpIngress.loopbackBind")),
        HttpTransport::Tls {
            certificate_file,
            private_key_file,
        } => (
            Some(tls::configuration(certificate_file, private_key_file)?),
            Scheme::Https,
            Vec::new(),
        ),
        HttpTransport::TrustedProxy { peers } => {
            if peers.is_empty()
                || peers.len() > 16
                || peers.iter().any(|p| p.is_unspecified() || p.is_multicast())
                || peers.iter().collect::<BTreeSet<_>>().len() != peers.len()
            {
                return Err(invalid("httpIngress.proxyPeers"));
            }
            (None, Scheme::Https, peers.clone())
        }
    };
    let authentication = match &http.authentication {
        HttpAuthentication::Bearer => {
            let credentials: Vec<_> = config
                .credentials
                .iter()
                .filter(|c| c.role == CredentialRole::Invoke)
                .map(|c| crate::standalone::transport::TransportCredential {
                    token: c.token.clone(),
                    principal: super::policy::principal(c),
                })
                .collect();
            if credentials.is_empty() {
                return Err(invalid("httpIngress.invokeCredentials"));
            }
            Authentication::Bearer(credentials)
        }
        HttpAuthentication::PublicOrigins { origins } => {
            if origins.is_empty() || origins.len() > 32 {
                return Err(invalid("httpIngress.publicOrigins"));
            }
            let mut unique = BTreeSet::new();
            let mut result = Vec::new();
            for origin in origins {
                let target = CanonicalTarget::parse(scheme, &origin.authority, "/")
                    .map_err(|_| invalid("httpIngress.publicOrigin"))?;
                if target.authority() != origin.authority
                    || !unique.insert(&origin.authority)
                    || [&origin.subject, &origin.tenant]
                        .iter()
                        .any(|v| v.is_empty() || v.len() > 256 || v.chars().any(char::is_control))
                    || !config.credentials.iter().any(|c| c.tenant == origin.tenant)
                {
                    return Err(invalid("httpIngress.publicOrigin"));
                }
                result.push((
                    origin.authority.clone(),
                    InvocationPrincipal {
                        subject: origin.subject.clone(),
                        kind: PrincipalKind::Trigger,
                        tenant: Some(TenantId(origin.tenant.clone())),
                        service: None,
                        claims: Metadata::new(),
                    },
                ));
            }
            Authentication::PublicOrigins(result)
        }
    };
    let browser_origins = browser::derive(config, http, scheme, &authentication)?;
    Ok(Some(HttpSettings {
        bind: http.bind,
        tls,
        peers,
        scheme,
        authentication,
        limits,
        request_timeout_millis: config.execution.maximum_wall_time_millis,
        response_cache: http.response_cache.clone(),
        browser_origins,
    }))
}

fn validate_cache(http: &HttpIngressConfig) -> Result<(), PlatformError> {
    if http.response_cache.is_empty() {
        return Ok(());
    }
    let HttpAuthentication::PublicOrigins { origins } = &http.authentication else {
        return Err(invalid("httpIngress.responseCache"));
    };
    let mut unique = BTreeSet::new();
    if http.response_cache.len() > 32
        || http.response_cache.iter().any(|policy| {
            !policy.validate()
                || !unique.insert((
                    &policy.tenant,
                    &policy.publication,
                    &policy.authority,
                    &policy.path,
                ))
                || policy.renderer_profile != latent_ingress::http::PROFILE
                || !origins.iter().any(|origin| {
                    origin.authority == policy.authority && origin.tenant == policy.tenant
                })
        })
    {
        return Err(invalid("httpIngress.responseCache"));
    }
    Ok(())
}
fn validate_limits(http: &HttpIngressConfig, reservations: usize) -> Result<(), PlatformError> {
    let limits = http.limits;
    if http.format_version != 1
        || !(1..=128).contains(&limits.maximum_connections)
        || !(1..=64).contains(&limits.maximum_exchanges)
        || limits.maximum_exchanges > reservations
        || !(1..=1000).contains(&limits.maximum_requests_per_connection)
        || limits.maximum_buffer_bytes > 512 * 1024 * 1024
        || limits.maximum_connections * CONNECTION_BYTES
            + limits.maximum_exchanges * EXCHANGE_RESERVATION_BYTES
            > limits.maximum_buffer_bytes
        || !(100..=300_000).contains(&limits.maximum_connection_age_millis)
        || [
            limits.handshake_timeout_millis,
            limits.header_timeout_millis,
            limits.body_timeout_millis,
            limits.idle_timeout_millis,
            limits.write_timeout_millis,
        ]
        .into_iter()
        .any(|t| !(10..=30_000).contains(&t) || t > limits.maximum_connection_age_millis)
        || (!http.bind.ip().is_loopback() && http.bind.ip().is_multicast())
    {
        return Err(invalid("httpIngress.limits"));
    }
    Ok(())
}
