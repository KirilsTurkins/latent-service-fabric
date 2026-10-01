//! Repository authority moves into owned jobs; factory ownership stays in callers.

mod input;
mod ownership;
pub(super) mod wait;
pub(super) mod worker_wait;

#[cfg(all(test, target_os = "linux"))]
mod tests;

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_artifacts::{ArtifactPreparationReadBounds, ArtifactRepository};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::{PreparationKey, PreparedReadiness};

use super::preparation::{
    authenticated_handle, counters, retained_metadata_bytes, SourceAuthority,
};
use super::WasmtimeBackend;
use crate::compiler::{Acquisition, Admission, CoalescingKey};
use crate::containment::platform_error;

struct ReadySourceLimits {
    handle: String,
    source_bytes: usize,
    metadata_bytes: usize,
    bounds: Option<ArtifactPreparationReadBounds>,
}

impl ReadySourceLimits {
    fn admission(
        &self,
        key: &PreparationKey,
        identity: Option<&latent_artifacts::ArtifactPreparationIdentity>,
        eligibility: Option<&latent_artifacts::ReleaseUseEligibility>,
    ) -> Admission {
        Admission {
            identity: identity.map(|source| CoalescingKey {
                key: key.clone(),
                source: source.clone(),
                eligibility: eligibility.cloned(),
            }),
            handle: self.handle.clone(),
            source_bytes: self.source_bytes,
            metadata_bytes: self.metadata_bytes,
            document_bytes: 0,
        }
    }
}

struct ReadyCompilation {
    key: PreparationKey,
    handle: String,
    source: Option<latent_artifacts::OwnedArtifactPreparationSource>,
    source_bytes: usize,
    bounds: Option<ArtifactPreparationReadBounds>,
    authority: SourceAuthority,
    wait_enabled: bool,
}

impl WasmtimeBackend {
    pub(super) async fn prepare_ready_repository(
        &self,
        repository: Arc<dyn ArtifactRepository>,
        key: PreparationKey,
        read_wait: Option<&dyn latent_executor::PreparationReadWait>,
    ) -> Result<PreparedReadiness, PlatformError> {
        // One finite caller-side read window, never one new window per check.
        // Opt-in sealed-source jobs have a separate real-clock worker window.
        // Materialization has a separate affine read window. Activation start
        // opts in only through the node's explicitly supplied host read timer.
        let window = wait::Window::new(read_wait);
        let pool = self
            .shared
            .compiler
            .as_ref()
            .ok_or_else(|| invalid("prepared-readiness-unsupported"))?;
        let context = &self.shared.preparation_context;
        counters::add(&context.preparation.repository_acquisitions, 1);
        context.validate_engine_key(&key)?;
        let source = Arc::clone(&repository).owned_preparation_source();
        let SourceAuthority {
            authentication: identity,
            eligibility,
        } = self
            .read_ready_authority(repository.as_ref(), &key, source.as_ref(), &window)
            .await?;
        let source_limits = self
            .ready_source_limits(
                &key,
                source.as_ref(),
                &SourceAuthority {
                    authentication: identity.clone(),
                    eligibility: eligibility.clone(),
                },
                &window,
            )
            .await?;
        let admission = source_limits.admission(&key, identity.as_ref(), eligibility.as_ref());
        // A later source snapshot may see refreshed catalog evidence. It must
        // never upgrade the original grant captured by this preparation.
        window
            .check(|| {
                context.check_eligibility(
                    eligibility.as_ref(),
                    &key.release,
                    key.publication.as_ref(),
                )
            })
            .await?;
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
                    self.start_ready_compilation(
                        repository.as_ref(),
                        &future,
                        &window,
                        ReadyCompilation {
                            key: key.clone(),
                            handle: source_limits.handle,
                            source,
                            source_bytes: source_limits.source_bytes,
                            bounds: source_limits.bounds,
                            authority: SourceAuthority {
                                authentication: identity.clone(),
                                eligibility: eligibility.clone(),
                            },
                            wait_enabled: read_wait.is_some(),
                        },
                    )
                    .await?;
                } else {
                    // Only the distinct job owns the directory/root lock.
                    drop(source);
                }
                drop(repository);
                future.await?
            }
        };
        if pin.runtime.descriptor.key != key
            || pin.runtime.authentication != identity
            || pin.runtime.eligibility != eligibility
        {
            return Err(invalid("prepared-source-association"));
        }
        window.check(|| context.check_runtime(&pin.runtime)).await?;
        Ok(self.ready_owner(pin))
    }
    async fn read_ready_authority(
        &self,
        repository: &dyn ArtifactRepository,
        key: &PreparationKey,
        source: Option<&latent_artifacts::OwnedArtifactPreparationSource>,
        window: &wait::Window<'_>,
    ) -> Result<SourceAuthority, PlatformError> {
        let context = &self.shared.preparation_context;
        let eligibility = if let Some(source) = source {
            window
                .check(|| {
                    source.execution_eligibility_selected(&key.release, key.publication.as_ref())
                })
                .await?
        } else {
            if repository
                .execution_eligibility_selected(&key.release, key.publication.as_ref())?
                .is_some()
            {
                return Err(super::admission_association_error());
            }
            None
        };
        window
            .check(|| {
                context.check_eligibility(
                    eligibility.as_ref(),
                    &key.release,
                    key.publication.as_ref(),
                )
            })
            .await?;
        let identity = if let Some(source) = source {
            window
                .check(|| source.identity_selected(&key.release, key.publication.as_ref()))
                .await?
        } else {
            None
        };
        Ok(SourceAuthority {
            authentication: identity,
            eligibility,
        })
    }

    async fn ready_source_limits(
        &self,
        key: &PreparationKey,
        source: Option<&latent_artifacts::OwnedArtifactPreparationSource>,
        authority: &SourceAuthority,
        window: &wait::Window<'_>,
    ) -> Result<ReadySourceLimits, PlatformError> {
        let context = &self.shared.preparation_context;
        let identity = &authority.authentication;
        let eligibility = &authority.eligibility;
        let mut bounds = None;
        let (handle, source_bytes, metadata_bytes) = if let Some(identity) = &identity {
            context.validate_identity(identity, key)?;
            (
                authenticated_handle(key, identity, eligibility.as_ref()),
                usize::try_from(identity.component_bytes())
                    .map_err(|_| invalid("component-byte-overflow"))?,
                context.reserved_metadata(retained_metadata_bytes(
                    identity.metadata().charged_bytes(),
                    Some(identity),
                    eligibility.as_ref(),
                    key.publication.as_ref(),
                )?)?,
            )
        } else {
            if let Some(source) = source {
                bounds = Some(
                    window
                        .check(|| {
                            source.read_bounds_selected(&key.release, key.publication.as_ref())
                        })
                        .await?,
                );
            }
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
                usize::try_from(bytes).map_err(|_| invalid("component-byte-overflow"))?,
                context.reserved_metadata(retained_metadata_bytes(
                    self.config.maximum_artifact_metadata_bytes,
                    None,
                    eligibility.as_ref(),
                    key.publication.as_ref(),
                )?)?,
            )
        };
        Ok(ReadySourceLimits {
            handle,
            source_bytes,
            metadata_bytes,
            bounds,
        })
    }

    async fn start_ready_compilation(
        &self,
        repository: &dyn ArtifactRepository,
        future: &crate::compiler::PreparationWait<super::PreparedRuntime>,
        window: &wait::Window<'_>,
        mut request: ReadyCompilation,
    ) -> Result<(), PlatformError> {
        let context = &self.shared.preparation_context;
        let input = request
            .read_input(context, repository, future, window)
            .await?;
        let context = Arc::clone(context);
        let ReadyCompilation {
            key,
            handle,
            authority,
            wait_enabled,
            ..
        } = request;
        let native_control = match &input {
            input::ArtifactInput::Native(Some(job)) => Some(job.control()),
            _ => None,
        };
        let worker_wait = if wait_enabled && matches!(&input, input::ArtifactInput::Source { .. }) {
            Some(worker_wait::WorkerWindow::new(future.control()?))
        } else {
            None
        };
        let build = move |reservation| -> crate::compiler::Task<super::PreparedRuntime> {
            Box::new(move |queue| {
                context.compile_input(input::CompileInput {
                    input,
                    key: &key,
                    handle,
                    authority,
                    reservation,
                    queue,
                    worker_wait: worker_wait.as_ref(),
                })
            })
        };
        if let Some(control) = native_control {
            future.start_with_control(Some(control), build)?;
        } else {
            future.start(build)?;
        }
        Ok(())
    }
}

