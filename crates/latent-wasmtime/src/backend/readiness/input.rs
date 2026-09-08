use latent_artifacts::{
    ArtifactPreparationIdentity, ArtifactPreparationReadLimits, CapsuleArtifact,
    OwnedArtifactPreparationSource,
};
use latent_core::PlatformError;
use latent_executor::PreparationKey;

use crate::backend::preparation::{
    counters, retained_metadata_bytes, Compilation, ComponentIntegrity,
};
use crate::backend::{prepared_handle, PreparationContext, PreparedRuntime};
use crate::cache::{PrepareAccess, PrepareReservation};
use crate::compiler::{CompilationResult, QueueWindow};
use crate::preparation_metadata::MetadataIdentity;
use crate::PreparationStage;

pub(in crate::backend) enum ArtifactInput {
    Source {
        source: OwnedArtifactPreparationSource,
        limits: ArtifactPreparationReadLimits,
    },
    Fetched {
        artifact: CapsuleArtifact,
        metadata: MetadataIdentity,
    },
}

impl PreparationContext {
    pub(in crate::backend) fn compile_input(
        &self,
        input: ArtifactInput,
        key: PreparationKey,
        mut handle: String,
        authentication: Option<ArtifactPreparationIdentity>,
        mut reservation: PrepareReservation<PreparedRuntime>,
        queue: QueueWindow,
    ) -> Result<CompilationResult<PreparedRuntime>, PlatformError> {
        let job = self.observer.begin(&key.release);
        job.record_queue_wait(queue.started_nanos, queue.finished_nanos);
        // This input owner (including its source/root lock) remains in this
        // stack frame until all synchronous validation and compilation finish.
        let (artifact, prevalidated, integrity) = match &input {
            ArtifactInput::Source { source, limits } => {
                let fetch = job.stage(PreparationStage::RepositoryFetchVerified);
                let artifact = source.fetch_blocking(&key.release, *limits)?;
                fetch.complete();
                (
                    std::borrow::Cow::Owned(artifact),
                    None,
                    ComponentIntegrity::VerifiedBySource,
                )
            }
            ArtifactInput::Fetched { artifact, metadata } => (
                std::borrow::Cow::Borrowed(artifact),
                Some(metadata),
                ComponentIntegrity::Verify,
            ),
        };
        let validation = job.stage(PreparationStage::MetadataValidation);
        self.validate_repository_manifest(&artifact)?;
        self.validate_key(&artifact, &key)?;
        self.validate_manifest(&artifact)?;
        let component_digest = self.component_identity(&artifact, &key, integrity)?;
        let metadata_bytes = if let Some(identity) = &authentication {
            counters::add(&self.preparation.metadata_fingerprints, 1);
            identity.verify_metadata(
                &artifact,
                self.config.maximum_artifact_metadata_bytes,
                self.config.value_codec_limits.max_depth,
            )?;
            retained_metadata_bytes(identity.metadata().charged_bytes(), Some(identity))?
        } else {
            let discovered;
            let metadata = if let Some(metadata) = prevalidated {
                metadata
            } else {
                discovered = self.metadata_identity(&artifact)?;
                &discovered
            };
            handle = prepared_handle(&key, &component_digest, &metadata.digest);
            retained_metadata_bytes(metadata.bytes, None)?
        };
        validation.complete();
        if authentication.is_none() {
            match reservation.rekey(handle.clone())? {
                PrepareAccess::Hit(runtime) => {
                    return Ok(CompilationResult {
                        runtime,
                        reservation: None,
                        observation: job,
                    })
                }
                PrepareAccess::Compile(owned) => reservation = owned,
            }
        }
        let runtime = self.build_runtime(
            &artifact,
            &key,
            Compilation {
                handle,
                component_digest,
                metadata_bytes,
                authentication,
            },
            &job,
        )?;
        Ok(CompilationResult {
            runtime,
            reservation: Some(reservation),
            observation: job,
        })
    }
}
