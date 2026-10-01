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

    pub(in crate::backend) async fn canonicalize_readiness_input(
        &self,
        ready: PreparedReadiness,
        envelope: &latent_activation::ActivationEnvelope,
        budget: &latent_core::ActivationBudget,
        wait: &dyn PreparationReadWait,
    ) -> Result<
        (
            PreparedReadiness,
            latent_executor::CanonicalTransactionInput,
        ),
        PlatformError,
    > {
        let pending = self.checked_readiness(ready)?;
        let revision = envelope
            .resolved_revision
            .as_ref()
            .ok_or_else(invalid_owner)?;
        let imports = &pending.owner.runtime.surface.imports;
        if budget.profile() != latent_core::BudgetProfile::Phase4
            || envelope.budget != *budget.granted()
            || !self.config.transactional_state
            || envelope.input_media_type != crate::values::MEDIA_TYPE
            || pending.descriptor.key.release != revision.release
            || pending.descriptor.key.publication != revision.publication
            || (!imports.contains(crate::surface::transaction::STATE)
                && !imports.contains(crate::surface::transaction::INTENTS))
        {
            return Err(invalid_owner());
        }
        let window = super::wait::Window::new(Some(wait));
        window
            .check(|| {
                self.shared
                    .preparation_context
                    .check_runtime(&pending.owner.runtime)
            })
            .await?;
        let function = pending
            .owner
            .runtime
            .surface
            .function(&envelope.target.contract.0, &envelope.target.function.0)
            .ok_or_else(invalid_owner)?;
        let limits = self.config.value_codec_limits;
        // Cover decoded values and the legacy diagnostic JSON representation
        // concurrently, without changing either codec's existing ceilings.
        let scratch_bytes = limits
            .max_decoded_value_bytes
            .checked_mul(2)
            .and_then(|bytes| bytes.checked_add(limits.max_input_bytes))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or_else(input_memory)?;
        let scratch = budget
            .reserve_host_memory(scratch_bytes)
            .map_err(|_| input_memory())?;
        let output_memory = budget
            .reserve_host_memory(
                u64::try_from(limits.max_output_bytes).map_err(|_| input_memory())?,
            )
            .map_err(|_| input_memory())?;
        let bytes = crate::values::canonical_params(
            &function.params,
            &envelope.input,
            &envelope.input_media_type,
            limits,
        )?;
        drop(scratch);
        let Materialization {
            descriptor,
            imports,
            owner,
        } = pending;
        Ok((
            PreparedReadiness::new(descriptor, imports, owner),
            latent_executor::CanonicalTransactionInput::new(bytes, output_memory),
        ))
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

fn input_memory() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "canonical transaction input exceeds original activation memory",
        false,
    )
}
