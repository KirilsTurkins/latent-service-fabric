//! The shared bounded fingerprint preserves the legacy preparation handle bytes.

use std::fmt::Write;

use latent_artifacts::{preparation_metadata_fingerprint, CapsuleArtifact};
use latent_core::PlatformError;

pub(crate) struct MetadataIdentity {
    pub digest: String,
    pub bytes: usize,
}

pub(crate) fn identity(
    artifact: &CapsuleArtifact,
    maximum_bytes: usize,
    maximum_depth: usize,
) -> Result<MetadataIdentity, PlatformError> {
    let fingerprint = preparation_metadata_fingerprint(
        &artifact.descriptor,
        &artifact.manifest,
        &artifact.contracts,
        maximum_bytes,
        maximum_depth,
    )?;
    let mut digest = String::with_capacity(64);
    for byte in fingerprint.digest() {
        write!(&mut digest, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(MetadataIdentity {
        digest,
        bytes: fingerprint.charged_bytes(),
    })
}
