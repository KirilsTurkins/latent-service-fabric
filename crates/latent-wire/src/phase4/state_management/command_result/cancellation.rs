//! Request only on the original managed owner after a current protected lookup.
use super::authority::ResponseOwner;
use super::{contract, denied, unsupported, Arc, CommandRecord, Outcome, PlatformError, ReadError};
use latent_node::transaction_runtime::OriginalCommandCancelDisposition;
use latent_rpc::transaction::v1 as t;

pub(super) fn response(
    request: &t::CancelCommandRequest,
    record: &CommandRecord,
    owner: &Arc<ResponseOwner>,
    pending: &mut super::super::audit::Pending,
) -> Result<contract::Response, ReadError> {
    // Source substitution cannot select another live activation, even if its
    // descriptive command key resembles this protected original record.
    if record.source().publication != owner.read.binding.publication.id.as_str()
        || record.source().release_digest != owner.read.binding.component.0
    {
        return Err(denied().into());
    }
    let mut command = crate::phase4::local_transaction::projection::inspection(record, None, None);
    let disposition = match record.outcome() {
        Outcome::Committed => t::CommandCancelDisposition::AlreadyCommitted,
        Outcome::Aborted | Outcome::Rejected => t::CommandCancelDisposition::AlreadyTerminal,
        Outcome::Pending => {
            command.outcome = t::CommandOutcome::RecoveryRequired as i32;
            let manager = owner
                .read
                .command_manager
                .as_ref()
                .ok_or_else(unsupported)?;
            let source = owner
                .read
                .inner
                .command_source
                .as_ref()
                .ok_or_else(unsupported)?;
            let cutoff = owner.window.cutoff(
                source,
                owner.read.inner.services.clock.as_ref(),
                owner.read.deadline,
            )?;
            let authority = Arc::new(CancellationAuthority {
                policy: owner.read.inner.services.policy.clone(),
                decision: owner.read.decision.clone(),
                namespace: owner.namespace.clone(),
                namespaces: owner.read.inner.services.namespaces.clone(),
                permit: owner.read.permit.clone(),
                source: source.clone(),
                clock: owner.read.inner.services.clock.clone(),
                cutoff,
                floor: record.clock_floor(),
                expires: record.identity_expires(),
            });
            match manager.cancel_original_command_authorized(
                &latent_core::TenantId(owner.read.key.tenant.clone()),
                record,
                owner.read.inner.services.store.as_ref(),
                &request.reason,
                authority,
                || pending.started(),
            )? {
                OriginalCommandCancelDisposition::Requested => {
                    t::CommandCancelDisposition::Requested
                }
                OriginalCommandCancelDisposition::RecoveryRequired => {
                    t::CommandCancelDisposition::RecoveryRequired
                }
            }
        }
    };
    Ok(t::CancelCommandResponse {
        disposition: disposition as i32,
        command: Some(command),
    }
    .into())
}

/// The accepted request retains its real decision and prepaid capacity, with
/// no manager, guest, request payload or strong original registration.
struct CancellationAuthority {
    policy: Arc<latent_policy::capability::PolicyStore>,
    decision: Arc<latent_policy::capability::OwnedPolicyDecision>,
    namespace: Arc<latent_state::namespace::catalog::NamespaceRead>,
    namespaces: Arc<latent_state::namespace::catalog::NamespaceCatalog>,
    permit: Arc<dyn super::StateManagementReservation>,
    source: latent_effects::runtime::CommandAdmissionSource,
    clock: Arc<dyn latent_core::ActivationClock>,
    cutoff: std::time::Instant,
    floor: u64,
    expires: u64,
}

impl latent_node::transaction_runtime::CommandCancellationAuthority for CancellationAuthority {
    fn policy(&self) -> &latent_policy::capability::PolicyStore {
        &self.policy
    }
    fn decision(&self) -> &Arc<latent_policy::capability::OwnedPolicyDecision> {
        &self.decision
    }
    fn namespace(&self) -> &latent_state::namespace::catalog::NamespaceRead {
        &self.namespace
    }
    fn namespaces(&self) -> &latent_state::namespace::catalog::NamespaceCatalog {
        &self.namespaces
    }
    fn cutoff(&self) -> Result<std::time::Instant, PlatformError> {
        let observed = self.clock.monotonic_now();
        let time = self.source.command_time().map_err(|_| unsupported())?;
        if !time.continuity_proven
            || time.unix_millis < self.floor
            || time.unix_millis >= self.expires
        {
            return Err(super::expired());
        }
        observed
            .checked_add(std::time::Duration::from_millis(
                self.expires - time.unix_millis,
            ))
            .map(|cutoff| cutoff.min(self.cutoff))
            .ok_or_else(super::expired)
    }
    fn uses_native_capacity(
        &self,
        owner: &latent_core::native_capacity::NativeCapacityOwner,
    ) -> bool {
        self.permit.uses_native_capacity(owner)
    }
    fn with_native_until(
        &self,
        cutoff: std::time::Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.permit.with_live_until(cutoff.min(self.cutoff), action)
    }
    fn with_native_pair_until(
        &self,
        other: &latent_core::native_capacity::NativeReservation,
        cutoff: std::time::Instant,
        action: &mut dyn FnMut(),
    ) -> Result<(), PlatformError> {
        self.permit
            .with_live_pair_until(other, cutoff.min(self.cutoff), action)
    }
}
