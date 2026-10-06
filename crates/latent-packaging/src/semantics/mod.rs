//! Bounded semantic checks for supplied artifacts; no compilation, execution or trust.
mod arena;
mod authoring;
pub use authoring::{derive_capsule_contracts, CapsuleContractInputs};
mod compare;
mod compatibility;
mod host;
mod lexical;
mod limits;
mod metadata;
mod owned;
mod projection;
mod sources;
#[cfg(test)]
mod tests;
mod wasm;
mod web;

pub use web::{inspect_web_bundle, validate_web_renderer, validate_web_renderer_with_backend};

pub use compatibility::{
    check_invocation_target, compare_packages, compile_host_binding, compile_local_binding,
    BreakingChangeAllowance, CheckedBinding, CheckedInvocationTarget, ComparedPackageIdentity,
    PackageComparisonLimits, PackageCompatibilityReport,
};
use latent_artifacts::package::{artifact_blob_digest, WitLock};
use latent_contracts::ContractDescriptor;
use latent_core::{
    ArtifactBlobDigest, HostAbiProfile, PlatformError, PlatformErrorCode, PHASE3_HOST_ABI_CURRENT,
};
use latent_manifest::{
    CapsuleManifest, ManifestValidator, Phase1ManifestValidator, Phase4TransactionManifestValidator,
};
pub use limits::SemanticLimits;
use std::collections::{BTreeMap, BTreeSet};
use wit_parser::decoding::DecodedWasm;

/// Bounded inspection counts. No executable/parser state is retained.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SurfaceCounts {
    pub source_packages: usize,
    /// Number of declared source-world imports, including compiler-pruned ones.
    pub imports: usize,
    pub exports: usize,
    pub functions: usize,
    pub type_nodes: usize,
}

/// Immutable summary of checked byte/type associations. This is not publisher
/// verification, runtime preparation, tenant authorization or catalog admission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckedSurface {
    component_digest: ArtifactBlobDigest,
    world: Box<str>,
    imports: Box<[Box<str>]>,
    exports: Box<[Box<str>]>,
    source_packages: Box<[(Box<str>, ArtifactBlobDigest)]>,
    counts: SurfaceCounts,
    host_profile: HostAbiProfile,
}

impl CheckedSurface {
    #[must_use]
    pub fn component_digest(&self) -> &ArtifactBlobDigest {
        &self.component_digest
    }
    #[must_use]
    pub fn world(&self) -> &str {
        &self.world
    }
    /// Declared source-world imports; the compiler may omit unused members or
    /// entire interfaces from the component's structurally checked import subset.
    #[must_use]
    pub fn imports(&self) -> &[Box<str>] {
        &self.imports
    }
    /// Checked source imports that require capability/provider bindings. All
    /// other imports were validated as resource-free value definitions; they
    /// remain in `imports()` and grant no host or provider authority.
    pub fn capability_imports(&self) -> impl Iterator<Item = &str> {
        self.imports
            .iter()
            .map(AsRef::as_ref)
            .filter(|name| self.host_profile.interface(name).is_some())
    }
    /// Exact structurally checked ABI; this installs no host or caller authority.
    #[must_use]
    pub fn host_profile(&self) -> HostAbiProfile {
        self.host_profile
    }
    /// These two Phase 4 hosts attach to the activation's admitted transaction.
    /// They cannot be installed or granted through a provider binding.
    #[must_use]
    pub fn activation_scoped_import(&self, interface: &str) -> bool {
        self.host_profile == latent_core::PHASE4_HOST_ABI_V1
            && self.imports.iter().any(|name| name.as_ref() == interface)
            && matches!(
                interface,
                "latent:state/key-value@0.2.0" | "latent:intents/staging@0.1.0"
            )
    }
    #[must_use]
    pub fn exports(&self) -> &[Box<str>] {
        &self.exports
    }
    #[must_use]
    pub fn source_packages(&self) -> &[(Box<str>, ArtifactBlobDigest)] {
        &self.source_packages
    }
    #[must_use]
    pub fn counts(&self) -> SurfaceCounts {
        self.counts
    }
}

/// Checks exact exports and the component's retained import subset against the
/// complete source world, plus the existing descriptor projection. Source keys
/// are exact logical paths from the supplied WIT lock. The returned summary
/// describes that declared source world, including imports pruned by a compiler.
/// The package builder additionally checks config/layer and contracts-byte binding.
pub fn validate_capsule(
    component: &[u8],
    manifest: &CapsuleManifest,
    contracts: &[ContractDescriptor],
    lock: &WitLock,
    sources: &BTreeMap<String, &[u8]>,
    limits: SemanticLimits,
) -> Result<CheckedSurface, PlatformError> {
    validate_capsule_for_profile(
        component,
        manifest,
        contracts,
        lock,
        sources,
        limits,
        PHASE3_HOST_ABI_CURRENT,
    )
}

