mod owned;
mod response;
#[cfg(test)]
mod tests;

use super::{invalid, RegistryConfig, RegistryCredentials, Result};
use latent_core::PlatformErrorCode;
pub use latent_network::AddressPolicy as RegistryAddressPolicy;
use latent_network::{canonical, dns::Resolver, NetworkError};
pub(super) use owned::OwnedClient;
use reqwest::Url;
use std::{
    net::{IpAddr, SocketAddr},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
};

#[derive(Clone, Debug)]
pub enum RegistryResolution {
    Static {
        addresses: Vec<IpAddr>,
    },
    Dns {
        server: SocketAddr,
        maximum_ttl_seconds: u32,
    },
}

#[derive(Clone, Debug)]
pub struct RegistryDestination {
    pub origin: String,
    pub addresses: RegistryAddressPolicy,
    pub resolution: RegistryResolution,
    pub content_prefixes: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct RegistryNetworkPolicy {
    pub destinations: Vec<RegistryDestination>,
    pub maximum_redirects: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RegistryNetworkUsage {
    pub connections: usize,
    pub reserved_connection_bytes: usize,
    pub maximum_connections: usize,
    pub maximum_connection_bytes: usize,
    pub active_resolvers: usize,
    pub waiting_resolvers: usize,
    pub retained_dns_answers: usize,
    pub reserved_resolver_bytes: usize,
    pub reserved_redirect_bytes: usize,
    pub destinations: usize,
    pub closed: bool,
}

pub(super) struct Network {
    clients: Vec<Arc<OwnedClient>>,
    pub maximum_redirects: usize,
    counters: Arc<Counters>,
    token_realm: Url,
}

pub(super) struct Counters {
    connections: AtomicUsize,
    bytes: AtomicUsize,
    maximum_connections: usize,
    maximum_bytes: usize,
    closed: AtomicBool,
    retired: tokio::sync::Notify,
    redirects: AtomicUsize,
}

impl Network {
    pub fn new(config: &RegistryConfig, policy: RegistryNetworkPolicy) -> Result<Self> {
        let RegistryCredentials::BearerChallenge {
            realm, addresses, ..
        } = &config.credentials
        else {
            return Err(invalid("oci-network-profile-requires-bearer-authority"));
        };
        if policy.destinations.is_empty()
            || policy.destinations.len() > 8
            || policy.maximum_redirects > 3
            || !config.addresses.is_empty()
            || !addresses.is_empty()
            || config.allow_insecure_loopback
        {
            return Err(invalid("invalid-oci-network-profile"));
        }
        let registry = origin(&config.origin)?;
        let realm = Url::parse(realm).map_err(|_| invalid("invalid-oci-bearer-realm"))?;
        let counters = Arc::new(Counters {
            connections: 0.into(),
            bytes: 0.into(),
            maximum_connections: config.limits.max_in_flight + 1,
            maximum_bytes: config.limits.max_retained_bytes as usize
                + (config.limits.max_in_flight + 1) * 256 * 1024,
            closed: false.into(),
            retired: tokio::sync::Notify::new(),
            redirects: 0.into(),
        });
        let tls = owned::tls(config)?;
        let mut clients = Vec::<Arc<OwnedClient>>::with_capacity(policy.destinations.len());
        for destination in policy.destinations {
            let origin = origin(&destination.origin)?;
            destination.addresses.validate().map_err(error)?;
            if clients
                .iter()
                .any(|client| client.origin.origin() == origin.origin())
                || destination.content_prefixes.len() > 8
                || destination
                    .content_prefixes
                    .iter()
                    .any(|prefix| !content_prefix(prefix))
            {
                return Err(invalid("invalid-oci-network-destination"));
            }
            let host = origin
                .host_str()
                .ok_or_else(|| invalid("invalid-oci-origin"))?
                .trim_matches(['[', ']']);
            let resolver = match &destination.resolution {
                RegistryResolution::Dns {
                    server,
                    maximum_ttl_seconds,
                } => Some(
                    Resolver::new(
                        host.to_owned(),
                        *server,
                        *maximum_ttl_seconds,
                        destination.addresses.clone(),
                        config.limits.max_in_flight,
                    )
                    .map_err(error)?,
                ),
                RegistryResolution::Static { addresses } => {
                    if addresses.is_empty()
                        || addresses.len() > 16
                        || addresses
                            .iter()
                            .any(|address| !destination.addresses.permits(*address))
                        || host.parse::<IpAddr>().ok().is_some_and(|literal| {
                            addresses
                                .iter()
                                .any(|address| canonical(*address) != canonical(literal))
                        })
                    {
                        return Err(invalid("invalid-oci-static-destination"));
                    }
                    None
                }
            };
            clients.push(Arc::new(OwnedClient {
                origin,
                policy: destination.addresses,
                resolution: destination.resolution,
                resolver,
                content_prefixes: destination.content_prefixes,
                counters: Arc::clone(&counters),
                tls: Arc::clone(&tls),
                limits: config.limits,
            }));
        }
        let network = Self {
            clients,
            counters,
            maximum_redirects: policy.maximum_redirects,
            token_realm: realm.clone(),
        };
        network.client(&registry)?;
        network.client(&realm)?;
        Ok(network)
    }

    pub fn client(&self, url: &Url) -> Result<Arc<OwnedClient>> {
        self.clients
            .iter()
            .find(|client| client.origin.origin() == url.origin())
            .cloned()
            .ok_or_else(|| {
                crate::error(
                    PlatformErrorCode::PermissionDenied,
                    "oci-destination-not-approved",
                )
            })
    }

    pub fn content_target(&self, current: &Url, raw: &str) -> Result<(Url, Arc<OwnedClient>)> {
        if raw.is_empty()
            || raw.len() > 4096
            || !raw.is_ascii()
            || raw.split('?').next().is_some_and(|path| path.contains('%'))
            || raw
                .split_once("://")
                .map(|(_, tail)| tail)
                .or_else(|| raw.strip_prefix("//"))
                .and_then(|tail| tail.split(['/', '?', '#']).next())
                .is_some_and(|authority| authority.contains('@'))
            || raw
                .bytes()
                .any(|byte| byte <= 32 || byte == 127 || byte == b'\\')
            || raw
                .split(['/', '?', '#'])
                .any(|part| part == ".." || part == ".")
        {
            return Err(invalid("invalid-oci-content-redirect"));
        }
        let target = current
            .join(raw)
            .map_err(|_| invalid("invalid-oci-content-redirect"))?;
        if target.as_str().len() > 4096
            || target.scheme() != "https"
            || !target.username().is_empty()
            || target.password().is_some()
            || target.fragment().is_some()
            || target.path().contains(['%', '\\'])
            || target.path().starts_with("/v2/")
            || (target.origin() == self.token_realm.origin()
                && target.path() == self.token_realm.path())
        {
            return Err(invalid("oci-content-redirect-outside-profile"));
        }
        let client = self.client(&target)?;
        if !client
            .content_prefixes
            .iter()
            .any(|prefix| target.path().starts_with(prefix))
        {
            return Err(crate::error(
                PlatformErrorCode::PermissionDenied,
                "oci-content-path-not-approved",
            ));
        }
        Ok((target, client))
    }

    pub fn usage(&self) -> RegistryNetworkUsage {
        let mut usage = RegistryNetworkUsage {
            connections: self.counters.connections.load(Ordering::Acquire),
            reserved_connection_bytes: self.counters.bytes.load(Ordering::Acquire),
            maximum_connections: self.counters.maximum_connections,
            maximum_connection_bytes: self.counters.maximum_bytes,
            active_resolvers: 0,
            waiting_resolvers: 0,
            retained_dns_answers: 0,
            reserved_resolver_bytes: 0,
            reserved_redirect_bytes: self.counters.redirects.load(Ordering::Acquire) * 16384,
            destinations: self.clients.len(),
            closed: self.counters.closed.load(Ordering::Acquire),
        };
        for resolver in self
            .clients
            .iter()
            .filter_map(|client| client.resolver.as_ref())
        {
            let current = resolver.usage();
            usage.active_resolvers += current.active;
            usage.waiting_resolvers += current.waiting;
            usage.retained_dns_answers += current.cached_answers;
            usage.reserved_resolver_bytes += current.reserved_bytes;
        }
        usage
    }

    pub async fn close(&self, deadline: tokio::time::Instant) -> Result<()> {
        self.counters.closed.store(true, Ordering::Release);
        for resolver in self
            .clients
            .iter()
            .filter_map(|client| client.resolver.as_ref())
        {
            resolver.close().map_err(error)?;
        }
        loop {
            let retired = self.counters.retired.notified();
            if self.counters.connections.load(Ordering::Acquire) == 0 {
                return Ok(());
            }
            tokio::time::timeout_at(deadline, retired)
                .await
                .map_err(|_| {
                    crate::error(
                        PlatformErrorCode::DeadlineExceeded,
                        "oci-network-shutdown-deadline",
                    )
                })?;
        }
    }

    pub fn redirect_lease(&self) -> Result<RedirectLease<'_>> {
        self.counters
            .redirects
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < self.counters.maximum_connections).then_some(current + 1)
            })
            .map_err(|_| super::exhausted("oci-redirect-owner-limit"))?;
        Ok(RedirectLease(&self.counters.redirects))
    }
}

