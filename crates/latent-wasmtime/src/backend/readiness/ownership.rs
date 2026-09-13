use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::{PreparedActivation, PreparedReadiness, PreparedUse};

use crate::backend::owned::WasmtimePreparedUse;
use crate::backend::{PreparedRuntime, SharedRuntime, WasmtimeBackend};
use crate::compiler::{ReadyPermit, ReadyPin};
use crate::containment::platform_error;

struct ReadyOwner {
    runtime: Arc<PreparedRuntime>,
    permit: ReadyPermit,
    shared: Arc<SharedRuntime>,
}

impl WasmtimeBackend {
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
        self.shared
            .preparation_context
            .check_runtime(&owner.runtime)?;
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
