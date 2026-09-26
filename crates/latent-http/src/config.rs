use crate::HttpError;
pub use latent_network::AddressPolicy as HttpAddressPolicy;
use latent_policy::capability::HttpOrigin;
use serde::{Deserialize, Serialize};
use std::net::{IpAddr, SocketAddr};

#[derive(Clone, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum HttpResolution {
    Static {
        addresses: Vec<IpAddr>,
    },
    Dns {
        server: SocketAddr,
        maximum_ttl_seconds: u32,
    },
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpDestination {
    pub origin: HttpOrigin,
    pub addresses: HttpAddressPolicy,
    pub resolution: HttpResolution,
    /// Guest header names are explicitly approved; transport/credential fields
    /// remain reserved even if named here.
    pub allowed_request_headers: Vec<String>,
    /// Only these other configured destination indices may receive redirects.
    /// The broker independently checks their actual method/path for each hop.
    pub redirect_destinations: Vec<usize>,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpLimits {
    pub maximum_request_body_bytes: usize,
    pub maximum_response_body_bytes: usize,
    pub maximum_encoded_response_bytes: usize,
    pub maximum_header_bytes: usize,
    pub maximum_headers: usize,
    pub maximum_redirects: usize,
}
impl Default for HttpLimits {
    fn default() -> Self {
        Self {
            maximum_request_body_bytes: 32768,
            maximum_response_body_bytes: 32768,
            maximum_encoded_response_bytes: 32768,
            maximum_header_bytes: 8192,
            maximum_headers: 32,
            maximum_redirects: 0,
        }
    }
}
impl HttpLimits {
    pub fn validate(self) -> Result<(), HttpError> {
        if [
            self.maximum_request_body_bytes,
            self.maximum_response_body_bytes,
            self.maximum_encoded_response_bytes,
        ]
        .iter()
        .any(|n| *n == 0 || *n > 512 * 1024)
            || !(1024..=32768).contains(&self.maximum_header_bytes)
            || !(1..=64).contains(&self.maximum_headers)
            || self.maximum_redirects > 3
        {
            return Err(HttpError::InvalidRequest);
        }
        Ok(())
    }
    /// Includes canonical header/container copies in addition to charged I/O
    /// storage. The broker intersects this with every independent policy ceiling.
    pub(crate) fn output_reservation(self) -> usize {
        self.maximum_response_body_bytes
            + 2 * self.maximum_header_bytes
            + self.maximum_headers * 64
            + 1024
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpProviderConfig {
    pub format_version: u32,
    pub destinations: Vec<HttpDestination>,
    pub limits: HttpLimits,
    /// DER roots are explicit trusted input, bounded before a verifier is built.
    /// System/web roots are separately enabled; no environment CA override exists.
    pub extra_roots: Vec<Vec<u8>>,
    pub public_roots: bool,
}
impl HttpProviderConfig {
    pub fn validate(&self) -> Result<(), HttpError> {
        self.limits.validate()?;
        if self.format_version != 1
            || !(1..=8).contains(&self.destinations.len())
            || self.destinations.capacity() > 8
            || self.extra_roots.capacity() > 8
            || self
                .extra_roots
                .iter()
                .any(|r| r.is_empty() || r.capacity() > 8192)
            || self.extra_roots.iter().map(Vec::len).sum::<usize>() > 32768
        {
            return Err(HttpError::InvalidRequest);
        }
        for (i, destination) in self.destinations.iter().enumerate() {
            destination.validate(self.destinations.len())?;
            if self.destinations[..i]
                .iter()
                .any(|d| d.origin == destination.origin)
            {
                return Err(HttpError::InvalidRequest);
            }
        }
        Ok(())
    }
}
impl HttpDestination {
    fn validate(&self, destinations: usize) -> Result<(), HttpError> {
        if self.allowed_request_headers.capacity() > 32
            || self.allowed_request_headers.iter().any(|name| {
                name.capacity() > 64
                    || !crate::headers::valid_name(name)
                    || name.bytes().any(|b| b.is_ascii_uppercase())
                    || crate::headers::reserved(name)
            })
            || self
                .allowed_request_headers
                .iter()
                .enumerate()
                .any(|(i, name)| self.allowed_request_headers[..i].contains(name))
        {
            return Err(HttpError::InvalidRequest);
        }
        let origin = &self.origin;
        if origin.host.capacity() > 253
            || origin.scheme.capacity() > 8
            || !matches!(origin.scheme.as_str(), "http" | "https")
            || origin.port == 0
        {
            return Err(HttpError::InvalidRequest);
        }
        let request = serde_json::json!({"kind":"http","origin":origin,"method":"GET","path":"/"});
        latent_policy::capability::ResourceRequest::parse(
            &serde_json::to_vec(&request).map_err(|_| HttpError::InvalidRequest)?,
        )?;
        if !(1..=16).contains(&self.addresses.networks.len())
            || self.addresses.networks.capacity() > 16
            || self.addresses.special_addresses.capacity() > 16
            || self.redirect_destinations.capacity() > 8
            || self
                .redirect_destinations
                .iter()
                .any(|n| *n >= destinations)
            || self
                .addresses
                .networks
                .iter()
                .enumerate()
                .any(|(i, n)| self.addresses.networks[..i].contains(n))
            || self
                .addresses
                .special_addresses
                .iter()
                .enumerate()
                .any(|(i, n)| self.addresses.special_addresses[..i].contains(n))
            || self
                .redirect_destinations
                .iter()
                .enumerate()
                .any(|(i, n)| self.redirect_destinations[..i].contains(n))
        {
            return Err(HttpError::InvalidRequest);
        }
        match &self.resolution {
            HttpResolution::Static { addresses } => {
                if !(1..=8).contains(&addresses.len())
                    || addresses.capacity() > 8
                    || addresses.iter().any(|ip| !self.addresses.permits(*ip))
                    || addresses
                        .iter()
                        .enumerate()
                        .any(|(i, n)| addresses[..i].contains(n))
                {
                    return Err(HttpError::InvalidRequest);
                }
                if let Ok(ip) = origin.host.parse::<IpAddr>() {
                    if addresses.as_slice() != [ip] {
                        return Err(HttpError::InvalidRequest);
                    }
                }
            }
            HttpResolution::Dns {
                server,
                maximum_ttl_seconds,
            } => {
                if server.port() == 0
                    || server.ip().is_unspecified()
                    || server.ip().is_multicast()
                    || *maximum_ttl_seconds > 300
                    || origin.host.parse::<IpAddr>().is_ok()
                {
                    return Err(HttpError::InvalidRequest);
                }
            }
        }
        Ok(())
    }
}
