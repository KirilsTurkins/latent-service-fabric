//! Explicit bounded credential profiles. Secret-bearing values do not implement Debug.

mod decode;
mod model;
#[cfg(test)]
mod tests;
mod validation;

use std::io::{self, Read};
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
    pub manifest_profile: latent_manifest::ManifestValidationProfile,
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
    if cli.expect_config_digest_stdin {
        verify_opened_config(&bytes, io::stdin().lock())?;
    }
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
        manifest_profile: cli.manifest_profile()?,
    })
}

fn verify_opened_config(bytes: &[u8], mut input: impl Read) -> Result<(), Failure> {
    // The first 72 stdin bytes are a canonical sha256: digest and newline.
    // The remaining stdin, if any, is reserved for the command's own input.
    let mut expected = [0_u8; 72];
    input.read_exact(&mut expected).map_err(|_| changed())?;
    let actual = latent_artifacts::content_digest(bytes).0;
    if expected[71] != b'\n' || &expected[..71] != actual.as_bytes() {
        return Err(changed());
    }
    Ok(())
}

fn changed() -> Failure {
    Failure::local(
        "configuration-identity-changed",
        "Credential configuration did not match the selected owner; no request was sent.",
    )
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-configuration",
        "Credential configuration is invalid or exceeds its limits.",
    )
}
