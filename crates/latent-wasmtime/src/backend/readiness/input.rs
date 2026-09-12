use latent_artifacts::{
    ArtifactPreparationReadLimits, CapsuleArtifact, OwnedArtifactPreparationSource,
};
use latent_core::PlatformError;
use latent_executor::PreparationKey;

use crate::backend::preparation::{
    counters, retained_metadata_bytes, Compilation, ComponentIntegrity, SourceAuthority,
};
use crate::backend::{prepared_handle, PreparationContext, PreparedRuntime};
use crate::cache::{PrepareAccess, PrepareReservation};
use crate::compiler::{CompilationResult, QueueWindow};
use crate::preparation_metadata::MetadataIdentity;
use crate::PreparationStage;

pub(in crate::backend) enum ArtifactInput {
    Native(Option<crate::aot::AotCompilationJob>),
    Source {
        source: OwnedArtifactPreparationSource,
        limits: ArtifactPreparationReadLimits,
    },
    Fetched {
        artifact: CapsuleArtifact,
        metadata: MetadataIdentity,
    },
}

impl ArtifactInput {
    fn read_native(
        &mut self,
        authority: &SourceAuthority,
        observation: &crate::preparation_observer::PreparationJob,
    ) -> Result<Option<crate::aot::supervisor::AotPreparedInput>, PlatformError> {
        let Self::Native(pending) = self else {
            return Ok(None);
        };
        let fetch = observation.stage(PreparationStage::RepositoryFetchVerified);
        let checked = pending.take().expect("affine native input").read()?;
        if checked.preparation_identity() != authority.authentication.as_ref()
            || Some(checked.eligibility()) != authority.eligibility.as_ref()
        {
            return Err(crate::backend::admission_association_error());
        }
        checked.check()?;
        fetch.complete();
        Ok(Some(checked))
    }
}

impl PreparationContext {
    #[expect(
        clippy::too_many_lines,
        reason = "one scope retains source and native ownership through validation, linking and adoption"
    )]
    pub(in crate::backend) fn compile_input(
        &self,
        mut input: ArtifactInput,
        key: PreparationKey,
        mut handle: String,
        authority: SourceAuthority,
        mut reservation: PrepareReservation<PreparedRuntime>,
        queue: QueueWindow,
    ) -> Result<CompilationResult<PreparedRuntime>, PlatformError> {
        self.check_eligibility(authority.eligibility.as_ref(), &key.release)?;
        let job = self.observer.begin(&key.release);
        job.record_queue_wait(queue.started_nanos, queue.finished_nanos);
        let mut native = input.read_native(&authority, &job)?;
        let SourceAuthority {
            authentication,
            eligibility,
        } = authority;
        // This input owner (including its source/root lock) remains in this
        // stack frame until all synchronous validation and compilation finish.
        let (artifact, prevalidated, integrity) = match &input {
            ArtifactInput::Native(_) => (
                std::borrow::Cow::Borrowed(native.as_ref().expect("checked input").artifact()),
                None,
                ComponentIntegrity::VerifiedBySource,
            ),
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
            retained_metadata_bytes(
                identity.metadata().charged_bytes(),
                Some(identity),
                eligibility.as_ref(),
            )?
        } else {
            let discovered;
            let metadata = if let Some(metadata) = prevalidated {
                metadata
            } else {
                discovered = self.metadata_identity(&artifact)?;
                &discovered
            };
            handle = crate::backend::admission::scoped_handle(
                prepared_handle(&key, &component_digest, &metadata.digest),
                eligibility.as_ref(),
            );
            retained_metadata_bytes(metadata.bytes, None, eligibility.as_ref())?
        };
        validation.complete();
        if authentication.is_none() {
            match reservation.rekey(handle.clone())? {
                PrepareAccess::Hit(runtime) => {
                    if let Some(native) = &native {
                        native.check()?;
                    }
                    if runtime.eligibility != eligibility {
                        return Err(crate::backend::admission_association_error());
                    }
                    self.check_runtime(&runtime)?;
                    return Ok(CompilationResult {
                        runtime,
                        reservation: None,
                        observation: job,
                    });
                }
                PrepareAccess::Compile(owned) => reservation = owned,
            }
        }
        let compilation = Compilation {
            handle,
            component_digest,
            metadata_bytes,
            authentication,
            eligibility,
        };
        let runtime = if matches!(&input, ArtifactInput::Native(_)) {
            drop(artifact);
            let native = native.as_mut().expect("checked input");
            self.build_native_runtime(native, &key, compilation, &job)?
        } else {
            self.build_runtime(&artifact, &key, compilation, &job)?
        };
        reservation.track_runtime(&runtime)?;
        Ok(CompilationResult {
            runtime,
            reservation: Some(reservation),
            observation: job,
        })
    }
}
