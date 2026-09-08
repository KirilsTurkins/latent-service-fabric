//! Identical synchronous compilation boundaries for control and worker jobs.

use std::sync::Arc;

use latent_artifacts::CapsuleArtifact;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparationKey;
use wasmtime::component::Component;

use super::{metadata_overflow, Compilation};
use crate::backend::{bounded_error, PreparedRuntime, WasmtimeBackend};
use crate::cache::PrepareReservation;
use crate::config::PHASE0_BACKEND_ID;
use crate::containment::platform_error;
use crate::preparation_observer::{PreparationJob, PreparationStage};
use crate::surface;

impl WasmtimeBackend {
    pub(in crate::backend) fn compile_runtime(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
        input: Compilation,
        reservation: PrepareReservation<PreparedRuntime>,
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
        let runtime = Arc::new(PreparedRuntime {
            pre,
            declared_budget: artifact.manifest.execution.resource_budget_ceiling.clone(),
            surface,
            descriptor,
            authentication: input.authentication,
            // The existing full metadata charge includes these manifest fields.
            imports: artifact
                .manifest
                .imports
                .iter()
                .map(|import| import.contract.clone())
                .collect(),
        });
        linking.complete();
        let adoption = job.stage(PreparationStage::CacheAdoption);
        if self.config.prepared_cache_enabled {
            reservation.publish_with_metadata(Arc::clone(&runtime), image_bytes, metadata_bytes)?;
        } else {
            if image_bytes > self.config.prepared_cache_maximum_compiled_image_bytes {
                return Err(platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "compiled component image exceeds the configured limit",
                    false,
                ));
            }
            let mut slot = self.lock_uncached_prepared();
            if slot.is_some() {
                return Err(platform_error(
                    PlatformErrorCode::StateConflict,
                    "cache-disabled preparation is still owned by an active runner",
                    true,
                ));
            }
            *slot = Some((input.handle, Arc::clone(&runtime)));
            drop(slot);
            drop(reservation);
        }
        adoption.complete();
        Ok(runtime)
    }
}
