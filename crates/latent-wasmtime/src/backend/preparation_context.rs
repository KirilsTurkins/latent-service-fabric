//! Immutable compiler inputs shared without retaining the runtime/pool owner.

use super::preparation::{
    counters, empty_component, metadata_overflow, ComponentIntegrity, PreparationCounters,
};
use super::{bounded_error, sha256_digest, PreparedRuntime};
use crate::bindings;
use crate::config::{WasmtimeConfig, PHASE0_BACKEND_ID};
use crate::containment::platform_error;
use crate::host::HostState;
use crate::preparation_observer::PreparationObserver;
use crate::{preparation_metadata, WasmtimeEngineProfile};
use latent_artifacts::{ArtifactPreparationIdentity, CapsuleArtifact};
use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use latent_executor::{PreparationKey, PreparedComponent};
use latent_manifest::{ExecutionBackendKind, StateModel, ThreadingModel};
use std::sync::{Arc, Mutex};
use wasmtime::component::{Component, InstancePre, Linker};
use wasmtime::Engine;

pub(super) struct PreparationContext {
    pub(super) next_untrusted: std::sync::atomic::AtomicU64,
    pub(super) engine: Engine,
    pub(super) profile: WasmtimeEngineProfile,
    pub(super) config: WasmtimeConfig,
    pub(super) preparation: Arc<PreparationCounters>,
    pub(super) observer: PreparationObserver,
    pub(super) uncached: Arc<Mutex<Option<(String, Arc<PreparedRuntime>)>>>,
}

impl PreparationContext {
    pub(super) fn validate_component_bytes(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<String, PlatformError> {
        if artifact.component_bytes.is_empty() {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "component artifact is empty",
                false,
            ));
        }
        if artifact.component_bytes.len() > self.config.maximum_component_bytes {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "component artifact exceeds the configured byte limit",
                false,
            ));
        }
        self.record_component_hash(artifact.component_bytes.len());
        let component_digest = sha256_digest(&artifact.component_bytes);
        if !artifact
            .manifest
            .component_digest
            .0
            .eq_ignore_ascii_case(&component_digest)
        {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "component content digest does not match the capsule manifest",
                false,
            ));
        }
        if !artifact
            .descriptor
            .release_digest
            .0
            .eq_ignore_ascii_case(&component_digest)
            || artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64
        {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "component content does not match the artifact descriptor",
                false,
            ));
        }
        Ok(component_digest)
    }

    pub(super) fn link_component(
        &self,
        component: &Component,
    ) -> Result<InstancePre<HostState>, PlatformError> {
        let mut linker = Linker::<HostState>::new(&self.engine);
        bindings::install_context_log_clock(&mut linker).map_err(|error| {
            platform_error(
                PlatformErrorCode::Internal,
                &format!("failed to bind host imports: {}", bounded_error(&error)),
                false,
            )
        })?;
        let pre = linker.instantiate_pre(component).map_err(|error| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                &format!(
                    "component imports cannot be resolved: {}",
                    bounded_error(&error)
                ),
                false,
            )
        })?;
        Ok(pre)
    }

    pub(super) fn validate_key(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
    ) -> Result<(), PlatformError> {
        if !key
            .release
            .0
            .eq_ignore_ascii_case(&artifact.descriptor.release_digest.0)
        {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "preparation release does not match the artifact descriptor",
                false,
            ));
        }
        self.validate_engine_key(key)
    }

    pub(super) fn validate_engine_key(&self, key: &PreparationKey) -> Result<(), PlatformError> {
        let expected_digest = self
            .profile
            .configuration
            .get("configuration-digest")
            .expect("profile always contains a configuration digest");
        if key.engine_version != self.profile.wasmtime_version
            || &key.engine_configuration_digest != expected_digest
            || key.target_triple != self.profile.target_triple
            || key.cpu_feature_set != self.profile.cpu_feature_set
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "preparation key does not match the active Wasmtime engine profile",
                false,
            ));
        }
        Ok(())
    }

    pub(super) fn validate_manifest(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<(), PlatformError> {
        let manifest = &artifact.manifest;
        if manifest.world.0.is_empty()
            || manifest.execution.backend != ExecutionBackendKind::WasmComponent
            || !matches!(
                manifest.execution.threading,
                ThreadingModel::SingleThreaded | ThreadingModel::Reentrant
            )
            || manifest.execution.state_model != StateModel::Stateless
        {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "backend requires a named world with stateless, single-threaded or reentrant Wasm Component execution",
                false,
            ));
        }
        let declared = &manifest.execution.resource_budget_ceiling;
        if declared.memory_bytes == 0
            || declared.memory_bytes > self.config.maximum_memory_bytes
            || declared.cpu_fuel == 0
            || declared.cpu_fuel > self.config.maximum_fuel
            || declared.wall_time_limit_millis == Some(0)
        {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "capsule-declared resource limits exceed the engine profile",
                false,
            ));
        }
        Ok(())
    }

    pub(super) fn prepared_descriptor(
        &self,
        artifact: &CapsuleArtifact,
        key: PreparationKey,
        handle: String,
        component_digest: String,
    ) -> PreparedComponent {
        let mut metadata = Metadata::new();
        metadata.insert("world".to_owned(), artifact.manifest.world.0.clone());
        metadata.insert(
            "imports".to_owned(),
            artifact
                .manifest
                .imports
                .iter()
                .map(|entry| entry.contract.0.as_str())
                .collect::<Vec<_>>()
                .join(","),
        );
        metadata.insert(
            "exports".to_owned(),
            artifact
                .manifest
                .exports
                .iter()
                .map(|entry| entry.contract.0.as_str())
                .collect::<Vec<_>>()
                .join(","),
        );
        metadata.insert("component-digest".to_owned(), component_digest);
        metadata.insert(
            "cache".to_owned(),
            if self.config.prepared_cache_enabled {
                "bounded-node-owned"
            } else {
                "runner-scoped-no-reuse"
            }
            .to_owned(),
        );
        metadata.insert(
            "resident-state".to_owned(),
            "compiled-component,linker,dynamic-indices".to_owned(),
        );
        metadata.insert("ambient-authority".to_owned(), "none".to_owned());
        PreparedComponent {
            key,
            backend: self.profile.id.clone(),
            opaque_handle: handle,
            metadata,
        }
    }

    pub(super) fn metadata_identity(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<preparation_metadata::MetadataIdentity, PlatformError> {
        counters::add(&self.preparation.metadata_fingerprints, 1);
        preparation_metadata::identity(
            artifact,
            self.config.maximum_artifact_metadata_bytes,
            self.config.value_codec_limits.max_depth,
        )
    }

    pub(super) fn record_component_hash(&self, bytes: usize) {
        counters::add(&self.preparation.component_hashes, 1);
        counters::add(
            &self.preparation.component_bytes_hashed,
            u64::try_from(bytes).unwrap_or(u64::MAX),
        );
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

    pub(super) fn validate_identity(
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

    pub(super) fn validate_repository_manifest(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<(), PlatformError> {
        if self.profile.id == PHASE0_BACKEND_ID {
            crate::phase0::validate_manifest(artifact)?;
        }
        Ok(())
    }
}
