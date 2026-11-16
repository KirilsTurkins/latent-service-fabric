//! DTO associations only constrain the actual immutable durable abort record.
use super::{authorization, NativeTransactionAdmission, State, TransactionRetrySelection};
use latent_commit::atomic::{AdmissionInput, AtomicError, CommandRecord, Outcome};
use latent_state::embedded::ReadView;

pub(super) fn check_association(
    view: &ReadView,
    input: &AdmissionInput,
    selection: &TransactionRetrySelection,
) -> Result<(), AtomicError> {
    let command = latent_commit::atomic::command_identity(&input.key)?;
    if command != selection.command {
        return Err(AtomicError::Conflict);
    }
    let key = latent_commit::atomic::attempt_row_key(command, selection.attempt);
    let bytes = view.get(&key)?.ok_or(AtomicError::RecoveryRequired)?;
    latent_commit::atomic::validate_linked_row(view, &key, &bytes)?;
    let record = CommandRecord::decode(&bytes)?;
    let source = record.source();
    if record.id() != command
        || record.key() != &input.key
        || record.attempt() != selection.attempt
        || record.transaction_id() != selection.transaction
        || record.outcome() != Outcome::Aborted
        || record.abort_proof() != Some(selection.request.expected_abort)
        || record.fingerprint()
            != latent_commit::atomic::fingerprint(&input.fingerprint, input.inbox.as_ref())?
        || record.result_read_policy() != input.result_read_policy
        || source.publication != input.source.publication
        || source.release_digest != input.source.release_digest
        || source.component_digest != input.source.component_digest
        || source.contract_digest != input.source.contract_digest
        || source.state_schema != input.source.state_schema
        || source.input_format != input.source.input_format
        || source.result_format != input.source.result_format
    {
        return Err(AtomicError::Conflict);
    }
    // Route/revision observations may change, but guest execution remains bound
    // to the first accepted exact publication/component/schema/type identity.
    Ok(())
}

impl NativeTransactionAdmission {
    /// Attach an authenticated inbox and its exact source to an explicit retry.
    /// These descriptors grant no retry authority. Normal admission verifies
    /// the original immutable abort/transaction association and finite retry
    /// policy, and fences the existing source into the pending/final writers.
    /// Pending, uncertain and terminal business outcomes cannot justify retry.
    /// Broker redelivery alone must not select this path.
    pub fn with_trusted_inbox_retry(
        mut self,
        identity: latent_commit::atomic::InboxIdentity,
        scope: latent_state::inbox_scope::InboxScope,
    ) -> Result<Self, latent_core::PlatformError> {
        let expected_key = identity.command_key().map_err(super::atomic)?;
        let valid = match self.state.get_mut() {
            Ok(State::Fresh(Some(selection))) => {
                selection.mode == latent_manifest::TransactionOperationMode::StrictCommand
                    && selection.retry.is_some()
                    && selection.client_key.as_deref() == Some(expected_key.as_str())
                    && selection.namespace == scope.namespace
                    && selection.incarnation == scope.incarnation
            }
            _ => false,
        };
        if !valid
            || self.inbox.is_some()
            || self.inbox_scope.is_some()
            || identity.provider != scope.provider
            || scope.input_binding().map_err(|_| authorization::denied())? != identity.binding
        {
            return Err(authorization::denied());
        }
        self.inbox = Some(identity);
        self.inbox_scope = Some(scope);
        Ok(self)
    }
}
