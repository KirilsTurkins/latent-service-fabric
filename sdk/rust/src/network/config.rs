use super::{FailureKind, RpcFailure};
use latent_core::TenantId;
use std::{net::SocketAddr, time::Duration};
use tonic::metadata::{Ascii, MetadataValue};
use zeroize::Zeroizing;

#[derive(Clone, Copy, Debug)]
pub struct ClientLimits {
    pub maximum_calls: usize,
    pub maximum_request_bytes: usize,
    pub maximum_response_bytes: usize,
    pub maximum_reserved_bytes: usize,
    pub connect_timeout: Duration,
    pub rpc_timeout: Duration,
}

impl Default for ClientLimits {
    fn default() -> Self {
        Self {
            maximum_calls: 8,
            maximum_request_bytes: 256 * 1024,
            maximum_response_bytes: 256 * 1024,
            maximum_reserved_bytes: 16 * 1024 * 1024,
            connect_timeout: Duration::from_secs(3),
            rpc_timeout: Duration::from_secs(10),
        }
    }
}

impl ClientLimits {
    pub(super) fn validate(self) -> Result<(), RpcFailure> {
        if !(1..=32).contains(&self.maximum_calls)
            || !(1..=4 * 1024 * 1024).contains(&self.maximum_request_bytes)
            || !(1..=4 * 1024 * 1024).contains(&self.maximum_response_bytes)
            || !(1..=64 * 1024 * 1024).contains(&self.maximum_reserved_bytes)
            || self.connect_timeout.is_zero()
            || self.rpc_timeout.is_zero()
            || self.connect_timeout > Duration::from_mins(5)
            || self.rpc_timeout > Duration::from_mins(5)
        {
            return Err(RpcFailure::local(FailureKind::InvalidConfiguration));
        }
        Ok(())
    }
}

pub struct ClientConfig {
    pub endpoint: SocketAddr,
    pub tenant: TenantId,
    pub credential: Zeroizing<String>,
    pub limits: ClientLimits,
}

impl std::fmt::Debug for ClientConfig {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ClientConfig")
            .field("limits", &self.limits)
            .finish_non_exhaustive()
    }
}

impl ClientConfig {
    pub(super) fn validate(&self) -> Result<MetadataValue<Ascii>, RpcFailure> {
        self.limits.validate()?;
        let tenant = self.tenant.0.as_bytes();
        if !self.endpoint.ip().is_loopback()
            || self.endpoint.port() == 0
            || tenant.is_empty()
            || tenant.len() > 128
            || !tenant[0].is_ascii_alphanumeric()
            || !tenant[tenant.len() - 1].is_ascii_alphanumeric()
            || !tenant
                .iter()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(byte))
            || !(32..=256).contains(&self.credential.len())
            || !self
                .credential
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
        {
            return Err(RpcFailure::local(FailureKind::InvalidConfiguration));
        }
        let value = Zeroizing::new(format!("Bearer {}", self.credential.as_str()));
        let mut value = MetadataValue::try_from(value.as_str())
            .map_err(|_| RpcFailure::local(FailureKind::InvalidConfiguration))?;
        value.set_sensitive(true);
        Ok(value)
    }
}
