use crate::{error, OciManifestBytes, OciReference};
use latent_artifacts::package::{
    artifact_blob_digest, decode_referrer, inspect_package, verify_layer_bytes,
    ArtifactDescriptor as LayerDescriptor, PackageKind, PackageLayout, PackageLimits,
    ReferrerManifest,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::fmt;

/// A complete, format-checked package upload with immutable byte associations.
///
/// The original manifest, its exact config bytes and every ordered layer are
/// retained. No DTO reserialization substitutes for the published identity.
/// Layer verification checks content hashes, not embedded WIT/capsule semantics
/// or cryptographic evidence. Browser/SSR packages remain packaging-only kinds.
pub struct OciPushRequest {
    reference: OciReference,
    manifest: OciManifestBytes,
    config_bytes: Box<[u8]>,
    layers: Box<[Box<[u8]>]>,
    layout: UploadLayout,
}

enum UploadLayout {
    Package(PackageLayout),
    Referrer(ReferrerManifest),
}

impl OciPushRequest {
    /// Each provided layer descriptor must equal the corresponding descriptor
    /// in the exact manifest, including media type, size and annotations.
    /// Config and layer sizes/hashes are checked before this request is usable.
    /// Transport/build callers must enforce the same count, individual and
    /// aggregate byte bounds before materializing their input buffers.
    pub fn new(
        reference: OciReference,
        manifest: OciManifestBytes,
        config_bytes: Vec<u8>,
        layers: Vec<(LayerDescriptor, Vec<u8>)>,
        limits: PackageLimits,
    ) -> Result<Self, PlatformError> {
        let layout = inspect_package(manifest.as_bytes(), &config_bytes, limits)?;
        if layers.len() > limits.max_layers {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "oci-push-layer-count-limit",
            ));
        }
        if layers.len() != layout.manifest().layers.len() {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "oci-push-incomplete-layers",
            ));
        }
        for ((supplied, bytes), (expected, layer)) in layers
            .iter()
            .zip(layout.manifest().layers.iter().zip(&layout.config().layers))
        {
            if supplied != expected {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "oci-push-descriptor-mismatch",
                ));
            }
            verify_layer_bytes(layer, bytes, limits)?;
        }
        let layers = layers
            .into_iter()
            .map(|(_, bytes)| bytes.into_boxed_slice())
            .collect::<Vec<_>>()
            .into_boxed_slice();
        Ok(Self {
            reference,
            manifest,
            config_bytes: config_bytes.into_boxed_slice(),
            layers,
            layout: UploadLayout::Package(layout),
        })
    }

    /// Associates a detached signature/provenance/SBOM envelope with its exact
    /// empty config and one evidence layer. Subject association and blob hashes
    /// are checked; payload cryptography, subject existence and trust are not.
    pub fn new_referrer(
        reference: OciReference,
        manifest: OciManifestBytes,
        config_bytes: Vec<u8>,
        layers: Vec<(LayerDescriptor, Vec<u8>)>,
        limits: PackageLimits,
    ) -> Result<Self, PlatformError> {
        let referrer = decode_referrer(manifest.as_bytes(), limits)?;
        if config_bytes.as_slice() != b"{}" {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "oci-referrer-config-mismatch",
            ));
        }
        if layers.len() != 1 {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "oci-referrer-layer-count",
            ));
        }
        let (descriptor, bytes) = &layers[0];
        if *descriptor != referrer.layers[0] {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "oci-referrer-descriptor-mismatch",
            ));
        }
        if bytes.len() as u64 != descriptor.size || artifact_blob_digest(bytes) != descriptor.digest
        {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "oci-referrer-content-mismatch",
            ));
        }
        let layers = layers
            .into_iter()
            .map(|(_, bytes)| bytes.into_boxed_slice())
            .collect::<Vec<_>>()
            .into_boxed_slice();
        Ok(Self {
            reference,
            manifest,
            config_bytes: config_bytes.into_boxed_slice(),
            layers,
            layout: UploadLayout::Referrer(referrer),
        })
    }

    #[must_use]
    pub fn reference(&self) -> &OciReference {
        &self.reference
    }

    #[must_use]
    pub fn manifest(&self) -> &OciManifestBytes {
        &self.manifest
    }

    #[must_use]
    pub fn config_bytes(&self) -> &[u8] {
        &self.config_bytes
    }

    #[must_use]
    pub fn layout(&self) -> Option<&PackageLayout> {
        match &self.layout {
            UploadLayout::Package(layout) => Some(layout),
            UploadLayout::Referrer(_) => None,
        }
    }

    #[must_use]
    pub fn referrer(&self) -> Option<&ReferrerManifest> {
        match &self.layout {
            UploadLayout::Package(_) => None,
            UploadLayout::Referrer(manifest) => Some(manifest),
        }
    }

    /// Rejects evidence, asset-only and opaque SSR kinds before capsule mapping.
    /// A successful kind check still grants no execution or publisher authority.
    pub fn capsule_layout(&self) -> Result<&PackageLayout, PlatformError> {
        self.layout()
            .filter(|layout| layout.config().kind == PackageKind::Capsule)
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::InvalidArgument,
                    "oci-package-not-capsule",
                )
            })
    }

    /// Iterates the verified descriptor/bytes pairs in manifest order.
    pub fn layers(&self) -> impl ExactSizeIterator<Item = (&LayerDescriptor, &[u8])> {
        let descriptors = match &self.layout {
            UploadLayout::Package(layout) => &layout.manifest().layers,
            UploadLayout::Referrer(manifest) => &manifest.layers,
        };
        descriptors.iter().zip(self.layers.iter().map(Box::as_ref))
    }
}

impl fmt::Debug for OciPushRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OciPushRequest")
            .field("manifest", &self.manifest)
            .field("config_size_bytes", &self.config_bytes.len())
            .field("layer_count", &self.layers.len())
            .finish_non_exhaustive()
    }
}
