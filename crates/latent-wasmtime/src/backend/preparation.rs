//! Repository-authenticated acquisition under the existing affine capacity gates.

mod compilation;
mod counters;
pub use counters::PreparationActivitySnapshot;
pub(super) use counters::PreparationCounters;

use std::mem::size_of;

use latent_artifacts::{ArtifactPreparationIdentity, ArtifactRepository, CapsuleArtifact};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::{PreparationKey, PreparedActivation};

use super::WasmtimeBackend;
use crate::cache::PrepareAccess;
use crate::config::PHASE0_BACKEND_ID;
use crate::containment::platform_error;
use crate::preparation_metadata;
use crate::preparation_observer::PreparationStage;

pub(super) struct Compilation {
    pub(super) handle: String,
    pub(super) component_digest: String,
    pub(super) metadata_bytes: usize,
    pub(super) authentication: Option<ArtifactPreparationIdentity>,
}

#[derive(Clone, Copy)]
pub(super) enum ComponentIntegrity {
    Verify,
    VerifiedBySource,
}

impl WasmtimeBackend {
    /// Fixed factory-owned counters, including attempts that later fail.
    #[must_use]
    pub fn preparation_activity_snapshot(&self) -> PreparationActivitySnapshot {
        self.shared.preparation.snapshot()
    }

    pub(super) fn metadata_identity(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<preparation_metadata::MetadataIdentity, PlatformError> {
        counters::add(&self.shared.preparation.metadata_fingerprints, 1);
        preparation_metadata::identity(
            artifact,
            self.config.maximum_artifact_metadata_bytes,
            self.config.value_codec_limits.max_depth,
        )
    }

    pub(super) fn record_component_hash(&self, bytes: usize) {
        counters::add(&self.shared.preparation.component_hashes, 1);
        counters::add(
            &self.shared.preparation.component_bytes_hashed,
            u64::try_from(bytes).unwrap_or(u64::MAX),
        );
    }

    pub(super) async fn prepare_repository(
        &self,
        repository: &dyn ArtifactRepository,
        key: &PreparationKey,
    ) -> Result<PreparedActivation, PlatformError> {
        counters::add(&self.shared.preparation.repository_acquisitions, 1);
        self.validate_engine_key(key)?;
        let source = repository.preparation_source();
        let identity = source
            .as_ref()
            .map(|source| source.identity(&key.release))
            .transpose()?
            .flatten();
        let permit = self.shared.instances.try_acquire()?;
        let Some(identity) = identity.filter(|_| self.config.prepared_cache_enabled) else {
            counters::add(&self.shared.preparation.repository_fetches, 1);
            let mut job = self.shared.preparation_observer.begin(&key.release);
            let mut fetch = job.stage(PreparationStage::RepositoryFetchVerified);
            if source.is_none() {
                // An arbitrary asynchronous fetch may share this task thread
                // with unrelated work even when it resumes on the same thread.
                job.suppress_thread_cpu();
                fetch.suppress_thread_cpu();
            }
            // Even a stamp-ineligible source owns its fallback read; an outer
            // repository adapter cannot redirect it to another repository.
            let (artifact, integrity) = match source {
                Some(source) => (
                    source.fetch(&key.release).await?,
                    ComponentIntegrity::VerifiedBySource,
                ),
                None => (
                    repository.fetch(&key.release).await?,
                    ComponentIntegrity::Verify,
                ),
            };
            fetch.complete();
            self.validate_repository_manifest(&artifact)?;
            let runtime = self.prepare_runtime_with_integrity(&artifact, key, integrity, &job)?;
            job.complete();
            return Ok(self.activation_use(runtime, permit));
        };
        self.validate_identity(&identity, key)?;
        let metadata_bytes =
            retained_metadata_bytes(identity.metadata().charged_bytes(), Some(&identity))?;
        let handle = authenticated_handle(key, &identity);
        let reservation = match self.shared.cache.begin(
            handle.clone(),
            usize::try_from(identity.component_bytes()).map_err(|_| metadata_overflow())?,
            self.reserved_metadata(metadata_bytes)?,
        )? {
            PrepareAccess::Hit(runtime) => {
                if runtime.authentication.as_ref() != Some(&identity)
                    || runtime.descriptor.key != *key
                {
                    return Err(platform_error(
                        PlatformErrorCode::CorruptArtifact,
                        "prepared repository identity does not match its cache entry",
                        false,
                    ));
                }
                counters::add(&self.shared.preparation.authenticated_hits, 1);
                return Ok(self.activation_use(runtime, permit));
            }
            PrepareAccess::Compile(reservation) => reservation,
        };
        counters::add(&self.shared.preparation.authenticated_misses, 1);
        counters::add(&self.shared.preparation.repository_fetches, 1);
        let job = self.shared.preparation_observer.begin(&key.release);
        let fetch = job.stage(PreparationStage::RepositoryFetchVerified);
        let artifact = source
            .expect("identity always belongs to a selected source")
            .fetch(&key.release)
            .await?;
        fetch.complete();
        let validation = job.stage(PreparationStage::MetadataValidation);
        self.validate_repository_manifest(&artifact)?;
        counters::add(&self.shared.preparation.metadata_fingerprints, 1);
        identity.verify_metadata(
            &artifact,
            self.config.maximum_artifact_metadata_bytes,
            self.config.value_codec_limits.max_depth,
        )?;
        self.validate_key(&artifact, key)?;
        self.validate_manifest(&artifact)?;
        let component_digest =
            self.component_identity(&artifact, key, ComponentIntegrity::VerifiedBySource)?;
        validation.complete();
        let runtime = self.compile_runtime(
            &artifact,
            key,
            Compilation {
                handle,
                component_digest,
                metadata_bytes,
                authentication: Some(identity),
            },
            reservation,
            &job,
        )?;
        job.complete();
        Ok(self.activation_use(runtime, permit))
    }

    fn validate_repository_manifest(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<(), PlatformError> {
        if self.profile.id == PHASE0_BACKEND_ID {
            crate::phase0::validate_manifest(artifact)?;
        }
        Ok(())
    }

    pub(super) fn component_identity(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
        integrity: ComponentIntegrity,
    ) -> Result<String, PlatformError> {
        let digest = match integrity {
            ComponentIntegrity::Verify => self.validate_component_bytes(artifact)?,
            ComponentIntegrity::VerifiedBySource => {
                if artifact.component_bytes.is_empty() {
                    return Err(empty_component());
                }
                if artifact.component_bytes.len() > self.config.maximum_component_bytes {
                    return Err(platform_error(
                        PlatformErrorCode::ResourceExhausted,
                        "component artifact exceeds the configured byte limit",
                        false,
                    ));
                }
                if artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64
                    || !artifact
                        .manifest
                        .component_digest
                        .0
                        .eq_ignore_ascii_case(&artifact.descriptor.release_digest.0)
                {
                    return Err(platform_error(
                        PlatformErrorCode::CorruptArtifact,
                        "component content does not match the artifact descriptor",
                        false,
                    ));
                }
                artifact.descriptor.release_digest.0.to_ascii_lowercase()
            }
        };
        if digest != key.release.0 {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "preparation release does not match component content",
                false,
            ));
        }
        Ok(digest)
    }

