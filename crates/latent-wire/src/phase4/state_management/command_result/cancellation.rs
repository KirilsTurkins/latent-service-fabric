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
            let mut requested: Option<Result<OriginalCommandCancelDisposition, PlatformError>> =
                None;
            owner
                .read
                .with_namespace(&owner.namespace, &owner.lifecycle, cutoff, &mut || {
                    requested = Some(pending.started().and_then(|()| {
                        manager.cancel_original_command(
                            &latent_core::TenantId(owner.read.key.tenant.clone()),
                            record,
                            owner.read.inner.services.store.as_ref(),
                            &request.reason,
                        )
                    }));
                })?;
            match requested.ok_or_else(unsupported)?? {
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
