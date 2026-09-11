use super::{arena, exhausted, invalid, lexical, limits, SemanticLimits};
use latent_artifacts::package::{
    artifact_blob_digest, encode_wit_lock, PackageLimits, WitLock, WitLockedPackage,
};
use latent_core::PlatformError;
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::{Resolve, UnresolvedPackageGroup, WorldId};

pub(super) fn resolve(
    lock: &WitLock,
    sources: &BTreeMap<String, &[u8]>,
    limits: SemanticLimits,
) -> Result<(Resolve, WorldId), PlatformError> {
    if sources.len() > limits.max_wit_packages || sources.len() != lock.packages.len() {
        return Err(invalid("wit-source-set-mismatch"));
    }
    // Validate caller-owned lock structure before cloning names or traversing edges.
    encode_wit_lock(
        lock,
        PackageLimits {
            max_layers: limits.max_wit_packages,
            ..PackageLimits::default()
        },
    )?;
    limits::name(&lock.world, limits)?;
    let expected: BTreeSet<_> = lock
        .packages
        .iter()
        .map(|entry| entry.source_path.as_str())
        .collect();
    if sources.keys().any(|path| !expected.contains(path.as_str())) {
        return Err(invalid("wit-source-set-mismatch"));
    }
    let mut total_bytes = 0;
    let mut tokens = 0;
    // Charge every input before parsing any package or constructing a Resolve.
    for entry in &lock.packages {
        let bytes = sources
            .get(&entry.source_path)
            .ok_or_else(|| invalid("wit-source-missing"))?;
        limits::add(&mut total_bytes, bytes.len(), limits.max_total_wit_bytes)?;
        if bytes.len() > limits.max_wit_source_bytes {
            return Err(exhausted("wit-source-byte-limit"));
        }
        if artifact_blob_digest(bytes) != entry.digest {
            return Err(invalid("wit-source-digest-mismatch"));
        }
        let source = std::str::from_utf8(bytes).map_err(|_| invalid("wit-source-not-utf8"))?;
        lexical::preflight(source, &mut tokens, limits)?;
    }
    let mut groups = BTreeMap::new();
    let mut counts = arena::Counts::default();
    for entry in &lock.packages {
        limits::name(&entry.id, limits)?;
        let source = std::str::from_utf8(sources[&entry.source_path])
            .map_err(|_| invalid("wit-source-not-utf8"))?;
        let group = UnresolvedPackageGroup::parse(&entry.source_path, source)
            .map_err(|_| invalid("invalid-wit-source"))?;
        identity(&group, entry)?;
        arena::unresolved(&group.main, &mut counts, limits)?;
        groups.insert(entry.id.clone(), group);
    }
    // A world may copy interface/type references from other worlds. Reject a
    // conservative expansion charge before the resolver materializes that graph.
    let expanded = counts
        .nodes
        .checked_mul(counts.worlds.saturating_add(1))
        .ok_or_else(|| exhausted("wit-resolution-work-limit"))?;
    if expanded > limits.max_type_nodes {
        return Err(exhausted("wit-resolution-work-limit"));
    }
    let mut resolve = Resolve::default();
    let mut remaining: BTreeMap<_, _> = lock
        .packages
        .iter()
        .map(|entry| (entry.id.as_str(), entry))
        .collect();
    let mut inserted = BTreeSet::new();
    let mut packages = Vec::new();
    while !remaining.is_empty() {
        let next = remaining
            .iter()
            .find(|(_, entry)| {
                entry
                    .dependencies
                    .iter()
                    .all(|id| inserted.contains(id.as_str()))
            })
            .map(|(id, _)| *id)
            .ok_or_else(|| invalid("cyclic-wit-source-graph"))?;
        let group = groups
            .remove(next)
            .ok_or_else(|| invalid("wit-source-missing"))?;
        let package = resolve
            .push_group(group)
            .map_err(|_| invalid("unresolved-wit-source"))?;
        arena::resolved(&resolve, limits)?;
        packages.push(package);
        inserted.insert(next);
        remaining.remove(next);
    }
    let world = resolve
        .select_world(&packages, Some(&lock.world))
        .map_err(|_| invalid("wit-world-missing"))?;
    let value = &resolve.worlds[world];
    let package = value.package.ok_or_else(|| invalid("wit-world-unpinned"))?;
    if resolve.id_of_name(package, &value.name) != lock.world {
        return Err(invalid("wit-world-mismatch"));
    }
    Ok((resolve, world))
}

fn identity(group: &UnresolvedPackageGroup, entry: &WitLockedPackage) -> Result<(), PlatformError> {
    if !group.nested.is_empty() || group.main.name.to_string() != entry.id {
        return Err(invalid("wit-source-package-mismatch"));
    }
    let mut dependencies = BTreeSet::new();
    for dependency in group.main.foreign_deps.keys() {
        if dependency.version.is_none() {
            return Err(invalid("unpinned-wit-dependency"));
        }
        dependencies.insert(dependency.to_string());
    }
    if !dependencies.iter().eq(entry.dependencies.iter()) {
        return Err(invalid("wit-source-dependencies-mismatch"));
    }
    Ok(())
}
