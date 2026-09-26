//! Source-authoritative authoring inputs. These are not build or admission proofs.
use std::collections::BTreeMap;

use latent_artifacts::package::{artifact_blob_digest, WitLock, WitLockedPackage};
use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_core::PlatformError;
use wit_parser::UnresolvedPackageGroup;

use super::{
    arena, compare, exhausted, host, invalid, lexical, limits, projection, sources, SemanticLimits,
};

/// Deterministic inputs derived from bounded, pinned WIT sources. The ordinary
/// packager must still compare them with the actual compiled component. No
/// authority, provider, executable, parser arena or guest state is retained.
#[derive(Debug, Clone)]
pub struct CapsuleContractInputs {
    contracts: Vec<u8>,
    lock: WitLock,
    imports: Vec<String>,
    exports: Vec<String>,
}

impl CapsuleContractInputs {
    #[must_use]
    pub fn contracts(&self) -> &[u8] {
        &self.contracts
    }

    #[must_use]
    pub fn wit_lock(&self) -> &WitLock {
        &self.lock
    }

    #[must_use]
    pub fn imports(&self) -> &[String] {
        &self.imports
    }

    #[must_use]
    pub fn exports(&self) -> &[String] {
        &self.exports
    }
}

/// Derive exact descriptor and lock documents from authoritative WIT, rather
/// than asking authors to maintain a second type definition in JSON. Each map
/// entry is one complete, versioned WIT package at a portable package-layer path.
/// Dependencies must be supplied explicitly, version-pinned and acyclic. Only
/// the current packaging profile is accepted; unsupported shapes are errors.
pub fn derive_capsule_contracts(
    world: &str,
    files: &BTreeMap<String, &[u8]>,
    bounds: SemanticLimits,
) -> Result<CapsuleContractInputs, PlatformError> {
    bounds.validate()?;
    limits::name(world, bounds)?;
    if files.is_empty() || files.len() > bounds.max_wit_packages {
        return Err(exhausted("authoring-wit-package-limit"));
    }
    let (mut bytes, mut tokens) = (0, 0);
    for (path, source) in files {
        limits::name(path, bounds)?;
        limits::add(&mut bytes, source.len(), bounds.max_total_wit_bytes)?;
        if source.len() > bounds.max_wit_source_bytes {
            return Err(exhausted("wit-source-byte-limit"));
        }
        let text = std::str::from_utf8(source).map_err(|_| invalid("wit-source-not-utf8"))?;
        lexical::preflight(text, &mut tokens, bounds)?;
    }
    let mut packages = BTreeMap::new();
    let mut counts = arena::Counts::default();
    for (path, source) in files {
        let text = std::str::from_utf8(source).map_err(|_| invalid("wit-source-not-utf8"))?;
        let group =
            UnresolvedPackageGroup::parse(path, text).map_err(|_| invalid("invalid-wit-source"))?;
        if !group.nested.is_empty() || group.main.name.version.is_none() {
            return Err(invalid("authoring-requires-versioned-package"));
        }
        arena::unresolved(&group.main, &mut counts, bounds)?;
        let mut dependencies = Vec::new();
        for dependency in group.main.foreign_deps.keys() {
            if dependency.version.is_none() {
                return Err(invalid("unpinned-wit-dependency"));
            }
            dependencies.push(dependency.to_string());
        }
        dependencies.sort();
        let id = group.main.name.to_string();
        let entry = WitLockedPackage {
            id: id.clone(),
            source_path: path.clone(),
            digest: artifact_blob_digest(source),
            dependencies,
        };
        if packages.insert(id, entry).is_some() {
            return Err(invalid("duplicate-authoring-wit-package"));
        }
    }
    let mut lock = WitLock {
        format_version: 1,
        world: world.to_owned(),
        // A private temporary association, replaced with the exact generated
        // bytes before anything is returned to the caller.
        contracts_digest: artifact_blob_digest(b""),
        packages: packages.into_values().collect(),
    };
    let (resolve, selected) = sources::resolve(&lock, files, bounds)?;
    let surface = compare::surface(&resolve, selected, bounds)?;
    // Self-comparison traverses the complete export type graph, including the
    // definitions behind named records, before the legacy projection is made.
    compare::worlds(&resolve, &surface, &resolve, &surface, bounds)?;
    host::validate(&resolve, &surface.imports, bounds)?;
    let descriptors = projection::generate(&resolve, selected, bounds)?;
    let contracts = encode_contract_metadata(&descriptors, ContractMetadataLimits::default())?;
    if contracts.len() > bounds.max_summary_bytes {
        return Err(exhausted("authoring-contract-byte-limit"));
    }
    lock.contracts_digest = artifact_blob_digest(&contracts);
    Ok(CapsuleContractInputs {
        contracts,
        lock,
        imports: surface.imports.into_keys().collect(),
        exports: surface.exports.into_keys().collect(),
    })
}

#[cfg(test)]
mod tests;