pub(super) struct RedirectLease<'a>(&'a AtomicUsize);

impl Drop for RedirectLease<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

fn origin(raw: &str) -> Result<Url> {
    if raw.is_empty()
        || raw.len() > 512
        || !raw.is_ascii()
        || raw.contains(['\\', '@'])
        || raw.bytes().any(|byte| byte <= 32 || byte == 127)
    {
        return Err(invalid("invalid-oci-network-origin"));
    }
    let url = Url::parse(raw).map_err(|_| invalid("invalid-oci-network-origin"))?;
    if url.scheme() != "https"
        || url.host().is_none()
        || url.path() != "/"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(invalid("invalid-oci-network-origin"));
    }
    Ok(url)
}

fn content_prefix(prefix: &str) -> bool {
    prefix.len() > 1
        && prefix.len() <= 512
        && prefix.starts_with('/')
        && prefix.ends_with('/')
        && !prefix.starts_with("/v2/")
        && !prefix.contains("//")
        && prefix
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'-' | b'_' | b'.'))
        && !prefix.split('/').any(|part| matches!(part, "." | ".."))
}

pub(super) fn error(error: NetworkError) -> latent_core::PlatformError {
    let code = match error {
        NetworkError::InvalidConfiguration => PlatformErrorCode::InvalidArgument,
        NetworkError::PermissionDenied => PlatformErrorCode::PermissionDenied,
        NetworkError::DeadlineExceeded => PlatformErrorCode::DeadlineExceeded,
        NetworkError::ResourceExhausted => PlatformErrorCode::ResourceExhausted,
        NetworkError::Closed | NetworkError::DnsFailed => PlatformErrorCode::Unavailable,
    };
    crate::error(
        code,
        match error {
            NetworkError::InvalidConfiguration => "oci-network-configuration-invalid",
            NetworkError::PermissionDenied => "oci-network-destination-denied",
            NetworkError::DnsFailed => "oci-dns-failed",
            NetworkError::DeadlineExceeded => "oci-network-deadline",
            NetworkError::ResourceExhausted => "oci-network-capacity",
            NetworkError::Closed => "oci-network-closed",
        },
    )
}

pub(super) fn response_error(error: &reqwest::Error) -> Option<latent_core::PlatformError> {
    let mut source: &(dyn std::error::Error + 'static) = error;
    for _ in 0..8 {
        if let Some(error) = source.downcast_ref::<response::BodyFailure>() {
            let (code, reason) = match error {
                response::BodyFailure::Deadline => {
                    (PlatformErrorCode::DeadlineExceeded, "oci-body-deadline")
                }
                response::BodyFailure::Connection => {
                    (PlatformErrorCode::Unavailable, "oci-body-connection-failed")
                }
                response::BodyFailure::Frames => {
                    (PlatformErrorCode::ResourceExhausted, "oci-body-frame-limit")
                }
            };
            return Some(crate::error(code, reason));
        }
        source = source.source()?;
    }
    None
}
