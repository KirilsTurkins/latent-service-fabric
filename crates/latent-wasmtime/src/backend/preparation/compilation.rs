//! Identical synchronous compilation boundaries for control and worker jobs.

use std::sync::Arc;

use latent_artifacts::CapsuleArtifact;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparationKey;
use wasmtime::component::Component;

use super::{metadata_overflow, Compilation};
use crate::backend::{bounded_error, PreparedRuntime};
use crate::cache::PrepareReservation;
use crate::config::PHASE0_BACKEND_ID;
use crate::containment::platform_error;
use crate::preparation_observer::{PreparationJob, PreparationStage};
use crate::surface;

impl super::super::PreparationContext {
    pub(in crate::backend) fn compile_runtime(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
        input: Compilation,
        mut reservation: PrepareReservation<PreparedRuntime>,
        job: &PreparationJob,
    ) -> Result<Arc<PreparedRuntime>, PlatformError> {
        let runtime = self.build_runtime(artifact, key, input, job)?;
        let adoption = job.stage(PreparationStage::CacheAdoption);
        if self.config.prepared_cache_enabled {
            reservation.track_runtime(&runtime)?;
            reservation.publish_with_metadata(
                Arc::clone(&runtime),
                runtime.image_bytes,
                runtime.metadata_bytes,
            )?;
        } else {
            if runtime.image_bytes > self.config.prepared_cache_maximum_compiled_image_bytes {
                return Err(platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "compiled component image exceeds the configured limit",
                    false,
                ));
            }
            let mut slot = self
                .uncached
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if slot.is_some() {
                return Err(platform_error(
                    PlatformErrorCode::StateConflict,
                    "cache-disabled preparation is still owned by an active runner",
                    true,
                ));
            }
            *slot = Some((
                runtime.descriptor.opaque_handle.clone(),
                Arc::clone(&runtime),
            ));
            drop(slot);
            drop(reservation);
        }
        adoption.complete();
        Ok(runtime)
    }

    pub(in crate::backend) fn build_runtime(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
        input: Compilation,
        job: &PreparationJob,
    ) -> Result<Arc<PreparedRuntime>, PlatformError> {
        let compilation = job.stage(PreparationStage::ComponentNew);
        let component = Component::new(&self.engine, &artifact.component_bytes);
        if component.is_ok() {
            compilation.complete();
        } else {
            drop(compilation);
        }
        let component = component.map_err(|error| {
            platform_error(
                PlatformErrorCode::CorruptArtifact,
                &format!("component validation failed: {}", bounded_error(&error)),
                false,
            )
        })?;
        let linking = job.stage(PreparationStage::SurfaceLink);
        let surface = surface::validate(&component, &self.engine, artifact, &self.config)?;
        let metadata_bytes = input
            .metadata_bytes
            .checked_add(surface.retained_bytes)
            .ok_or_else(metadata_overflow)?;
        let pre = self.link_component(&component)?;
        if self.profile.id == PHASE0_BACKEND_ID {
            crate::phase0::validate_prepared(&pre)?;
        }
        let image = component.image_range();
        let image_bytes = image.end.addr().saturating_sub(image.start.addr());
        let descriptor = self.prepared_descriptor(
            artifact,
            key.clone(),
            input.handle.clone(),
            input.component_digest,
        );
        // InstancePre now owns the image. Do not retain an extra local native
        // owner beyond construction of its uniquely charged prepared runtime.
        drop(component);
        let runtime = Arc::new(PreparedRuntime {
            pre,
            declared_budget: artifact.manifest.execution.resource_budget_ceiling.clone(),
            surface,
            descriptor,
            authentication: input.authentication,
            metadata_bytes,
            image_bytes,
            // The existing full metadata charge includes these manifest fields.
            imports: artifact
                .manifest
                .imports
                .iter()
                .map(|import| import.contract.clone())
                .collect(),
            lifetime_charge: self
                .runtime_ledger
                .register(crate::cache::PreparedRuntimeCost {
                    source_bytes: artifact.component_bytes.len(),
                    metadata_bytes,
                    compiled_image_bytes: image_bytes,
                })?,
        });
        linking.complete();
        Ok(runtime)
    }
}
