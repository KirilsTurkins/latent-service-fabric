use super::{BuildObservation, ProvenanceLimits, PROVENANCE_BUILD_TYPE};
use crate::{SignatureFailure, SignatureResult};
use std::collections::BTreeSet;

pub(crate) fn validate_digest(value: &str) -> SignatureResult<()> {
    if value.len() > 71 {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if value.len() != 71 || !value.starts_with("sha256:") || !hex(&value[7..]) {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    Ok(())
}
pub(crate) fn validate_revision(value: &str) -> SignatureResult<()> {
    if value.len() > 64 {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if !matches!(value.len(), 40 | 64) || !hex(value) {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    Ok(())
}
fn hex(value: &str) -> bool {
    value
        .bytes()
        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Closed public source label, not a network locator: HTTPS, DNS host, ASCII
/// portable path; no credentials, port, escaping, query, fragment or local path.
pub(crate) fn validate_repository(value: &str) -> SignatureResult<()> {
    if value.len() > 512 {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let tail = value
        .strip_prefix("https://")
        .ok_or(SignatureFailure::MalformedProvenance)?;
    let (host, path) = tail
        .split_once('/')
        .ok_or(SignatureFailure::MalformedProvenance)?;
    if host.is_empty()
        || host.len() > 253
        || path.is_empty()
        || host.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
        || path.split('/').any(|part| {
            part.is_empty()
                || matches!(part, "." | "..")
                || !part
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        })
    {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    Ok(())
}

pub(crate) fn validate_observation(
    value: &BuildObservation,
    limits: ProvenanceLimits,
) -> SignatureResult<()> {
    limits.validate()?;
    if value.materials.len() > limits.max_materials {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if value.format_version != 1 || value.build_type != PROVENANCE_BUILD_TYPE {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    validate_repository(&value.source.repository)?;
    validate_revision(&value.source.revision)?;
    validate_digest(&value.source.snapshot_digest)?;
    validate_digest(&value.component_digest)?;
    if value.source.repository_trust != "operator-asserted"
        || value.source.capture != "git-archive-allowlist"
        || value.component_size == 0
        || value.component_size > 64 * 1024 * 1024
        || value
            .finished_at
            .checked_sub(value.started_at)
            .is_none_or(|duration| duration > 3600)
        || !matches!(
            value.reproducibility.as_str(),
            "not-checked" | "two-build-byte-equality"
        )
        || value.hermetic
        || value.dependency_completeness != "lockfile-only"
    {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    let p = &value.parameters;
    if p.cargo_package != "latent-toolchain-smoke"
        || p.cargo_example != "echo-capsule"
        || p.target != "wasm32-unknown-unknown"
        || p.profile != "release"
        || !p.locked
        || p.incremental
    {
        return Err(SignatureFailure::PredicateDisallowed.into());
    }
    let mut names = BTreeSet::new();
    for material in &value.materials {
        if material.name.len() > 128 {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        if !material
            .name
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
            || !material
                .name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            || material.size == 0
            || material.size > 256 * 1024 * 1024
            || !names.insert(&material.name)
        {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
        validate_digest(&material.digest)?;
        if material.name == "source-snapshot" && material.digest != value.source.snapshot_digest {
            return Err(SignatureFailure::IntegrityMismatch.into());
        }
    }
    for required in [
        "source-snapshot",
        "dependency-lock",
        "build-recipe",
        "toolchain-config",
        "cargo",
        "rustc",
        "wasm-tools",
    ] {
        if !names.iter().any(|name| name.as_str() == required) {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
    }
    Ok(())
}
