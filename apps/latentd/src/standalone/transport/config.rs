use std::net::SocketAddr;
use std::time::Duration;

use latent_core::{InvocationPrincipal, PlatformError, PrincipalKind};

use super::failure;

#[derive(Clone)]
pub struct TransportCredential {
    pub token: String,
    pub principal: InvocationPrincipal,
}

/// Fixed listener/dispatch ceilings. Credentials are intentionally not Debug.
#[derive(Clone)]
pub struct TransportConfig {
    pub bind: SocketAddr,
    pub maximum_connections: usize,
    pub maximum_rpcs: usize,
    pub reserved_cancel_status_rpcs: usize,
    pub maximum_control_jobs: usize,
    pub maximum_header_bytes: u32,
    pub maximum_streams_per_connection: u32,
    pub request_timeout: Duration,
    pub shutdown_timeout: Duration,
    pub credentials: Vec<TransportCredential>,
}

impl TransportConfig {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if !self.bind.ip().is_loopback()
            || !(1..=4096).contains(&self.maximum_connections)
            || !(2..=65_536).contains(&self.maximum_rpcs)
            || self.reserved_cancel_status_rpcs == 0
            || self.reserved_cancel_status_rpcs >= self.maximum_rpcs
            || self.maximum_control_jobs == 0
            || self.maximum_control_jobs > self.maximum_rpcs - self.reserved_cancel_status_rpcs
            || !(1024..=65_536).contains(&self.maximum_header_bytes)
            || self.maximum_streams_per_connection == 0
            || self.maximum_streams_per_connection > 65_536
            || self.request_timeout.is_zero()
            || self.request_timeout > Duration::from_hours(24)
            || self.shutdown_timeout.is_zero()
            || self.shutdown_timeout > Duration::from_mins(1)
            || self.credentials.is_empty()
            || self.credentials.len() > 64
            || self.credentials.capacity() > 64
        {
            return Err(invalid());
        }
        for (index, credential) in self.credentials.iter().enumerate() {
            if !bounded_identifier(&credential.token, 512)
                || !credential.token.is_ascii()
                || self.credentials[..index]
                    .iter()
                    .any(|other| other.token == credential.token)
            {
                return Err(invalid());
            }
            validate_principal(&credential.principal)?;
        }
        Ok(())
    }
}

fn validate_principal(value: &InvocationPrincipal) -> Result<(), PlatformError> {
    if value.kind == PrincipalKind::Anonymous
        || !bounded_identifier(&value.subject, 512)
        || !value
            .tenant
            .as_ref()
            .is_some_and(|tenant| bounded_identifier(&tenant.0, 512))
        || value
            .service
            .as_ref()
            .is_some_and(|service| !bounded_identifier(&service.0, 512))
        || (value.kind == PrincipalKind::Service && value.service.is_none())
        || value.claims.len() > 64
    {
        return Err(invalid());
    }
    let mut remaining = 32 * 1024_usize;
    for (key, value) in &value.claims {
        if key.capacity() > 4096 || value.capacity() > 4096 {
            return Err(invalid());
        }
        remaining = remaining
            .checked_sub(key.capacity())
            .and_then(|bytes| bytes.checked_sub(value.capacity()))
            .ok_or_else(invalid)?;
    }
    Ok(())
}

fn bounded_identifier(value: &String, maximum: usize) -> bool {
    value.capacity() <= maximum
        && !value.is_empty()
        && !value
            .chars()
            .any(|value| value.is_control() || value.is_whitespace())
}

fn invalid() -> PlatformError {
    failure(
        latent_core::PlatformErrorCode::InvalidArgument,
        "invalid standalone transport configuration",
    )
}
