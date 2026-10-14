//! A separate opaque native association routes to the original cancellation owner.
use super::{capacity, error, LocalActivationJournal, TERMINAL_RESERVE_BYTES};
use crate::{
    cancellation::WeakCancellationOwner,
    transaction_runtime::{
        CommandCancellationIdentity, OriginalCommandCancelDisposition, OriginalCommandCancellation,
    },
};
use latent_commit::atomic::CommandRecord;
use latent_core::{ActivationId, ActivationPhase, PlatformError, PlatformErrorCode, TenantId};
use latent_state::protected_store::ProtectedStoreOwner;

pub(super) const RECORD_BYTES: usize = 2048;

#[cfg_attr(test, derive(Clone))]
pub(super) struct BoundOriginalCommand {
    identity: CommandCancellationIdentity,
    serial: u64,
    owner: WeakCancellationOwner,
}

pub(super) fn bind(
    journal: &LocalActivationJournal,
    id: &ActivationId,
    serial: u64,
    original: OriginalCommandCancellation,
    owner: WeakCancellationOwner,
) -> Result<(), PlatformError> {
    let mut state = journal.inner.lock();
    let record = state.records.get_mut(id).ok_or_else(denied)?;
    if record.serial != serial
        || record.command_cancellation.is_some()
        || record.status.terminal_state.is_some()
        || !matches!(
            record.status.phase,
            ActivationPhase::Admitted | ActivationPhase::Queued
        )
        || !record
            .active_budget
            .as_ref()
            .is_some_and(|budget| original.matches_activation(id, budget))
        || !owner.matches_activation(id)
    {
        return Err(denied());
    }
    let identity = original.into_identity();
    if identity.tenant != record.tenant {
        return Err(denied());
    }
    if identity
        .retained_bytes()
        .and_then(|bytes| bytes.checked_add(std::mem::size_of::<BoundOriginalCommand>()))
        .is_none_or(|bytes| bytes > RECORD_BYTES)
    {
        return Err(capacity());
    }
    let bytes = record
        .bytes
        .checked_add(RECORD_BYTES)
        .ok_or_else(capacity)?;
    if bytes > journal.inner.config.maximum_record_bytes - TERMINAL_RESERVE_BYTES {
        return Err(capacity());
    }
    record.command_cancellation = Some(Box::new(BoundOriginalCommand {
        identity,
        serial,
        owner,
    }));
    record.bytes = bytes;
    Ok(())
}

impl LocalActivationJournal {
    #[cfg(test)]
    pub(crate) fn command_association_boundary_for_test(&self, original: &ActivationId) -> usize {
        self.inner.lock().records.get(original).unwrap().bytes
            + TERMINAL_RESERVE_BYTES
            + RECORD_BYTES
    }

    #[cfg(test)]
    pub(crate) fn duplicate_command_association_for_test(
        &self,
        original: &ActivationId,
        duplicate: &ActivationId,
    ) {
        let mut state = self.inner.lock();
        let mut association = state
            .records
            .get(original)
            .unwrap()
            .command_cancellation
            .as_ref()
            .unwrap()
            .clone();
        let record = state.records.get_mut(duplicate).unwrap();
        assert!(record.command_cancellation.is_none() && record.status.terminal_state.is_none());
        assert!(
            record.bytes + RECORD_BYTES
                <= self.inner.config.maximum_record_bytes - TERMINAL_RESERVE_BYTES
        );
        association.serial = record.serial;
        record.bytes += RECORD_BYTES;
        record.command_cancellation = Some(association);
    }

    pub(crate) fn cancel_original_command(
        &self,
        tenant: &TenantId,
        command: &CommandRecord,
        store: &ProtectedStoreOwner,
        reason: &str,
    ) -> Result<OriginalCommandCancelDisposition, PlatformError> {
        if tenant.0 != command.key().tenant {
            return Err(denied());
        }
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        let mut matched = None;
        for record in state.records.values() {
            let Some(bound) = &record.command_cancellation else {
                continue;
            };
            if &record.tenant == tenant && bound.identity.matches_record(command, store) {
                if matched.is_some() {
                    return Err(error(
                        PlatformErrorCode::Unavailable,
                        "ambiguous-original-command-cancellation",
                    ));
                }
                if bound.serial != record.serial || record.status.terminal_state.is_some() {
                    return Err(denied());
                }
                matched = Some(bound);
            }
        }
        match matched {
            Some(original) => Ok(original.owner.cancel(reason)),
            None => Ok(OriginalCommandCancelDisposition::RecoveryRequired),
        }
    }
}

fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "original-command-cancellation-owner-mismatch",
    )
}
