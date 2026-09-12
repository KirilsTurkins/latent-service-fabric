//! Explicit control comparison; parser arenas are dropped on return.
mod report;
#[cfg(test)]
mod tests;
mod types;
pub use report::{
    BreakingChangeAllowance, ComparedPackageIdentity, PackageComparisonLimits,
    PackageCompatibilityReport,
};

use super::{compare, sources, SemanticLimits};
use crate::PackageBundle;
use latent_artifacts::package::{decode_wit_lock, LayerRole, PackageKind, PackageLimits, WitLock};
use latent_contracts::{Analysis, StructuralCompatibility as Level, StructuralIssueCode as Code};
use latent_core::{PlatformError, PlatformErrorCode};
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::{InterfaceId, Resolve};

/// Compare immutable checked capsule surfaces. This grants neither live trust nor
/// host runtime eligibility and never remaps versioned dispatch identities.
pub fn compare_packages(
    previous: &PackageBundle,
    candidate: &PackageBundle,
    limits: PackageComparisonLimits,
) -> Result<PackageCompatibilityReport, PlatformError> {
    limits.validate()?;
    let mut analysis = Analysis::new(limits.comparison)?;
    let previous_identity = ComparedPackageIdentity::of(previous);
    let candidate_identity = ComparedPackageIdentity::of(candidate);
    if previous.layout().config().kind != PackageKind::Capsule
        || candidate.layout().config().kind != PackageKind::Capsule
    {
        analysis.issue(Level::Unsupported, Code::UnsupportedPackage, &[]);
    } else {
        let result = compare_inner(previous, candidate, limits, &mut analysis);
        match result {
            Err(error) if error.code == PlatformErrorCode::ResourceExhausted => {
                analysis.exhausted();
            }
            Err(error) => return Err(error),
            Ok(()) => (),
        }
    }
    Ok(PackageCompatibilityReport::new(
        previous_identity,
        candidate_identity,
        analysis.finish(),
    ))
}

fn lock(bundle: &PackageBundle) -> Result<WitLock, PlatformError> {
    let layer = bundle
        .layout()
        .config()
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::WitLock)
        .ok_or_else(|| super::invalid("comparison-wit-lock-missing"))?;
    decode_wit_lock(
        bundle
            .blob(&layer.path)
            .ok_or_else(|| super::invalid("comparison-wit-lock-missing"))?,
        PackageLimits::default(),
    )
}

