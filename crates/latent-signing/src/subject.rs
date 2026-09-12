use crate::{format::map_package_error, SignatureFailure, SignatureResult};
use latent_artifacts::package::{
    inspect_package, PackageLimits, PackageSubject, OCI_MANIFEST_MEDIA_TYPE,
};

/// Immutable package identity derived from exact manifest bytes and its checked
/// config association. It does not establish layer integrity or guest semantics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackageSigningSubject {
    subject: PackageSubject,
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
            subject: PackageSubject {
                media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
                digest: package.digest().clone(),
                size: manifest_bytes.len() as u64,
            },
        })
    }

    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }
}
