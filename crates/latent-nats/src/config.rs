use crate::{EventError, Result};
use latent_capabilities::broker::secrets::{TlsCredentialDestination, TlsCredentialProtocol};
use serde::{Deserialize, Serialize};
use std::net::{IpAddr, SocketAddr};

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NatsEndpoint {
    pub server_name: String,
    /// Exactly one approved socket. No DNS, discovered servers or ambient proxies.
    pub peer: SocketAddr,
    /// Explicit approval for this exact non-public address, never a network range.
    pub allow_non_public_peer: bool,
}
impl NatsEndpoint {
    pub fn validate(&self) -> Result<()> {
        if self.server_name.capacity() > 256 {
            return Err(EventError::InvalidEvent);
        }
        self.credential_destination()
            .validate()
            .map_err(|_| EventError::InvalidEvent)?;
        let public = match self.peer.ip() {
            IpAddr::V4(ip) => {
                let [a, b, _, _] = ip.octets();
                if ip.is_unspecified() || ip.is_multicast() || ip.is_broadcast() {
                    return Err(EventError::InvalidEvent);
                }
                !(ip.is_private()
                    || ip.is_loopback()
                    || ip.is_link_local()
                    || ip.is_documentation()
                    || a == 0
                    || a >= 240
                    || (a == 100 && (64..=127).contains(&b))
                    || (a == 198 && (b == 18 || b == 19))
                    || (a == 192 && b == 0))
            }
            // The initial transport profile has no IPv6/mapped-address ambiguity.
            IpAddr::V6(_) => return Err(EventError::InvalidEvent),
        };
        if !public && !self.allow_non_public_peer {
            return Err(EventError::PermissionDenied);
        }
        Ok(())
    }
    #[must_use]
    pub fn credential_destination(&self) -> TlsCredentialDestination {
        TlsCredentialDestination {
            protocol: TlsCredentialProtocol::Nats,
            server_name: self.server_name.clone(),
            port: self.peer.port(),
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopicMapping {
    pub tenant: String,
    pub topic: String,
    pub subject: String,
    pub stream: String,
    /// Required operator stream configuration, not a local deduplication cache.
    pub duplicate_window_millis: u64,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NatsConfig {
    pub format_version: u32,
    pub endpoint: NatsEndpoint,
    pub public_roots: bool,
    pub extra_roots: Vec<Vec<u8>>,
    pub topics: Vec<TopicMapping>,
    /// Stable application publication namespace. Rotation intentionally changes keys.
    pub idempotency_namespace: String,
    pub maximum_payload_bytes: usize,
    /// Converted once on entry, including all queue/authentication/ack waits.
    pub timeout_millis: u64,
}
pub(crate) fn text(value: &str, max: usize) -> bool {
    !value.is_empty() && value.len() <= max && value.bytes().all(|b| (0x21..=0x7e).contains(&b))
}
pub(crate) fn subject(value: &str) -> bool {
    text(value, 128)
        && value.split('.').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
        })
        && !value.starts_with('_')
}
impl NatsConfig {
    pub fn validate(&self) -> Result<()> {
        self.endpoint.validate()?;
        if self.format_version != 1
            || self.topics.is_empty()
            || self.topics.capacity() > 16
            || self.extra_roots.capacity() > 8
            || (!self.public_roots && self.extra_roots.is_empty())
            || self
                .extra_roots
                .iter()
                .any(|c| c.is_empty() || c.capacity() > 16384)
            || self.extra_roots.iter().map(Vec::capacity).sum::<usize>() > 65536
            || !text(&self.idempotency_namespace, 128)
            || self.idempotency_namespace.capacity() > 128
            || !(1..=262_144).contains(&self.maximum_payload_bytes)
            || !(10..=30000).contains(&self.timeout_millis)
        {
            return Err(EventError::InvalidEvent);
        }
        for (i, row) in self.topics.iter().enumerate() {
            if !text(&row.tenant, 128)
                || !subject(&row.topic)
                || !subject(&row.subject)
                || !subject(&row.stream)
                || row.stream.contains('.')
                || [&row.tenant, &row.topic, &row.subject, &row.stream]
                    .iter()
                    .any(|s| s.capacity() > 128)
                || !(1000..=86_400_000).contains(&row.duplicate_window_millis)
                || self.topics[..i].iter().any(|old| {
                    (old.tenant == row.tenant && old.topic == row.topic)
                        || (old.tenant != row.tenant && old.subject == row.subject)
                        || (old.stream == row.stream
                            && old.duplicate_window_millis != row.duplicate_window_millis)
                })
            {
                return Err(EventError::InvalidEvent);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_endpoint_capacity_cannot_bypass_the_configuration_bound() {
        let mut config = NatsConfig {
            format_version: 1,
            endpoint: NatsEndpoint {
                server_name: "broker.example".into(),
                peer: "1.1.1.1:4222".parse().unwrap(),
                allow_non_public_peer: false,
            },
            public_roots: true,
            extra_roots: vec![],
            topics: vec![TopicMapping {
                tenant: "test".into(),
                topic: "orders".into(),
                subject: "orders".into(),
                stream: "ORDERS".into(),
                duplicate_window_millis: 1000,
            }],
            idempotency_namespace: "test".into(),
            maximum_payload_bytes: 1024,
            timeout_millis: 1000,
        };
        assert!(config.validate().is_ok());
        let mut name = String::with_capacity(1024);
        name.push_str("broker.example");
        config.endpoint.server_name = name;
        assert_eq!(config.validate(), Err(EventError::InvalidEvent));
    }
}
