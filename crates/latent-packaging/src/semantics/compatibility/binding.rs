//! Selected checked import/export comparison, without publication authority.
use super::{
    dependencies, lock, preflight, resolved, types, Analysis, ComparedPackageIdentity, Level,
    PackageComparisonLimits, Walker,
};
use crate::PackageBundle;
use latent_core::{ArtifactBlobDigest, PlatformError, PHASE3_HOST_ABI_V3};
use std::collections::BTreeMap;

/// Sealed immutable ABI facts. A control compiler must separately establish
/// tenant admission, provider installation, policy, and deployment currentness.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckedBinding {
    consumer: ComparedPackageIdentity,
    provider: Option<ComparedPackageIdentity>,
    interface: Box<str>,
    operations: Box<[String]>,
    host_abi: Option<ArtifactBlobDigest>,
}
impl CheckedBinding {
    #[must_use]
    pub fn consumer(&self) -> &ComparedPackageIdentity {
        &self.consumer
    }
    #[must_use]
    pub fn provider(&self) -> Option<&ComparedPackageIdentity> {
        self.provider.as_ref()
    }
    #[must_use]
    pub fn interface(&self) -> &str {
        &self.interface
    }
    #[must_use]
    pub fn operations(&self) -> &[String] {
        &self.operations
    }
    #[must_use]
    pub fn host_abi(&self) -> Option<&ArtifactBlobDigest> {
        self.host_abi.as_ref()
    }
}
fn incompatible() -> PlatformError {
    crate::semantics::incompatible("binding-contract-not-exact")
}

/// Checks an exact declared consumer import against the node's pinned host ABI.
/// Async freestanding calls are accepted only for that ABI's explicit profile;
/// unknown resources/futures/streams and version substitutions remain rejected.
pub fn compile_host_binding(
    consumer: &PackageBundle,
    interface: &str,
    limits: PackageComparisonLimits,
) -> Result<CheckedBinding, PlatformError> {
    limits.validate()?;
    let mut analysis = Analysis::new(limits.comparison)?;
    analysis.name(interface)?;
    let lock = lock(consumer)?;
    preflight(consumer, &lock, limits, &mut 0, &mut 0, &mut analysis)?;
    let (source, surface) = resolved(consumer, &lock, limits.semantics)?;
    let imported = *surface.imports.get(interface).ok_or_else(incompatible)?;
    let spec = PHASE3_HOST_ABI_V3
        .interface(interface)
        .ok_or_else(incompatible)?;
    // validate_capsule already checks this association. Rechecking the selected
    // bounded source keeps this proof independent of projection/digest labels.
    crate::semantics::host::validate(
        &source,
        &BTreeMap::from([(interface.to_owned(), imported)]),
        limits.semantics,
    )?;
    let operations = source.interfaces[imported]
        .functions
        .keys()
        .cloned()
        .collect();
    Ok(CheckedBinding {
        consumer: ComparedPackageIdentity::of(consumer),
        provider: None,
        interface: interface.into(),
        operations,
        host_abi: Some(latent_artifacts::package::artifact_blob_digest(
            spec.wit.as_bytes(),
        )),
    })
}

/// Proves one declared import and provider export have the same fully qualified
/// versioned dispatch identity and complete supported value ABI. No adapters.
pub fn compile_local_binding(
    consumer: &PackageBundle,
    provider: &PackageBundle,
    consumer_import: &str,
    provider_export: &str,
    limits: PackageComparisonLimits,
) -> Result<CheckedBinding, PlatformError> {
    limits.validate()?;
    let mut analysis = Analysis::new(limits.comparison)?;
    analysis.name(consumer_import)?;
    analysis.name(provider_export)?;
    if consumer_import != provider_export {
        return Err(incompatible());
    }
    let consumer_lock = lock(consumer)?;
    let provider_lock = lock(provider)?;
    let mut bytes = 0;
    let mut packages = 0;
    for (bundle, lock) in [(consumer, &consumer_lock), (provider, &provider_lock)] {
        preflight(
            bundle,
            lock,
            limits,
            &mut bytes,
            &mut packages,
            &mut analysis,
        )?;
    }
    let (left, input) = resolved(consumer, &consumer_lock, limits.semantics)?;
    let (right, output) = resolved(provider, &provider_lock, limits.semantics)?;
    let imported = *input
        .imports
        .get(consumer_import)
        .ok_or_else(incompatible)?;
    let exported = *output
        .exports
        .get(provider_export)
        .ok_or_else(incompatible)?;
    exact_interface(
        &left,
        imported,
        &right,
        exported,
        consumer_import,
        &mut analysis,
    )?;
    let report = analysis.finish();
    if !report.analysis_complete || report.level != Level::Identical {
        return Err(incompatible());
    }
    Ok(CheckedBinding {
        consumer: ComparedPackageIdentity::of(consumer),
        provider: Some(ComparedPackageIdentity::of(provider)),
        interface: consumer_import.into(),
        operations: left.interfaces[imported]
            .functions
            .keys()
            .cloned()
            .collect(),
        host_abi: None,
    })
}
fn exact_interface(
    left: &wit_parser::Resolve,
    imported: wit_parser::InterfaceId,
    right: &wit_parser::Resolve,
    exported: wit_parser::InterfaceId,
    interface: &str,
    analysis: &mut Analysis,
) -> Result<(), PlatformError> {
    if left.id_of(imported).as_deref() != Some(interface)
        || right.id_of(exported).as_deref() != Some(interface)
        || left.interfaces[imported].functions.is_empty()
    {
        return Err(incompatible());
    }
    for (resolve, id) in [(left, imported), (right, exported)] {
        types::inspect_interface(resolve, id, analysis)?;
    }
    if dependencies(left, imported, analysis)? != dependencies(right, exported, analysis)? {
        return Err(incompatible());
    }
    Walker {
        left,
        right,
        analysis,
        resources: false,
    }
    .interface(imported, exported, interface, false)
}

#[cfg(test)]
mod tests;
