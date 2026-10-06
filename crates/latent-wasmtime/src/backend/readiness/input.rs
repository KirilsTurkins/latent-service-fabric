use latent_artifacts::{
    ArtifactPreparationReadLimits, CapsuleArtifact, OwnedArtifactPreparationSource,
};
use latent_core::PlatformError;
use latent_executor::PreparationKey;

use super::worker_wait::WorkerWindow;
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
        artifact: Box<CapsuleArtifact>,
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

pub(in crate::backend) struct CompileInput<'a> {
    pub input: ArtifactInput,
    pub key: &'a PreparationKey,
    pub handle: String,
    pub authority: SourceAuthority,
    pub reservation: PrepareReservation<PreparedRuntime>,
    pub queue: QueueWindow,
    pub worker_wait: Option<&'a WorkerWindow>,
}

struct ReadArtifact<'a> {
    artifact: std::borrow::Cow<'a, CapsuleArtifact>,
    prevalidated: Option<&'a MetadataIdentity>,
    integrity: ComponentIntegrity,
}

impl ArtifactInput {
    fn read<'a>(
        &'a self,
        native: Option<&'a crate::aot::supervisor::AotPreparedInput>,
        key: &PreparationKey,
        worker_wait: Option<&WorkerWindow>,
        eligibility: Option<&latent_artifacts::ReleaseUseEligibility>,
        job: &crate::preparation_observer::PreparationJob,
    ) -> Result<ReadArtifact<'a>, PlatformError> {
        let (artifact, prevalidated, integrity) = match self {
            Self::Native(_) => (
                std::borrow::Cow::Borrowed(native.expect("checked input").artifact()),
                None,
                ComponentIntegrity::VerifiedBySource,
            ),
            Self::Source { source, limits } => {
                let fetch = job.stage(PreparationStage::RepositoryFetchVerified);
                let artifact = match (worker_wait, eligibility) {
                    (Some(wait), Some(original)) => source.fetch_blocking_selected_with_wait(
                        &key.release,
                        key.publication.as_ref(),
                        *limits,
                        original,
                        wait,
                    )?,
                    _ => source.fetch_blocking_selected(
                        &key.release,
                        key.publication.as_ref(),
                        *limits,
                    )?,
                };
                fetch.complete();
                (
                    std::borrow::Cow::Owned(artifact),
                    None,
                    ComponentIntegrity::VerifiedBySource,
                )
            }
            Self::Fetched { artifact, metadata } => (
                std::borrow::Cow::Borrowed(artifact.as_ref()),
                Some(metadata),
                ComponentIntegrity::Verify,
            ),
        };
        Ok(ReadArtifact {
            artifact,
            prevalidated,
            integrity,
        })
    }
}

impl PreparationContext {
    pub(in crate::backend) fn compile_input(
        &self,
        request: CompileInput<'_>,
    ) -> Result<CompilationResult<PreparedRuntime>, PlatformError> {
        let CompileInput {
            mut input,
            key,
            handle,
            authority,
            mut reservation,
            queue,
            worker_wait,
        } = request;
        WorkerWindow::check(worker_wait, || {
            self.check_eligibility(
                authority.eligibility.as_ref(),
                &key.release,
                key.publication.as_ref(),
            )
        })?;
        let job = self.observer.begin(&key.release);
        job.record_queue_wait(queue.started_nanos, queue.finished_nanos);
        let mut native = input.read_native(&authority, &job)?;
        // Retain the affine input, its sealed source/root lock and checked native
        // owner through every synchronous validation, compilation and adoption.
        let read = input.read(
            native.as_ref(),
            key,
            worker_wait,
            authority.eligibility.as_ref(),
            &job,
        )?;
        let compilation = self.validate_input(&read, key, handle, authority, &job)?;
        if compilation.authentication.is_none() {
            match reservation.rekey(compilation.handle.clone())? {
                PrepareAccess::Hit(runtime) => {
                    if let Some(native) = &native {
                        native.check()?;
                    }
                    if runtime.eligibility != compilation.eligibility {
                        return Err(crate::backend::admission_association_error());
                    }
                    WorkerWindow::check(worker_wait, || self.check_runtime(&runtime))?;
                    return Ok(CompilationResult {
                        runtime,
                        reservation: None,
                        observation: job,
                    });
                }
                PrepareAccess::Compile(owned) => reservation = owned,
            }
        }
        let runtime = if matches!(&input, ArtifactInput::Native(_)) {
            drop(read);
            self.build_native_runtime(
                native.as_mut().expect("checked input"),
                key,
                compilation,
                &job,
            )?
        } else {
            self.build_runtime_with_wait(&read.artifact, key, compilation, &job, worker_wait)?
        };
        reservation.track_runtime(&runtime)?;
        Ok(CompilationResult {
            runtime,
            reservation: Some(reservation),
            observation: job,
        })
    }

    fn validate_input(
        &self,
        read: &ReadArtifact<'_>,
        key: &PreparationKey,
        mut handle: String,
        authority: SourceAuthority,
        job: &crate::preparation_observer::PreparationJob,
    ) -> Result<Compilation, PlatformError> {
        let SourceAuthority {
            authentication,
            eligibility,
        } = authority;
        let artifact = &read.artifact;
        let validation = job.stage(PreparationStage::MetadataValidation);
        self.validate_repository_manifest(artifact)?;
        self.validate_key(artifact, key)?;
        self.validate_manifest(artifact)?;
        let component_digest = self.component_identity(artifact, key, read.integrity)?;
        let metadata_bytes = if let Some(identity) = &authentication {
            counters::add(&self.preparation.metadata_fingerprints, 1);
            identity.verify_metadata(
                artifact,
                self.config.maximum_artifact_metadata_bytes,
                self.config.value_codec_limits.max_depth,
            )?;
            retained_metadata_bytes(
                identity.metadata().charged_bytes(),
                Some(identity),
                eligibility.as_ref(),
                key.publication.as_ref(),
            )?
        } else {
            let discovered;
            let metadata = if let Some(metadata) = read.prevalidated {
                metadata
            } else {
                discovered = self.metadata_identity(artifact)?;
                &discovered
            };
            handle = crate::backend::admission::scoped_handle(
                prepared_handle(key, &component_digest, &metadata.digest),
                eligibility.as_ref(),
            );
            retained_metadata_bytes(
                metadata.bytes,
                None,
                eligibility.as_ref(),
                key.publication.as_ref(),
            )?
        };
        validation.complete();
        Ok(Compilation {
            handle,
            component_digest,
            metadata_bytes,
            authentication,
            eligibility,
        })
    }
}
