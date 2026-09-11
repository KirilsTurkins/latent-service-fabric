use clap::Parser;
use std::net::SocketAddr;

pub(super) const MAXIMUM_MESSAGE_BYTES: usize = 1024 * 1024 + 16 * 1024;
pub(super) const MAXIMUM_IDENTIFIER_BYTES: usize = 512;
pub(super) const MAXIMUM_TIMEOUT_MILLIS: u64 = 5000;

/// The token is never included in Debug output or configuration diagnostics.
#[derive(Parser)]
#[command(about = "Minimal native reference for the optimization benchmark")]
pub(super) struct Args {
    #[arg(long, default_value = "127.0.0.1:0")]
    pub listen: SocketAddr,
    #[arg(long)]
    pub token: String,
    #[arg(long, default_value = "optimization")]
    pub tenant: String,
    #[arg(long, value_delimiter = ',', default_value = "optimization/workloads")]
    pub services: Vec<String>,
    #[arg(long, default_value_t = 4)]
    pub concurrency: usize,
    #[arg(long, default_value_t = MAXIMUM_TIMEOUT_MILLIS)]
    pub timeout_ms: u64,
}

impl Args {
    pub(super) fn validate(&self) -> Result<(), ()> {
        if !self.listen.ip().is_loopback()
            || !(32..=256).contains(&self.token.len())
            || !self
                .token
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            || self.tenant.is_empty()
            || self.tenant.len() > MAXIMUM_IDENTIFIER_BYTES
            || !self
                .tenant
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            || !(1..=64).contains(&self.concurrency)
            || !(1..=MAXIMUM_TIMEOUT_MILLIS).contains(&self.timeout_ms)
            || self.services.is_empty()
            || self.services.len() > 32
        {
            return Err(());
        }
        for (index, service) in self.services.iter().enumerate() {
            if !valid_service(service) || self.services[..index].contains(service) {
                return Err(());
            }
        }
        Ok(())
    }
}

fn valid_service(service: &str) -> bool {
    if service == "optimization/workloads" {
        return true;
    }
    service
        .strip_prefix("optimization/workloads-")
        .is_some_and(|suffix| {
            suffix
                .parse::<u32>()
                .is_ok_and(|index| (1..=31).contains(&index) && suffix == index.to_string())
        })
}
