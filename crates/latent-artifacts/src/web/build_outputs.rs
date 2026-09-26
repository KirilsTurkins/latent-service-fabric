use crate::package::{PackageKind, PackageLayout};
use latent_core::{ArtifactBlobDigest, PlatformError};
use sha2::{Digest, Sha256};

/// Observed web outputs have their own identity; a browser package has no
/// executable/component identity. The final package still authenticates its
/// inventory and build-input receipt, excluded here to avoid digest cycles.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebBuildOutputs {
    digest: ArtifactBlobDigest,
    count: usize,
    bytes: u64,
}

impl WebBuildOutputs {
    #[must_use]
    pub fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }
    #[must_use]
    pub fn count(&self) -> usize {
        self.count
    }
    #[must_use]
    pub fn bytes(&self) -> u64 {
        self.bytes
    }
}

/// Binds the actual ordered package descriptors, including private renderer,
/// web profile and routing metadata. This is an identity, never builder trust.
pub fn web_build_outputs(package: &PackageLayout) -> Result<WebBuildOutputs, PlatformError> {
    if !matches!(
        package.config().kind,
        PackageKind::BrowserAssets | PackageKind::SsrPackage
    ) {
        return Err(super::incompatible());
    }
    let mut hash = Sha256::new();
    part(&mut hash, b"lsf-web-build-outputs-v1");
    part(&mut hash, package.config().kind.artifact_type().as_bytes());
    let mut count = 0;
    let mut bytes = 0u64;
    for layer in &package.config().layers {
        if matches!(
            layer.path.as_str(),
            "package/sbom.cdx.json" | "package/build-inputs.json"
        ) {
            continue;
        }
        count += 1;
        bytes = bytes.checked_add(layer.size).ok_or_else(super::exhausted)?;
        for value in [
            layer.path.as_str(),
            layer.role.as_str(),
            layer.media_type.as_str(),
            layer.digest.as_str(),
        ] {
            part(&mut hash, value.as_bytes());
        }
        part(&mut hash, &layer.size.to_le_bytes());
    }
    if count == 0 {
        return Err(super::invalid("web-build-output-missing"));
    }
    Ok(WebBuildOutputs {
        digest: format!("sha256:{:x}", hash.finalize())
            .parse()
            .expect("SHA-256"),
        count,
        bytes,
    })
}

fn part(hash: &mut Sha256, value: &[u8]) {
    hash.update((value.len() as u64).to_le_bytes());
    hash.update(value);
}
