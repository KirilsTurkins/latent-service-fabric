use crate::{error, StreamError, StreamErrorCode};
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use serde::{Deserialize, Serialize};
use std::net::{IpAddr, SocketAddr};

#[derive(Clone, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum StreamResolution {
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
pub struct StreamDestination {
    pub endpoint: StreamEndpoint,
    pub addresses: AddressPolicy,
    pub resolution: StreamResolution,
}

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StreamLimits {
    pub maximum_transfer_bytes: u64,
    pub idle_timeout_millis: u32,
    pub absolute_timeout_millis: u32,
}
impl Default for StreamLimits {
    fn default() -> Self {
        Self {
            maximum_transfer_bytes: 1024 * 1024,
            idle_timeout_millis: 2000,
            absolute_timeout_millis: 10_000,
        }
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StreamProviderConfig {
    pub format_version: u32,
    pub profile: String,
    pub destinations: Vec<StreamDestination>,
    pub limits: StreamLimits,
}
impl StreamProviderConfig {
    pub fn validate(&self) -> Result<(), StreamError> {
        if self.format_version != 1
            || self.profile != latent_capabilities::broker::network::STREAM_PROFILE
            || self.profile.capacity() > 128
            || self.destinations.is_empty()
            || self.destinations.capacity() > 8
            || self.limits.maximum_transfer_bytes == 0
            || self.limits.maximum_transfer_bytes > 1024 * 1024
            || self.limits.idle_timeout_millis == 0
            || self.limits.idle_timeout_millis > 2000
            || self.limits.absolute_timeout_millis == 0
            || self.limits.absolute_timeout_millis > 10_000
            || self.limits.idle_timeout_millis > self.limits.absolute_timeout_millis
        {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        for (index, destination) in self.destinations.iter().enumerate() {
            destination.endpoint.validate()?;
            destination
                .addresses
                .validate()
                .map_err(|_| error(StreamErrorCode::InvalidInput))?;
            if destination.endpoint.host.capacity() > 253
                || self.destinations[..index]
                    .iter()
                    .any(|other| other.endpoint == destination.endpoint)
                || destination.addresses.networks.capacity() > 16
                || destination.addresses.special_addresses.capacity() > 16
            {
                return Err(error(StreamErrorCode::InvalidInput));
            }
            // Guest TLS travels over TCP. Host TLS is separately explicit; this
            // TCP implementation cannot claim or transparently substitute it.
            if destination.endpoint.transport != StreamTransport::Tcp {
                return Err(error(StreamErrorCode::Unsupported));
            }
            match &destination.resolution {
                StreamResolution::Static { addresses } => {
                    if addresses.is_empty()
                        || addresses.capacity() > 8
                        || addresses
                            .iter()
                            .any(|ip| !destination.addresses.permits(*ip))
                        || addresses
                            .iter()
                            .enumerate()
                            .any(|(i, ip)| addresses[..i].contains(ip))
                        || destination
                            .endpoint
                            .host
                            .parse::<IpAddr>()
                            .is_ok_and(|ip| addresses.as_slice() != [ip])
                    {
                        return Err(error(StreamErrorCode::InvalidInput));
                    }
                }
                StreamResolution::Dns {
                    server,
                    maximum_ttl_seconds,
                } => {
                    if server.port() == 0
                        || server.ip().is_unspecified()
                        || server.ip().is_multicast()
                        || *maximum_ttl_seconds == 0
                        || *maximum_ttl_seconds > 300
                        || destination.endpoint.host.parse::<IpAddr>().is_ok()
                    {
                        return Err(error(StreamErrorCode::InvalidInput));
                    }
                }
            }
        }
        Ok(())
    }
}