pub(crate) fn validate_capsule_for_profile(
    component: &[u8],
    manifest: &CapsuleManifest,
    contracts: &[ContractDescriptor],
    lock: &WitLock,
    sources: &BTreeMap<String, &[u8]>,
    limits: SemanticLimits,
    host_profile: HostAbiProfile,
) -> Result<CheckedSurface, PlatformError> {
    limits.validate()?;
    owned::manifest(manifest, limits)?;
    if manifest.world.0 != lock.world {
        return Err(incompatible("capsule-wit-world-mismatch"));
    }
    let validator: &dyn ManifestValidator = if host_profile == latent_core::PHASE4_HOST_ABI_V1 {
        &Phase4TransactionManifestValidator
    } else {
        &Phase1ManifestValidator
    };
    validator
        .validate_capsule(manifest)
        .map_err(|_| invalid("invalid-capsule-manifest"))?;
    if let Some(renderer) = &manifest.runtime_requirements.renderer {
        if renderer != &latent_manifest::RendererRequirement::angular() {
            return Err(incompatible("renderer-profile-incompatible"));
        }
        validate_web_renderer_with_backend(
            component,
            renderer.profile,
            latent_artifacts::web::WebBackendProfile::from_imports(&manifest.imports)?,
            limits,
        )?;
    } else {
        wasm::validate(component, limits)?;
    }
    let digest = artifact_blob_digest(component);
    if manifest.component_digest.0 != digest.as_str() {
        return Err(incompatible("capsule-component-digest-mismatch"));
    }
    let (source, world) = sources::resolve(lock, sources, limits)?;
    let declared = compare::surface(&source, world, limits)?;
    let decoded = wit_parser::decoding::decode(component)
        .map_err(|_| incompatible("component-wit-decode-failed"))?;
    let DecodedWasm::Component(actual, actual_world) = decoded else {
        return Err(incompatible("wit-package-is-not-component"));
    };
    arena::resolved(&actual, limits)?;
    let compiled = compare::surface(&actual, actual_world, limits)?;
    compare_manifest(manifest, &declared, host_profile)?;
    let type_nodes =
        compare::worlds_for_profile(&source, &declared, &actual, &compiled, limits, host_profile)?;
    host::validate_for_profile(&source, &declared.imports, limits, host_profile)?;
    projection::validate(&source, world, contracts, limits)?;
    let functions = declared
        .exports
        .values()
        .map(|id| source.interfaces[*id].functions.len())
        .sum();
    let counts = SurfaceCounts {
        source_packages: lock.packages.len(),
        imports: declared.imports.len(),
        exports: declared.exports.len(),
        functions,
        type_nodes,
    };
    let mut charge = 256;
    limits::add(&mut charge, lock.world.len(), limits.max_summary_bytes)?;
    for name in declared.imports.keys().chain(declared.exports.keys()) {
        limits::add(&mut charge, name.len() + 32, limits.max_summary_bytes)?;
    }
    for package in &lock.packages {
        limits::add(
            &mut charge,
            package.id.len() + 128,
            limits.max_summary_bytes,
        )?;
    }
    Ok(CheckedSurface {
        component_digest: digest,
        world: lock.world.clone().into_boxed_str(),
        imports: declared
            .imports
            .into_keys()
            .map(String::into_boxed_str)
            .collect(),
        exports: declared
            .exports
            .into_keys()
            .map(String::into_boxed_str)
            .collect(),
        source_packages: lock
            .packages
            .iter()
            .map(|entry| (entry.id.clone().into_boxed_str(), entry.digest.clone()))
            .collect(),
        counts,
        host_profile,
    })
}

fn compare_manifest(
    manifest: &CapsuleManifest,
    declared: &compare::WorldSurface,
    host_profile: HostAbiProfile,
) -> Result<(), PlatformError> {
    let exports: BTreeSet<_> = manifest
        .exports
        .iter()
        .map(|item| item.contract.0.as_str())
        .collect();
    if !exports
        .iter()
        .copied()
        .eq(declared.exports.keys().map(String::as_str))
    {
        return Err(incompatible("capsule-export-set-mismatch"));
    }
    for import in &manifest.imports {
        if host_profile.interface(&import.contract.0).is_none() {
            return Err(incompatible("unsupported-host-import"));
        }
        if !import.optional && !declared.imports.contains_key(&import.contract.0) {
            return Err(incompatible("capsule-required-import-missing"));
        }
    }
    if declared.imports.keys().any(|name| {
        host_profile.interface(name).is_some()
            && !manifest
                .imports
                .iter()
                .any(|entry| entry.contract.0 == *name)
    }) {
        return Err(incompatible("capsule-undeclared-import"));
    }
    Ok(())
}

pub(super) fn invalid(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::InvalidArgument, reason)
}
pub(super) fn exhausted(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::ResourceExhausted, reason)
}
pub(super) fn incompatible(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::IncompatibleContract, reason)
}
fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
