use latent_artifacts::package::{
    inspect_package, verify_layer_bytes, LayerRole, PackageKind, PackageLayout,
};
use latent_core::PlatformError;

use crate::{sbom::CheckedPackageSbom, BuildReceipt, CheckedSurface, PackagingLimits};

/// Exact received envelope/configuration and logical-path-addressed raw blobs.
#[derive(Debug)]
pub struct BundleInput {
    pub manifest: Vec<u8>,
    pub configuration: Vec<u8>,
    pub layers: Vec<(String, Vec<u8>)>,
}

#[derive(Debug)]
pub struct PackageBlob {
    path: Box<str>,
    bytes: Box<[u8]>,
}

impl PackageBlob {
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

/// Owned immutable integrity/semantic inspection. This is not a trust,
/// authenticated tenant, catalog-admission or execution-eligibility token.
#[derive(Debug)]
pub struct PackageBundle {
    layout: PackageLayout,
    manifest: Box<[u8]>,
    configuration: Box<[u8]>,
    layers: Box<[PackageBlob]>,
    surface: Option<CheckedSurface>,
    receipt: Option<BuildReceipt>,
    sbom: Option<CheckedPackageSbom>,
}

impl PackageBundle {
    #[must_use]
    pub fn layout(&self) -> &PackageLayout {
        &self.layout
    }
    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest
    }
    #[must_use]
    pub fn config_bytes(&self) -> &[u8] {
        &self.configuration
    }
    #[must_use]
    pub fn layers(&self) -> &[PackageBlob] {
        &self.layers
    }
    #[must_use]
    pub fn surface(&self) -> Option<&CheckedSurface> {
        self.surface.as_ref()
    }
    #[must_use]
    pub fn build_receipt(&self) -> Option<&BuildReceipt> {
        self.receipt.as_ref()
    }
    /// Checked inventory association and attribution counts. Package publisher
    /// authority and admission still require independent verification.
    #[must_use]
    pub fn sbom(&self) -> Option<&CheckedPackageSbom> {
        self.sbom.as_ref()
    }
    #[must_use]
    pub fn blob(&self, path: &str) -> Option<&[u8]> {
        let index = self
            .layers
            .binary_search_by(|blob| blob.path().cmp(path))
            .ok()?;
        Some(self.layers[index].bytes())
    }
}

/// Checks exact-byte associations and capsule semantics without compiling code,
/// contacting a registry or changing catalog visibility. Received JSON identity
/// is preserved; only the build API canonicalizes supplied metadata.
pub fn inspect_bundle(
    mut input: BundleInput,
    limits: PackagingLimits,
) -> Result<PackageBundle, PlatformError> {
    limits.validate()?;
    let layout = inspect_package(&input.manifest, &input.configuration, limits.package)?;
    if input.layers.len() != layout.config().layers.len() {
        return Err(crate::invalid("package-blob-set-mismatch"));
    }
    if input
        .layers
        .iter()
        .any(|(path, _)| path.len() > limits.package.max_path_bytes)
    {
        return Err(crate::exceeded("package-path-limit"));
    }
    input.layers.sort_by(|a, b| a.0.cmp(&b.0));
    for ((path, bytes), layer) in input.layers.iter().zip(&layout.config().layers) {
        if path != &layer.path {
            return Err(crate::invalid("package-blob-set-mismatch"));
        }
        let maximum = limits.layer_limit(layer.role, path);
        if bytes.len() as u64 > maximum {
            return Err(crate::exceeded("package-content-byte-limit"));
        }
        verify_layer_bytes(layer, bytes, limits.package)?;
    }
    let surface = if layout.config().kind == PackageKind::Capsule {
        Some(crate::assembly::inspect_capsule(
            layout.config(),
            &input.layers,
            limits,
        )?)
    } else {
        None
    };
    let receipt = if let Some((_, bytes)) = input
        .layers
        .iter()
        .find(|(path, _)| path == crate::BUILD_INPUTS_PATH)
    {
        let layer = layout
            .config()
            .layers
            .iter()
            .find(|layer| layer.path == crate::BUILD_INPUTS_PATH)
            .expect("associated layer");
        if layer.role != LayerRole::Asset || layer.media_type != "application/json" {
            return Err(crate::invalid("invalid-build-inputs-layer"));
        }
        let receipt = crate::receipt::decode(bytes, limits.package)?;
        receipt.validate_outputs(layout.config(), limits.package)?;
        Some(receipt)
    } else {
        None
    };
    let sbom = crate::sbom::embedded::inspect(&layout, &input.layers, limits)?;
    Ok(PackageBundle {
        layout,
        manifest: input.manifest.into_boxed_slice(),
        configuration: input.configuration.into_boxed_slice(),
        layers: input
            .layers
            .into_iter()
            .map(|(path, bytes)| PackageBlob {
                path: path.into_boxed_str(),
                bytes: bytes.into_boxed_slice(),
            })
            .collect::<Vec<_>>()
            .into_boxed_slice(),
        surface,
        receipt,
        sbom,
    })
}
