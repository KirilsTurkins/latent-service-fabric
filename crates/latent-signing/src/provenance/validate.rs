use super::{
    BuildObservation, BuildRecipe, ProvenanceLimits, C_GUEST_BUILD_TYPE, GO_CAPSULE_BUILD_TYPE,
    PROVENANCE_BUILD_TYPE, RUST_CAPSULE_BUILD_TYPE, RUST_GUEST_BUILD_TYPE,
    TYPESCRIPT_CAPSULE_BUILD_TYPE,
};
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
    if value.format_version != 1 || !super::supported_build_type(&value.build_type) {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    validate_repository(&value.source.repository)?;
    validate_revision(&value.source.revision)?;
    validate_digest(&value.source.snapshot_digest)?;
    validate_digest(&value.component_digest)?;
    if value.build_type != PROVENANCE_BUILD_TYPE
        && value.source.revision != value.source.snapshot_digest[7..]
    {
        return Err(SignatureFailure::IntegrityMismatch.into());
    }
    if value.source.repository_trust != "operator-asserted"
        || value.source.capture
            != if value.build_type == PROVENANCE_BUILD_TYPE {
                "git-archive-allowlist"
            } else {
                "explicit-input-files"
            }
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
        || value.dependency_completeness
            != if value.build_type == PROVENANCE_BUILD_TYPE {
                "lockfile-only"
            } else {
                "declared-inputs-incomplete"
            }
    {
        return Err(SignatureFailure::MalformedProvenance.into());
    }
    validate_recipe(&value.build_type, &value.parameters)?;
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
        "build-recipe",
        "toolchain-config",
        "wasm-tools",
    ] {
        if !names.iter().any(|name| name.as_str() == required) {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
    }
    let tool_materials: &[&str] = match value.build_type.as_str() {
        PROVENANCE_BUILD_TYPE => &["dependency-lock", "cargo", "rustc"],
        RUST_GUEST_BUILD_TYPE => &["dependency-lock", "cargo", "rustc", "wit-bindgen"],
        RUST_CAPSULE_BUILD_TYPE => &[
            "dependency-lock",
            "cargo",
            "rustc",
            "wit-bindgen",
            "contracts-tool",
            "packager",
            "package-inputs",
        ],
        C_GUEST_BUILD_TYPE => &["zig", "wit-bindgen"],
        TYPESCRIPT_CAPSULE_BUILD_TYPE => &[
            "dependency-lock",
            "node",
            "compiler-inputs",
            "contracts-tool",
            "packager",
            "package-inputs",
        ],
        GO_CAPSULE_BUILD_TYPE => &[
            "go",
            "componentize-go",
            "dependency-lock",
            "contracts-tool",
            "packager",
            "package-inputs",
        ],
        _ => unreachable!("profile checked above"),
    };
    for required in tool_materials {
        if !names.iter().any(|name| name.as_str() == *required) {
            return Err(SignatureFailure::MalformedProvenance.into());
        }
    }
    Ok(())
}

fn validate_recipe(build_type: &str, parameters: &BuildRecipe) -> SignatureResult<()> {
    let valid_recipe = match (build_type, parameters) {
        (PROVENANCE_BUILD_TYPE | RUST_GUEST_BUILD_TYPE, BuildRecipe::Rust(p)) => {
            let example = if build_type == PROVENANCE_BUILD_TYPE {
                p.cargo_example == "echo-capsule"
            } else {
                matches!(
                    p.cargo_example.as_str(),
                    "guest-http"
                        | "guest-streaming"
                        | "guest-blob"
                        | "guest-secrets"
                        | "guest-events"
                        | "guest-random"
                        | "guest-metrics"
                        | "guest-service"
                        | "guest-callee"
                )
            };
            example
                && p.cargo_package == "latent-toolchain-smoke"
                && p.target == "wasm32-unknown-unknown"
                && p.profile == "release"
                && p.locked
                && !p.incremental
        }
        (RUST_CAPSULE_BUILD_TYPE, BuildRecipe::RustCapsule(p)) => {
            !p.cargo_package.is_empty()
                && p.cargo_package.len() <= 64
                && p.cargo_package.as_bytes()[0].is_ascii_lowercase()
                && p.cargo_package.split('-').all(|part| {
                    !part.is_empty()
                        && part
                            .bytes()
                            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
                })
                && p.manifest_path == "Cargo.toml"
                && p.crate_type == "cdylib"
                && p.target == "wasm32-unknown-unknown"
                && p.profile == "release"
                && p.locked
                && !p.incremental
        }
        (C_GUEST_BUILD_TYPE, BuildRecipe::C(p)) => {
            p.compiler == "zig-cc"
                && matches!(
                    p.fixture.as_str(),
                    "blob"
                        | "callee"
                        | "events"
                        | "http"
                        | "metrics"
                        | "random"
                        | "secrets"
                        | "service"
                        | "streaming"
                        | "application"
                )
                && p.target == "wasm32-wasi"
                && p.optimization == "O2"
        }
        (TYPESCRIPT_CAPSULE_BUILD_TYPE, BuildRecipe::TypeScriptCapsule(p)) => {
            p.compiler == "componentize-js"
                && p.bindings == "jco"
                && p.language == "typescript"
                && p.target == "wasm32-component"
                && p.runtime == "spidermonkey"
                && !p.ambient_wasi
        }
        (GO_CAPSULE_BUILD_TYPE, BuildRecipe::GoCapsule(p)) => {
            !p.go_package.is_empty()
                && p.go_package.len() <= 64
                && p.go_package.as_bytes()[0].is_ascii_lowercase()
                && p.go_package.split('-').all(|part| {
                    !part.is_empty()
                        && part
                            .bytes()
                            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
                })
                && p.compiler == "componentize-go"
                && p.target == "wasm32-wasip1"
                && p.runtime == "go-component-async-v1"
                && p.locked
                && !p.ambient_wasi
        }
        _ => false,
    };
    if !valid_recipe {
        return Err(SignatureFailure::PredicateDisallowed.into());
    }
    Ok(())
}