    fn validate_identity(
        &self,
        identity: &ArtifactPreparationIdentity,
        key: &PreparationKey,
    ) -> Result<(), PlatformError> {
        if !identity.matches_release(&key.release) {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "artifact repository returned a different release",
                false,
            ));
        }
        if identity.component_bytes() == 0 {
            return Err(empty_component());
        }
        if identity.component_bytes() > self.config.maximum_component_bytes as u64 {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "component artifact exceeds the configured byte limit",
                false,
            ));
        }
        if identity.metadata().charged_bytes() > self.config.maximum_artifact_metadata_bytes
            || identity.metadata().required_type_depth() > self.config.value_codec_limits.max_depth
        {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "preparation metadata exceeds its configured bound",
                false,
            ));
        }
        Ok(())
    }

    pub(super) fn reserved_metadata(&self, metadata_bytes: usize) -> Result<usize, PlatformError> {
        metadata_bytes
            .checked_add(self.config.maximum_artifact_metadata_bytes)
            .ok_or_else(metadata_overflow)
    }
}

pub(super) fn retained_metadata_bytes(
    bytes: usize,
    identity: Option<&ArtifactPreparationIdentity>,
) -> Result<usize, PlatformError> {
    bytes
        .checked_add(identity.map_or(
            size_of::<Option<ArtifactPreparationIdentity>>(),
            |identity| {
                identity
                    .retained_bytes()
                    .max(size_of::<Option<ArtifactPreparationIdentity>>())
            },
        ))
        .ok_or_else(metadata_overflow)
}

fn metadata_overflow() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "prepared metadata accounting overflowed",
        false,
    )
}

fn empty_component() -> PlatformError {
    platform_error(
        PlatformErrorCode::CorruptArtifact,
        "component artifact is empty",
        false,
    )
}

fn authenticated_handle(key: &PreparationKey, identity: &ArtifactPreparationIdentity) -> String {
    let mut digest = blake3::Hasher::new();
    digest.update(b"lsf-wasmtime-authenticated-preparation-v1\0");
    for value in [
        &key.release.0,
        &key.engine_version,
        &key.engine_configuration_digest,
        &key.target_triple,
        &key.cpu_feature_set,
    ] {
        digest.update(&(value.len() as u64).to_le_bytes());
        digest.update(value.as_bytes());
    }
    digest.update(&identity.cache_digest());
    format!("wasmtime-authenticated:{}", digest.finalize().to_hex())
}
