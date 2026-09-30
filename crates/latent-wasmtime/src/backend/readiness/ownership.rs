use std::sync::Arc;

use latent_core::{ContractId, PlatformError, PlatformErrorCode};
use latent_executor::{
    PreparationReadWait, PreparedActivation, PreparedComponent, PreparedReadiness, PreparedUse,
};

use crate::backend::owned::WasmtimePreparedUse;
use crate::backend::{PreparedRuntime, SharedRuntime, WasmtimeBackend};
use crate::compiler::{ReadyPermit, ReadyPin};
use crate::containment::platform_error;

struct ReadyOwner {
    runtime: Arc<PreparedRuntime>,
    permit: ReadyPermit,
    shared: Arc<SharedRuntime>,
}

struct Materialization {
    descriptor: PreparedComponent,
    imports: Vec<ContractId>,
    owner: ReadyOwner,
}

impl WasmtimeBackend {
    pub(in crate::backend) fn inspect_readiness(
        &self,
        ready: PreparedReadiness,
    ) -> Result<latent_executor::PreparationInspection, PlatformError> {
        let pending = self.checked_readiness(ready)?;
        let runtime = &pending.owner.runtime;
        self.shared.preparation_context.check_runtime(runtime)?;
        let surface = &runtime.surface;
        if surface.imports.len() > 64 || surface.imports.iter().any(|contract| contract.len() > 512) {
            return Err(platform_error(PlatformErrorCode::ResourceExhausted, "preparation-inspection-import-limit", false));
        }
        let profile =
            if surface.has_web_application() && self.config.buffered_web_value_profile.is_some() {
                latent_core::diagnostic::DiagnosticProfile::WasmtimeBufferedWebValuesV1
            } else {
                latent_core::diagnostic::DiagnosticProfile::WasmtimeServiceValuesV1
            };
        Ok(latent_executor::PreparationInspection {
            key: pending.descriptor.key.clone(),
            component_digest: latent_core::ReleaseDigest(
                runtime.descriptor.metadata["component-digest"].clone(),
            ),
            profile,
            import_count: surface.imports.len() as u64,
            function_count: surface.function_count() as u64,
            hostcall_fuel: surface.hostcall_fuel as u64,
            maximum_lifted_bytes: surface.value_codec_limits.max_lifted_bytes as u64,
            maximum_type_nodes: surface.value_codec_limits.max_type_nodes as u64,
            declared_budget: runtime.declared_budget.clone(),
            sealed_metadata_fingerprint: runtime.authentication.as_ref().map(|identity| *identity.metadata().digest()),
            imports: surface.imports.iter().cloned().map(ContractId).collect(),
            exports: surface.inspection_exports()?,
        })
    }

    pub(in crate::backend) fn ready_owner(
        &self,
        pin: ReadyPin<PreparedRuntime>,
    ) -> PreparedReadiness {
        PreparedReadiness::new(
            pin.runtime.descriptor.clone(),
            pin.runtime.imports.clone(),
            ReadyOwner {
                runtime: pin.runtime,
                permit: pin.permit,
                shared: Arc::clone(&self.shared),
            },
        )
    }

    pub(in crate::backend) fn materialize_readiness(
        &self,
        ready: PreparedReadiness,
    ) -> Result<PreparedActivation, PlatformError> {
        let pending = self.checked_readiness(ready)?;
        self.shared
            .preparation_context
            .check_runtime(&pending.owner.runtime)?;
        self.finish_materialization(pending)
    }

    pub(in crate::backend) async fn materialize_readiness_with_wait(
        &self,
        ready: PreparedReadiness,
        wait: &dyn PreparationReadWait,
    ) -> Result<PreparedActivation, PlatformError> {
        let pending = self.checked_readiness(ready)?;
        let window = super::wait::Window::new(Some(wait));
        // This pure check retains the ORIGINAL affine ready pin and grant.
        // No instance slot, Store or guest is created until it succeeds. Busy
        // drops every fence before awaiting; expiry/revocation are not retried.
        window
            .check(|| {
                self.shared
                    .preparation_context
                    .check_runtime(&pending.owner.runtime)
            })
            .await?;
        self.finish_materialization(pending)
    }

    fn checked_readiness(
        &self,
        ready: PreparedReadiness,
    ) -> Result<Materialization, PlatformError> {
        let (descriptor, imports, owner) = ready
            .into_parts::<ReadyOwner>()
            .map_err(|_| invalid_owner())?;
        if !Arc::ptr_eq(&owner.shared, &self.shared)
            || descriptor != owner.runtime.descriptor
            || imports != owner.runtime.imports
        {
            return Err(invalid_owner());
        }
        self.shared
            .preparation_context
            .validate_engine_key(&descriptor.key)?;
        Ok(Materialization {
            descriptor,
            imports,
            owner,
        })
    }

    fn finish_materialization(
        &self,
        pending: Materialization,
    ) -> Result<PreparedActivation, PlatformError> {
        // Never wrap this ownership transition in a retry. Capacity errors and
        // every later activation-start check keep their original semantics.
        let Materialization {
            descriptor,
            imports,
            owner,
        } = pending;
        let active = self.shared.instances.try_acquire()?;
        let use_owner = WasmtimePreparedUse {
            runtime: owner.runtime,
            permit: active,
            shared: owner.shared,
        };
        drop(owner.permit);
        Ok(PreparedActivation {
            prepared: PreparedUse::new(descriptor, use_owner),
            imports,
        })
    }
}

fn invalid_owner() -> PlatformError {
    platform_error(
        PlatformErrorCode::InvalidArgument,
        "readiness belongs to another runtime or descriptor",
        false,
    )
}