impl ReadyCompilation {
    async fn read_input(
        &mut self,
        context: &super::PreparationContext,
        repository: &dyn ArtifactRepository,
        future: &crate::compiler::PreparationWait<super::PreparedRuntime>,
        window: &wait::Window<'_>,
    ) -> Result<input::ArtifactInput, PlatformError> {
        let input = if let Some(native) = &context.native_aot {
            let source = self.source.take();
            let native_source = source
                .as_ref()
                .ok_or_else(super::admission_association_error)?;
            let bounds = window
                .check(|| {
                    native_source
                        .read_bounds_selected(&self.key.release, self.key.publication.as_ref())
                })
                .await?;
            future.reserve_documents(document_bytes(bounds)?)?;
            let job = native.reserve(&self.key.release, self.key.publication.as_ref())?;
            drop(source);
            input::ArtifactInput::Native(Some(job))
        } else if let Some(source) = self.source.take() {
            let bounds = if let Some(bounds) = self.bounds {
                bounds
            } else {
                window
                    .check(|| {
                        source
                            .read_bounds_selected(&self.key.release, self.key.publication.as_ref())
                    })
                    .await?
            };
            if bounds.component_bytes != self.source_bytes as u64 {
                return Err(invalid("preparation-read-size-changed"));
            }
            future.reserve_documents(document_bytes(bounds)?)?;
            input::ArtifactInput::Source {
                source,
                limits: bounds.into_limits(self.source_bytes),
            }
        } else {
            // The caller owns this arbitrary async future. It is never
            // polled by a compiler worker or mistaken for a sync read.
            let artifact = repository.fetch(&self.key.release).await?;
            if artifact.component_bytes.capacity() > context.config.maximum_component_bytes {
                return Err(invalid("component-owned-byte-limit"));
            }
            let metadata = context.metadata_identity(&artifact)?;
            input::ArtifactInput::Fetched {
                artifact: Box::new(artifact),
                metadata,
            }
        };
        Ok(input)
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
