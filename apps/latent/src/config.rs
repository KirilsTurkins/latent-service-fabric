//! Explicit bounded credential profiles. Secret-bearing values do not implement Debug.

mod decode;
mod model;
#[cfg(test)]
mod tests;
mod validation;

use std::path::Path;
use std::time::Duration;

use crate::args::Cli;
use crate::error::Failure;

pub use model::InputLimits;

pub struct ResolvedConfig {
    pub endpoint: String,
    pub tenant: String,
    pub token: String,
    pub connect_timeout: Duration,
    pub rpc_timeout: Duration,
    pub limits: InputLimits,
}

pub fn resolve(cli: &Cli) -> Result<ResolvedConfig, Failure> {
    let path = cli.config.as_ref().ok_or_else(|| {
        Failure::local(
            "configuration-required",
            "Remote commands require an explicit credential configuration.",
        )
    })?;
    if path == Path::new("-") {
        return Err(invalid());
    }
    let bytes = crate::input::read(path, decode::MAXIMUM_CONFIG_BYTES, "configuration")?;
    let document = decode::document(&bytes)?;
    validation::document(&document)?;
    let requested = cli
        .profile
        .as_deref()
        .or(document.default_profile.as_deref());
    let selected = match requested {
        Some(name) => document
            .profiles
            .into_iter()
            .find(|profile| profile.name == name),
        None if document.profiles.len() == 1 => document.profiles.into_iter().next(),
        None => {
            return Err(Failure::local(
                "profile-required",
                "Select one configured profile.",
            ))
        }
    }
    .ok_or_else(|| Failure::local("unknown-profile", "The selected profile does not exist."))?;
    let endpoint = cli.endpoint.as_ref().unwrap_or(&selected.endpoint);
    let tenant = cli.tenant.as_ref().unwrap_or(&selected.tenant);
    validation::endpoint(endpoint)?;
    validation::tenant(tenant)?;
    let connect = cli
        .connect_timeout_ms
        .unwrap_or(selected.connect_timeout_millis);
    let rpc = cli.rpc_timeout_ms.unwrap_or(selected.rpc_timeout_millis);
    validation::timeout(connect)?;
    validation::timeout(rpc)?;
    Ok(ResolvedConfig {
        endpoint: endpoint.clone(),
        tenant: tenant.clone(),
        token: selected.token,
        connect_timeout: Duration::from_millis(connect),
        rpc_timeout: Duration::from_millis(rpc),
        limits: selected.limits,
    })
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-configuration",
        "Credential configuration is invalid or exceeds its limits.",
    )
}
