//! Pinned WIT source graph. Parsing and content association do not establish
//! that the sources describe a given compiled component or publisher.
use std::collections::{BTreeMap, BTreeSet};

use latent_core::{ArtifactBlobDigest, PlatformError};
use serde::{Deserialize, Serialize};

use super::{invalid, LayerRole, PackageConfig, PackageKind, PackageLimits};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WitLockedPackage {
    pub id: String,
    pub source_path: String,
    #[serde(with = "digest")]
    pub digest: ArtifactBlobDigest,
    pub dependencies: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WitLock {
    pub format_version: u32,
    pub world: String,
    #[serde(with = "digest")]
    pub contracts_digest: ArtifactBlobDigest,
    pub packages: Vec<WitLockedPackage>,
}

/// Decodes the closed, bounded v1 source graph, including reference/cycle checks.
pub fn decode_wit_lock(bytes: &[u8], limits: PackageLimits) -> Result<WitLock, PlatformError> {
    let value = super::parse::parse(bytes, limits)?;
    let lock: WitLock =
        serde_json::from_value(value).map_err(|_| invalid("invalid-wit-lock-json"))?;
    validate_graph(&lock, limits)?;
    Ok(lock)
}

/// Emits deterministic JSON. The byte-limited encoder rejects excess output.
pub fn encode_wit_lock(lock: &WitLock, limits: PackageLimits) -> Result<Vec<u8>, PlatformError> {
    validate_graph(lock, limits)?;
    super::codec::encode_bounded(lock, limits)
}

/// Associates a valid lock with the capsule's contracts and pinned WIT source
/// assets. Source bytes must additionally pass the ordinary layer-byte checks.
/// WIT syntax and compiled-component agreement are packaging/admission checks.
pub fn validate_wit_lock(
    config: &PackageConfig,
    lock: &WitLock,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    super::validate::config(config, limits)?;
    validate_graph(lock, limits)?;
    if config.kind != PackageKind::Capsule {
        return Err(invalid("wit-lock-requires-capsule"));
    }
    let contracts = config
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Contracts)
        .ok_or_else(|| invalid("wit-lock-contracts-missing"))?;
    if contracts.digest != lock.contracts_digest {
        return Err(invalid("wit-lock-contracts-mismatch"));
    }
    for package in &lock.packages {
        let source = config
            .layers
            .iter()
            .find(|layer| layer.path == package.source_path)
            .ok_or_else(|| invalid("wit-lock-source-missing"))?;
        if source.role != LayerRole::Asset
            || source.media_type != "text/plain"
            || source.digest != package.digest
        {
            return Err(invalid("wit-lock-source-mismatch"));
        }
    }
    Ok(())
}

fn validate_graph(lock: &WitLock, limits: PackageLimits) -> Result<(), PlatformError> {
    limits.validate()?;
    if lock.format_version != 1
        || lock.packages.is_empty()
        || lock.packages.len() > limits.max_layers
    {
        return Err(invalid("invalid-wit-lock-shape"));
    }
    let root = world_package(&lock.world, limits)?;
    let mut ids = BTreeMap::new();
    let mut paths = BTreeSet::new();
    let mut previous: Option<&str> = None;
    for (index, package) in lock.packages.iter().enumerate() {
        package_id(&package.id, limits)?;
        if previous.is_some_and(|value| value >= package.id.as_str()) {
            return Err(invalid("unordered-wit-lock-packages"));
        }
        previous = Some(&package.id);
        ids.insert(package.id.as_str(), index);
        super::paths::path(&package.source_path, limits)?;
        if !paths.insert(package.source_path.to_ascii_lowercase()) {
            return Err(invalid("duplicate-wit-lock-source"));
        }
        if package.dependencies.len() > limits.max_layers {
            return Err(super::exceeded("wit-lock-dependency-limit"));
        }
        let mut prior: Option<&str> = None;
        for dependency in &package.dependencies {
            package_id(dependency, limits)?;
            if prior.is_some_and(|value| value >= dependency.as_str()) {
                return Err(invalid("unordered-wit-lock-dependencies"));
            }
            prior = Some(dependency);
        }
    }
    if !ids.contains_key(root.as_str()) {
        return Err(invalid("wit-lock-world-package-missing"));
    }
    for package in &lock.packages {
        if package
            .dependencies
            .iter()
            .any(|dependency| !ids.contains_key(dependency.as_str()))
        {
            return Err(invalid("wit-lock-dependency-missing"));
        }
    }
    let mut state = vec![0_u8; lock.packages.len()];
    for index in 0..lock.packages.len() {
        visit(index, &lock.packages, &ids, &mut state)?;
    }
    Ok(())
}

// Graph depth is capped by the hard 256-package ceiling, independently of JSON
// nesting. All indexes and edges are checked before this traversal begins.
fn visit(
    index: usize,
    packages: &[WitLockedPackage],
    ids: &BTreeMap<&str, usize>,
    state: &mut [u8],
) -> Result<(), PlatformError> {
    match state[index] {
        1 => return Err(invalid("cyclic-wit-lock")),
        2 => return Ok(()),
        _ => {}
    }
    state[index] = 1;
    for dependency in &packages[index].dependencies {
        visit(ids[dependency.as_str()], packages, ids, state)?;
    }
    state[index] = 2;
    Ok(())
}

fn package_id(value: &str, limits: PackageLimits) -> Result<(), PlatformError> {
    if value.len() > 512 || value.len() > limits.max_string_bytes {
        return Err(invalid("invalid-wit-package-id"));
    }
    let (name, version) = value
        .rsplit_once('@')
        .ok_or_else(|| invalid("invalid-wit-package-id"))?;
    let (namespace, package) = name
        .split_once(':')
        .ok_or_else(|| invalid("invalid-wit-package-id"))?;
    if !identifier(namespace) || !identifier(package) || !super::paths::version(version) {
        return Err(invalid("invalid-wit-package-id"));
    }
    Ok(())
}

fn world_package(value: &str, limits: PackageLimits) -> Result<String, PlatformError> {
    if value.len() > 512 || value.len() > limits.max_string_bytes {
        return Err(invalid("invalid-wit-world-id"));
    }
    let (name, version) = value
        .rsplit_once('@')
        .ok_or_else(|| invalid("invalid-wit-world-id"))?;
    let (package, world) = name
        .split_once('/')
        .ok_or_else(|| invalid("invalid-wit-world-id"))?;
    if !identifier(world) {
        return Err(invalid("invalid-wit-world-id"));
    }
    let id = format!("{package}@{version}");
    package_id(&id, limits)?;
    Ok(id)
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_lowercase()
        && value.as_bytes()[value.len() - 1].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
}

mod digest {
    use super::{ArtifactBlobDigest, Deserialize};
    pub fn serialize<S: serde::Serializer>(
        value: &ArtifactBlobDigest,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(value.as_str())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<ArtifactBlobDigest, D::Error> {
        String::deserialize(deserializer)?
            .parse()
            .map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
#[path = "wit_lock_tests.rs"]
mod tests;
