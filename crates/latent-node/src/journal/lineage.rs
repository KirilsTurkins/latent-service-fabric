//! Registration authority is separate from tenant-scoped query membership.

use super::{error, state::Record, state::State};
use latent_activation::ActivationEnvelope;
use latent_capabilities::broker::ProviderCall;
use latent_core::{ActivationBudget, PlatformError, PlatformErrorCode, TenantId};

pub(super) enum RegistrationScope<'a> {
    SameTenant,
    Broker(&'a ProviderCall),
}

impl RegistrationScope<'_> {
    pub(super) fn root_serial(
        &self,
        state: &State,
        envelope: &ActivationEnvelope,
        tenant: &TenantId,
        serial: u64,
    ) -> Result<u64, PlatformError> {
        let Some(parent_id) = &envelope.parent_activation_id else {
            return if matches!(self, Self::SameTenant)
                && envelope.root_activation_id == envelope.activation_id
            {
                Ok(serial)
            } else {
                Err(denied())
            };
        };
        let parent = state.records.get(parent_id).ok_or_else(denied)?;
        if parent.root != envelope.root_activation_id
            || parent.terminal_at.is_some()
            || envelope.activation_id == envelope.root_activation_id
        {
            return Err(denied());
        }
        match self {
            Self::SameTenant if &parent.tenant == tenant => (),
            Self::Broker(call) => {
                // This checks the original live session, cancellation, ledger,
                // deadline and exact broker-selected Service publication.
                let selected = call.local_invocation_target(&envelope.target)?;
                if selected.target != envelope.target
                    || parent_id != call.activation_id()
                    || envelope.root_activation_id != *call.root_activation_id()
                    || envelope.principal != call.local_invocation_principal(tenant.clone())
                    || !owns_broker_parent(
                        parent,
                        call.local_invocation_source(),
                        call.budget_accounting(),
                    )
                {
                    return Err(denied());
                }
            }
            Self::SameTenant => return Err(denied()),
        }
        Ok(parent.root_serial)
    }
}

pub(super) fn owns_broker_parent(
    parent: &Record,
    source: (&TenantId, &latent_core::ServiceId),
    budget: &ActivationBudget,
) -> bool {
    &parent.tenant == source.0
        && &parent.target_service == source.1
        && parent.terminal_at.is_none()
        && parent
            .active_budget
            .as_ref()
            .is_some_and(|original| original.is_same_instance(budget))
}

fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "activation-lineage-not-authorized",
    )
}