fn preflight(
    bundle: &PackageBundle,
    lock: &WitLock,
    limits: PackageComparisonLimits,
    total_bytes: &mut usize,
    total_packages: &mut usize,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    super::limits::add(
        total_packages,
        lock.packages.len(),
        limits.max_total_wit_packages,
    )?;
    if bundle.surface().is_none() {
        return Err(super::invalid("comparison-surface-missing"));
    }
    for item in &lock.packages {
        let bytes = bundle
            .blob(&item.source_path)
            .ok_or_else(|| super::invalid("comparison-wit-source-missing"))?;
        super::limits::add(total_bytes, bytes.len(), limits.max_total_wit_bytes)?;
        a.edge(1 + item.dependencies.len())?;
        a.name(&item.id)?;
        a.text(&item.source_path)?;
        a.retained(item.id.capacity() + item.source_path.capacity() + 256)?;
        for dependency in &item.dependencies {
            a.name(dependency)?;
            a.retained(dependency.capacity() + 64)?;
        }
    }
    Ok(())
}
fn resolved(
    bundle: &PackageBundle,
    lock: &WitLock,
    limits: SemanticLimits,
) -> Result<(Resolve, compare::WorldSurface), PlatformError> {
    let inputs = lock
        .packages
        .iter()
        .map(|item| {
            Ok((
                item.source_path.clone(),
                bundle
                    .blob(&item.source_path)
                    .ok_or_else(|| super::invalid("comparison-wit-source-missing"))?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>, PlatformError>>()?;
    let (resolve, world) = sources::resolve(lock, &inputs, limits)?;
    let surface = compare::surface(&resolve, world, limits)?;
    Ok((resolve, surface))
}

fn compare_inner(
    old: &PackageBundle,
    new: &PackageBundle,
    limits: PackageComparisonLimits,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    let old_lock = lock(old)?;
    let new_lock = lock(new)?;
    let mut bytes = 0;
    let mut packages = 0;
    preflight(old, &old_lock, limits, &mut bytes, &mut packages, a)?;
    preflight(new, &new_lock, limits, &mut bytes, &mut packages, a)?;
    let (left, old_surface) = resolved(old, &old_lock, limits.semantics)?;
    let (right, new_surface) = resolved(new, &new_lock, limits.semantics)?;
    surfaces(&left, &old_surface, &right, &new_surface, a)
}

fn surfaces(
    left: &Resolve,
    old: &compare::WorldSurface,
    right: &Resolve,
    new: &compare::WorldSurface,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    let mut walk = Walker {
        left,
        right,
        analysis: a,
    };
    // Inspect both complete public surfaces before allowing a breaking decision:
    // a removed/added function with unsupported shape cannot hide behind a diff.
    for (resolve, surface) in [(left, old), (right, new)] {
        for (name, id) in surface.imports.iter().chain(&surface.exports) {
            walk.analysis.name(name)?;
            types::inspect_interface(resolve, *id, walk.analysis)?;
        }
    }
    if !old.imports.keys().eq(new.imports.keys()) {
        walk.analysis
            .issue(Level::Unknown, Code::ImportChanged, &["imports"]);
    }
    for (name, id) in &old.imports {
        if let Some(candidate) = new.imports.get(name) {
            walk.interface(*id, *candidate, name, false)?;
        }
    }
    for (name, id) in &old.exports {
        if let Some(candidate) = new.exports.get(name) {
            walk.interface(*id, *candidate, name, true)?;
        } else {
            walk.analysis
                .issue(Level::Breaking, Code::RemovedInterface, &[name]);
        }
    }
    if new.exports.len() > old.exports.len() {
        walk.analysis.added();
    }
    Ok(())
}

struct Walker<'a, 'b> {
    left: &'a Resolve,
    right: &'a Resolve,
    analysis: &'b mut Analysis,
}
impl Walker<'_, '_> {
    fn interface(
        &mut self,
        left: InterfaceId,
        right: InterfaceId,
        path: &str,
        additions: bool,
    ) -> Result<(), PlatformError> {
        let old = &self.left.interfaces[left];
        let new = &self.right.interfaces[right];
        // A breaking export can be an explicit caller decision. A changed host
        // import is an unproved execution requirement and cannot use that escape.
        let changed = if additions {
            Level::Breaking
        } else {
            Level::Unknown
        };
        self.analysis.node(1)?;
        let old_dependencies = dependencies(self.left, left, self.analysis)?;
        let new_dependencies = dependencies(self.right, right, self.analysis)?;
        if old_dependencies != new_dependencies {
            self.analysis
                .issue(changed, Code::DependencyChanged, &[path]);
        }
        for (name, id) in &old.types {
            self.analysis.edge(1)?;
            self.analysis.text(name)?;
            if let Some(other) = new.types.get(name) {
                if !self.ty(wit_parser::Type::Id(*id), wit_parser::Type::Id(*other), 1)? {
                    self.analysis
                        .issue(changed, Code::TypeChanged, &[path, name]);
                }
            } else {
                self.analysis
                    .issue(changed, Code::RemovedType, &[path, name]);
            }
        }
        for (name, function) in &old.functions {
            self.analysis.node(1)?;
            self.analysis.text(name)?;
            if let Some(other) = new.functions.get(name) {
                if !self.function(function, other)? {
                    self.analysis
                        .issue(changed, Code::FunctionChanged, &[path, name]);
                }
            } else {
                self.analysis
                    .issue(changed, Code::RemovedFunction, &[path, name]);
            }
        }
        if new.types.len() > old.types.len() || new.functions.len() > old.functions.len() {
            if additions {
                self.analysis.added();
            } else {
                self.analysis
                    .issue(Level::Unknown, Code::ImportChanged, &[path]);
            }
        }
        Ok(())
    }
}
fn dependencies(
    resolve: &Resolve,
    id: InterfaceId,
    a: &mut Analysis,
) -> Result<BTreeSet<String>, PlatformError> {
    let mut dependencies = BTreeSet::new();
    for dependency in resolve.interface_direct_deps(id) {
        a.edge(1)?;
        let name = resolve
            .id_of(dependency)
            .ok_or_else(|| super::invalid("comparison-unqualified-dependency"))?;
        a.name(&name)?;
        a.retained(name.capacity() + 128)?;
        dependencies.insert(name);
    }
    Ok(dependencies)
}
