//! Repository materialization with an affine pin and the declared import list.

use latent_artifacts::{content_digest, ArtifactRepository, CapsuleArtifact};
use latent_core::{ContractId, PlatformError, PlatformErrorCode};

use crate::{ExecutionBackend, PreparationKey, PreparedUse};

/// One prepared activation and its manifest imports, including optional imports.
/// The invocation owner binds these contracts to that activation's host context.
#[derive(Debug)]
#[must_use = "dropping prepared activation releases its backend ownership"]
pub struct PreparedActivation {
    pub prepared: PreparedUse,
    pub imports: Vec<ContractId>,
}

pub(crate) async fn prepare<B: ExecutionBackend + ?Sized>(
    backend: &B,
    repository: &dyn ArtifactRepository,
    key: &PreparationKey,
) -> Result<PreparedActivation, PlatformError> {
    // Selecting a sealed source explicitly delegates both lookup and reads.
    // Never combine another repository's token with the outer trait's fetch.
    let artifact = match repository.preparation_source() {
        Some(source) => source.fetch(&key.release).await?,
        None => repository.fetch(&key.release).await?,
    };
    verify(&artifact, key)?;
    let prepared = backend.prepare_for_use(&artifact, key).await?;
    let imports = artifact
        .manifest
        .imports
        .iter()
        .map(|import| import.contract.clone())
        .collect();
    Ok(PreparedActivation { prepared, imports })
}

fn verify(artifact: &CapsuleArtifact, key: &PreparationKey) -> Result<(), PlatformError> {
    let actual = content_digest(&artifact.component_bytes);
    if !artifact
        .descriptor
        .release_digest
        .0
        .eq_ignore_ascii_case(&key.release.0)
        || actual != key.release
        || !artifact
            .manifest
            .component_digest
            .0
            .eq_ignore_ascii_case(&actual.0)
        || artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64
    {
        return Err(PlatformError {
            code: PlatformErrorCode::CorruptArtifact,
            message: "artifact repository returned a different release".to_owned(),
            retryable: false,
            details: Vec::new(),
        });
    }
    Ok(())
}
