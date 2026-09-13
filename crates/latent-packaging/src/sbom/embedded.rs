mod outputs;

use latent_artifacts::package::{LayerRole, PackageLayout};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError};

use super::{
    inspect_cyclonedx_sbom, SbomDependencyCompleteness, SbomEntryKind, CYCLONEDX_JSON_MEDIA_TYPE,
};
use crate::PackagingLimits;

pub const SBOM_PATH: &str = "package/sbom.cdx.json";

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SbomRoleCounts {
    entries: usize,
    with_source: usize,
    with_license: usize,
}

impl SbomRoleCounts {
    #[must_use]
    pub const fn entries(self) -> usize {
        self.entries
    }
    #[must_use]
    pub const fn with_source(self) -> usize {
        self.with_source
    }
    #[must_use]
    pub const fn with_license(self) -> usize {
        self.with_license
    }
}

/// Exact package/inventory association plus fixed-size attribution counts.
/// No second BOM copy or full dependency graph is retained. These are checked
/// inventory assertions, not publisher trust or a complete linked-code closure.
#[derive(Debug)]
pub struct CheckedPackageSbom {
    package_digest: PackageDigest,
    inventory_digest: ArtifactBlobDigest,
    dependency_completeness: SbomDependencyCompleteness,
    source_snapshot_digest: Option<ArtifactBlobDigest>,
    counts: [SbomRoleCounts; 9],
}

impl CheckedPackageSbom {
    #[must_use]
    pub fn package_digest(&self) -> &PackageDigest {
        &self.package_digest
    }
    #[must_use]
    pub fn inventory_digest(&self) -> &ArtifactBlobDigest {
        &self.inventory_digest
    }
    #[must_use]
    pub fn dependency_completeness(&self) -> SbomDependencyCompleteness {
        self.dependency_completeness
    }
    #[must_use]
    pub fn source_snapshot_digest(&self) -> Option<&ArtifactBlobDigest> {
        self.source_snapshot_digest.as_ref()
    }
    #[must_use]
    pub fn counts(&self, kind: SbomEntryKind) -> SbomRoleCounts {
        self.counts[kind.index()]
    }
    #[must_use]
    pub fn entry_count(&self) -> usize {
        self.counts.iter().map(|counts| counts.entries).sum()
    }
}

// Called only after PackageBundle's exact layer set/digests and capsule WIT
// semantics are checked. The supplied slices are already bounded raw content.
pub(crate) fn inspect(
    layout: &PackageLayout,
    layers: &[(String, Vec<u8>)],
    limits: PackagingLimits,
) -> Result<Option<CheckedPackageSbom>, PlatformError> {
    let config = layout.config();
    let Some(layer) = config.layers.iter().find(|layer| layer.path == SBOM_PATH) else {
        return Ok(None);
    };
    if layer.role != LayerRole::Asset || layer.media_type != CYCLONEDX_JSON_MEDIA_TYPE {
        return Err(crate::invalid("invalid-embedded-sbom-layer"));
    }
    let bytes = &layers
        .iter()
        .find(|(path, _)| path == SBOM_PATH)
        .expect("checked package blob set")
        .1;
    let inspected = inspect_cyclonedx_sbom(CYCLONEDX_JSON_MEDIA_TYPE, bytes, limits.sbom)?;
    let inventory = inspected.inventory();
    if inventory.package_kind != config.kind
        || inventory.package_name != config.name
        || inventory.package_version != config.version
    {
        return Err(crate::invalid("sbom-package-identity-mismatch"));
    }
    outputs::validate(config, layers, inventory, limits)?;
    let mut counts = [SbomRoleCounts::default(); 9];
    for entry in &inventory.entries {
        let role = &mut counts[entry.kind.index()];
        role.entries += 1;
        role.with_source += usize::from(entry.source.is_some());
        role.with_license += usize::from(entry.license_expression.is_some());
    }
    Ok(Some(CheckedPackageSbom {
        package_digest: layout.digest().clone(),
        inventory_digest: inspected.digest().clone(),
        dependency_completeness: inventory.dependency_completeness,
        source_snapshot_digest: inventory.source_snapshot_digest.clone(),
        counts,
    }))
}
