use crate::{format::map_package_error, SignatureFailure, SignatureResult};
use latent_artifacts::package::{
    inspect_package, LayerRole, PackageKind, PackageLimits, PackageSubject, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_core::ArtifactBlobDigest;

/// Immutable package identity derived from exact manifest bytes and its checked
/// config association. It does not establish layer integrity or guest semantics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackageSigningSubject {
    subject: PackageSubject,
    kind: PackageKind,
    component_digest: Option<ArtifactBlobDigest>,
    component_size: Option<u64>,
}

impl PackageSigningSubject {
    pub fn from_package(
        manifest_bytes: &[u8],
        config_bytes: &[u8],
        limits: PackageLimits,
    ) -> SignatureResult<Self> {
        limits
            .validate()
            .map_err(|_| SignatureFailure::InvalidLimits)?;
        let package = inspect_package(manifest_bytes, config_bytes, limits)
            .map_err(|error| map_package_error(&error, SignatureFailure::InvalidSubject))?;
        Ok(Self {
            kind: package.config().kind,
            component_digest: package.config().component_digest.clone(),
            component_size: package
                .config()
                .layers
                .iter()
                .find(|layer| layer.role == LayerRole::Component)
                .map(|layer| layer.size),
            subject: PackageSubject {
                media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
                digest: package.digest().clone(),
                size: manifest_bytes.len() as u64,
            },
        })
    }

    #[cfg(test)]
    pub(crate) fn test(
        subject: PackageSubject,
        component_digest: Option<ArtifactBlobDigest>,
    ) -> Self {
        Self {
            kind: if component_digest.is_some() {
                PackageKind::Capsule
            } else {
                PackageKind::BrowserAssets
            },
            component_digest,
            component_size: None,
            subject,
        }
    }

    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }
    #[must_use]
    pub const fn kind(&self) -> PackageKind {
        self.kind
    }
    #[must_use]
    pub fn component_digest(&self) -> Option<&ArtifactBlobDigest> {
        self.component_digest.as_ref()
    }
    #[must_use]
    pub const fn component_size(&self) -> Option<u64> {
        self.component_size
    }
}
