//! Repository authority moves into owned jobs; factory ownership stays in callers.

mod input;
mod ownership;

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_artifacts::{ArtifactPreparationReadBounds, ArtifactRepository};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::{PreparationKey, PreparedReadiness};

use super::preparation::{authenticated_handle, counters, retained_metadata_bytes};
use super::WasmtimeBackend;
use crate::compiler::{Acquisition, Admission, CoalescingKey};
use crate::containment::platform_error;

impl WasmtimeBackend {
    pub(super) async fn prepare_ready_repository(
        &self,
        repository: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
    ) -> Result<PreparedReadiness, PlatformError> {
        let pool = self
            .shared
            .compiler
            .as_ref()
            .ok_or_else(|| invalid("prepared-readiness-unsupported"))?;
        let context = &self.shared.preparation_context;
        counters::add(&context.preparation.repository_acquisitions, 1);
        context.validate_engine_key(&key)?;
        let source = Arc::clone(&repository).owned_preparation_source();
        let identity = source
            .as_ref()
            .map(|source| source.identity(&key.release))
            .transpose()?
            .flatten();
        let mut bounds = None;
        let (handle, source_bytes, metadata_bytes) = if let Some(identity) = &identity {
            context.validate_identity(identity, &key)?;
            (
                authenticated_handle(&key, identity),
                usize::try_from(identity.component_bytes())
                    .map_err(|_| invalid("component-byte-overflow"))?,
                context.reserved_metadata(retained_metadata_bytes(
                    identity.metadata().charged_bytes(),
                    Some(identity),
                )?)?,
            )
        } else {
            bounds = source
                .as_ref()
                .map(|source| source.read_bounds(&key.release))
                .transpose()?;
            let bytes = bounds.map_or(self.config.maximum_component_bytes as u64, |bounds| {
                bounds.component_bytes
            });
            if bytes == 0 {
                return Err(super::preparation::empty_component());
            }
            if bytes > self.config.maximum_component_bytes as u64 {
                return Err(invalid("component-byte-limit"));
            }
            let generation = context
                .next_untrusted
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                    value.checked_add(1)
                })
                .map_err(|_| invalid("preparation-generation-exhausted"))?;
            (
                format!("wasmtime-readiness-pending:{generation}"),
                bytes as usize,
                context.reserved_metadata(retained_metadata_bytes(
                    self.config.maximum_artifact_metadata_bytes,
                    None,
                )?)?,
            )
        };
        let admission = Admission {
            identity: identity.clone().map(|source| CoalescingKey {
                key: key.clone(),
                source,
            }),
            handle: handle.clone(),
            source_bytes,
            metadata_bytes,
            document_bytes: 0,
        };
        let acquired = pool.acquire(admission)?;
        let pin = match acquired {
            Acquisition::Ready(pin) => {
                counters::add(
                    &context.preparation.authenticated_hits,
                    u64::from(identity.is_some()),
                );
                pin
            }
            Acquisition::Waiting { future, owner } => {
                if owner {
                    counters::add(
                        &context.preparation.authenticated_misses,
                        u64::from(identity.is_some()),
                    );
                    counters::add(&context.preparation.repository_fetches, 1);
                    let input = if let Some(source) = source {
                        let bounds = bounds.map_or_else(|| source.read_bounds(&key.release), Ok)?;
                        if bounds.component_bytes != source_bytes as u64 {
                            return Err(invalid("preparation-read-size-changed"));
                        }
                        future.reserve_documents(document_bytes(bounds)?)?;
                        input::ArtifactInput::Source {
                            source,
                            limits: bounds.into_limits(source_bytes),
                        }
                    } else {
                        // The caller owns this arbitrary async future. It is never
                        // polled by a compiler worker or mistaken for a sync read.
                        let artifact = repository.fetch(&key.release).await?;
                        if artifact.component_bytes.capacity() > self.config.maximum_component_bytes
                        {
                            return Err(invalid("component-owned-byte-limit"));
                        }
                        let metadata = context.metadata_identity(&artifact)?;
                        input::ArtifactInput::Fetched { artifact, metadata }
                    };
                    let context = Arc::clone(context);
                    let key = key.clone();
                    let authentication = identity.clone();
                    future.start(move |reservation| {
                        Box::new(move || {
                            context.compile_input(input, key, handle, authentication, reservation)
                        })
                    })?;
                } else {
                    // Only the distinct job owns the directory/root lock.
                    drop(source);
                }
                future.await?
            }
        };
        if pin.runtime.descriptor.key != key || pin.runtime.authentication != identity {
            return Err(invalid("prepared-source-association"));
        }
        Ok(self.ready_owner(pin))
    }
}

trait ReadLimits {
    fn into_limits(self, component: usize) -> latent_artifacts::ArtifactPreparationReadLimits;
}

impl ReadLimits for ArtifactPreparationReadBounds {
    fn into_limits(self, component: usize) -> latent_artifacts::ArtifactPreparationReadLimits {
        latent_artifacts::ArtifactPreparationReadLimits {
            maximum_component_bytes: component,
            maximum_metadata_document_bytes: self.maximum_metadata_document_bytes,
            maximum_manifest_document_bytes: self.maximum_manifest_document_bytes,
        }
    }
}

fn document_bytes(bounds: ArtifactPreparationReadBounds) -> Result<usize, PlatformError> {
    bounds
        .maximum_metadata_document_bytes
        .checked_add(bounds.maximum_manifest_document_bytes)
        .and_then(|bytes| bytes.checked_add(64 * 1024))
        .ok_or_else(|| invalid("preparation-document-overflow"))
}

fn invalid(reason: &'static str) -> PlatformError {
    platform_error(PlatformErrorCode::ResourceExhausted, reason, false)
}
