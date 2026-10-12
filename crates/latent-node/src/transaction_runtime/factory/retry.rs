//! DTO associations only constrain the actual immutable durable abort record.
use super::TransactionRetrySelection;
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
