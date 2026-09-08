//! Affine prepared-state ownership shared by materialization and invocation.

use std::sync::Arc;
use std::time::Instant;

use latent_artifacts::CapsuleArtifact;
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::{
    ExecutionCancellation, ExecutionReport, ExecutionRequest, PreparationKey, PreparedActivation,
    PreparedUse,
};

use super::{elapsed_micros, PreparedRuntime, SharedRuntime, WasmtimeBackend};
use crate::cache::ActiveInstancePermit;
use crate::containment::platform_error;

pub(super) struct WasmtimePreparedUse {
    // Declaration order ensures runtime state is destroyed before its capacity
    // permit when an unused owner is dropped, including during unwind.
    pub(super) runtime: Arc<PreparedRuntime>,
    pub(super) permit: ActiveInstancePermit,
    shared: Arc<SharedRuntime>,
}

impl WasmtimeBackend {
    pub(super) fn invocation_runtime(
        &self,
        prepared: Option<WasmtimePreparedUse>,
        handle: &str,
    ) -> Result<(ActiveInstancePermit, Arc<PreparedRuntime>), PlatformError> {
        if let Some(prepared) = prepared {
            Ok((prepared.permit, prepared.runtime))
        } else {
            let permit = self.shared.instances.try_acquire()?;
            let runtime = self.prepared_runtime(handle).ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::NotFound,
                    "prepared component is absent or has been evicted",
                    true,
                )
            })?;
            Ok((permit, runtime))
        }
    }

    /// Materializing prepared uses and running invocations share this bound.
    #[must_use]
    pub fn active_instance_reservations(&self) -> usize {
        self.shared.instances.active()
    }

    #[must_use]
    pub fn maximum_instance_reservations(&self) -> usize {
        self.config.active_instance_limit()
    }

    pub(super) fn key_for_release(&self, release: &ReleaseDigest) -> PreparationKey {
        PreparationKey {
            release: release.clone(),
            engine_version: self.profile.wasmtime_version.clone(),
            engine_configuration_digest: self.profile.configuration["configuration-digest"].clone(),
            target_triple: self.profile.target_triple.clone(),
            cpu_feature_set: self.profile.cpu_feature_set.clone(),
        }
    }

    pub(super) fn prepare_owned(
        &self,
        artifact: &CapsuleArtifact,
        key: &PreparationKey,
    ) -> Result<PreparedUse, PlatformError> {
        let permit = self.shared.instances.try_acquire()?;
        // The runtime is retained inside the same cache access/publication that
        // prepared it, so concurrent eviction cannot open a descriptor-only gap.
        let runtime = self.prepare_runtime(artifact, key)?;
        Ok(self.runtime_use(runtime, permit))
    }

    pub(super) fn activation_use(
        &self,
        runtime: Arc<PreparedRuntime>,
        permit: ActiveInstancePermit,
    ) -> PreparedActivation {
        let imports = runtime.imports.clone();
        PreparedActivation {
            prepared: self.runtime_use(runtime, permit),
            imports,
        }
    }

    fn runtime_use(
        &self,
        runtime: Arc<PreparedRuntime>,
        permit: ActiveInstancePermit,
    ) -> PreparedUse {
        PreparedUse::new(
            runtime.descriptor.clone(),
            WasmtimePreparedUse {
                runtime,
                permit,
                shared: Arc::clone(&self.shared),
            },
        )
    }

    pub(super) async fn invoke_owned(
        &self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &dyn ExecutionCancellation,
    ) -> ExecutionReport {
        let ownership = match self.validate_owned(&request, prepared) {
            Ok(ownership) => ownership,
            Err(error) => return ExecutionReport::reusable(Err(error)),
        };
        let activation_id = request.activation.activation_id.clone();
        let outcome = self
            .invoke_inner(request, cancellation, Some(ownership))
            .await;
        let proof_started = Instant::now();
        let report = ExecutionReport::reusable(outcome);
        self.lock_timings()
            .update_reusable_proof(&activation_id.0, elapsed_micros(proof_started));
        report
    }

    fn validate_owned(
        &self,
        request: &ExecutionRequest,
        prepared: PreparedUse,
    ) -> Result<WasmtimePreparedUse, PlatformError> {
        let (descriptor, ownership) = prepared
            .into_parts::<WasmtimePreparedUse>()
            .map_err(|_| invalid_owner())?;
        if !Arc::ptr_eq(&ownership.shared, &self.shared)
            || descriptor != ownership.runtime.descriptor
            || descriptor != request.prepared
        {
            return Err(invalid_owner());
        }
        Ok(ownership)
    }
}

fn invalid_owner() -> PlatformError {
    platform_error(
        PlatformErrorCode::InvalidArgument,
        "prepared use belongs to another runtime or descriptor",
        false,
    )
}
