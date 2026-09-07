//! Legacy echo framing over the shared dynamic Component Model backend.

mod adapter;
#[cfg(test)]
mod tests;

use std::ops::Deref;

use latent_artifacts::CapsuleArtifact;
use latent_core::{
    BoxFuture, ErrorDetail, Metadata, PlatformError, PlatformErrorCode, ReleaseDigest,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest, GuestOutcome,
    PreparationKey, PreparedComponent, PreparedUse,
};
use latent_manifest::ExecutionBackendKind;

use crate::backend::WasmtimeBackend;
use crate::config::{DispatchMode, Phase0WasmtimeConfig, PHASE0_BACKEND_ID};
use crate::containment::{bounded_text, platform_error, MAX_DIAGNOSTIC_BYTES};
use crate::factory::WasmtimeComponentEngineFactory;
use crate::host::{BoundedLogSink, HostState};
use crate::surface::{CONTEXT_IMPORT, LOG_IMPORT};
use crate::{WasmtimeEngineFactory, WasmtimeEngineProfile};

pub const BACKEND_ID: &str = PHASE0_BACKEND_ID;
pub const ECHO_WORLD: &str = "examples:echo/service@0.1.0";
pub const ECHO_EXPORT: &str = "examples:echo/api@0.1.0";
pub const ECHO_SUCCESS_MEDIA_TYPE: &str = "text/plain; charset=utf-8";
pub const ECHO_DOMAIN_ERROR_MEDIA_TYPE: &str = "application/vnd.latent.echo-error+json";

/// Preserves the profiling API while sharing engine and preparation ownership.
pub struct Phase0WasmtimeEngineFactory {
    inner: WasmtimeComponentEngineFactory,
}

impl Phase0WasmtimeEngineFactory {
    pub fn new(config: Phase0WasmtimeConfig) -> Result<Self, PlatformError> {
        Ok(Self {
            inner: WasmtimeComponentEngineFactory::with_mode(config, DispatchMode::Phase0)?,
        })
    }

    #[must_use]
    pub fn preparation_key(&self, release: ReleaseDigest) -> PreparationKey {
        self.inner.preparation_key(release)
    }

    #[must_use]
    pub fn log_sink(&self) -> BoundedLogSink {
        self.inner.log_sink()
    }

    #[must_use]
    pub fn profile(&self) -> &WasmtimeEngineProfile {
        self.inner.profile()
    }

    #[must_use]
    pub fn create_backend_instance(&self) -> Phase0WasmtimeBackend {
        Phase0WasmtimeBackend {
            inner: self.inner.create_backend_instance(),
        }
    }
}

impl WasmtimeEngineFactory for Phase0WasmtimeEngineFactory {
    fn profile(&self) -> &WasmtimeEngineProfile {
        self.inner.profile()
    }

    fn create_backend(&self) -> Result<Box<dyn ExecutionBackend>, PlatformError> {
        Ok(Box::new(self.create_backend_instance()))
    }
}

/// Only adapts legacy payloads; all guest execution and cleanup remain shared.
pub struct Phase0WasmtimeBackend {
    inner: WasmtimeBackend,
}

impl Deref for Phase0WasmtimeBackend {
    type Target = WasmtimeBackend;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

impl Phase0WasmtimeBackend {
    fn adapt_request(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<ExecutionRequest, PlatformError> {
        // Leave the shared backend's initial cancellation/identity precedence
        // intact. Those paths do not inspect or execute a payload.
        if cancellation.is_cancelled()
            || cancellation.activation_id() != &request.activation.activation_id
        {
            return Ok(request);
        }
        adapter::request(request, self.inner.config.value_codec_limits)
    }
}

impl ExecutionBackend for Phase0WasmtimeBackend {
    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    fn preparation_key(&self, release: &ReleaseDigest) -> Result<PreparationKey, PlatformError> {
        self.inner.preparation_key(release)
    }

    fn prepare_for_use<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedUse, PlatformError>> {
        Box::pin(async move {
            validate_manifest(artifact)?;
            self.inner.prepare_for_use(artifact, key).await
        })
    }

    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let request = match self.adapt_request(request, cancellation) {
                Ok(request) => request,
                Err(error) => return ExecutionReport::reusable(Err(error)),
            };
            let report = self
                .inner
                .invoke_prepared_contained(request, prepared, cancellation)
                .await;
            adapter::report(report, self.inner.config.value_codec_limits)
        })
    }

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move {
            validate_manifest(artifact)?;
            self.inner.prepare(artifact, key).await
        })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            let request = self.adapt_request(request, cancellation)?;
            Ok(adapter::outcome(
                self.inner.invoke(request, cancellation).await?,
                self.inner.config.value_codec_limits,
            ))
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let request = match self.adapt_request(request, cancellation) {
                Ok(request) => request,
                // Adaptation has not created a store or other guest resource.
                Err(error) => return ExecutionReport::reusable(Err(error)),
            };
            let report = self.inner.invoke_contained(request, cancellation).await;
            adapter::report(report, self.inner.config.value_codec_limits)
        })
    }

    fn release(&self, prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.inner.release(prepared)
    }
}

fn validate_manifest(artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
    let manifest = &artifact.manifest;
    if manifest.world.0 != ECHO_WORLD {
        return Err(PlatformError {
            code: PlatformErrorCode::IncompatibleContract,
            message: "capsule declares an unexpected WIT world".to_owned(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: "unexpected-world".to_owned(),
                fields: Metadata::from([
                    ("expected".to_owned(), ECHO_WORLD.to_owned()),
                    (
                        "actual".to_owned(),
                        bounded_text(&manifest.world.0, MAX_DIAGNOSTIC_BYTES),
                    ),
                ]),
            }],
        });
    }
    if manifest.execution.backend != ExecutionBackendKind::WasmComponent {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "capsule does not select the Wasm Component execution backend",
            false,
        ));
    }
    if manifest.exports.len() != 1 || manifest.exports[0].contract.0 != ECHO_EXPORT {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "capsule exports do not match the Phase 0 echo contract",
            false,
        ));
    }
    if manifest.imports.len() != 2
        || manifest.imports.iter().any(|import| import.optional)
        || !manifest
            .imports
            .iter()
            .any(|import| import.contract.0 == CONTEXT_IMPORT)
        || !manifest
            .imports
            .iter()
            .any(|import| import.contract.0 == LOG_IMPORT)
    {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "capsule imports do not match the two required Phase 0 host capabilities",
            false,
        ));
    }
    Ok(())
}

/// The facade's extra signature restriction creates no store or instance.
/// The shared preparation path can call it before adopting Phase 0 state.
pub(crate) fn validate_prepared(
    pre: &wasmtime::component::InstancePre<HostState>,
) -> Result<(), PlatformError> {
    crate::bindings::ServicePre::new(pre.clone())
        .map(|_| ())
        .map_err(|_| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                "component does not expose the typed echo world",
                false,
            )
        })
}
