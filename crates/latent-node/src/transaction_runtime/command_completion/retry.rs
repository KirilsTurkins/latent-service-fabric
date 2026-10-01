//! Explicit retry preserves the original stored source and server-issued fence.
use latent_commit::atomic::{
    attempt_row_key, command_identity, command_row_key, AdmissionDecision, AdmissionInput,
    AtomicError, CommandAccess, CommandRecord, CommandTime, PreparedAdmission, RetryRequest,
};
use latent_core::{transaction_contract::AbortFence, PlatformError};
use latent_state::embedded::ReadView;

#[derive(Clone)]
pub struct CommandRetry {
    request_id: String,
    fence: AbortFence,
}
impl CommandRetry {
    pub fn new(request_id: String, fence: AbortFence) -> Result<Self, PlatformError> {
        if request_id.is_empty()
            || request_id.len() > 128
            || !request_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
            || fence.owner_fence.len() != 32
            || [&fence.command_id, &fence.attempt_id, &fence.transaction_id]
                .into_iter()
                .any(|id| {
                    id.len() != 64 || !id.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
                })
        {
            return Err(super::errors::atomic(AtomicError::Invalid));
        }
        Ok(Self { request_id, fence })
    }

    pub(crate) fn prepare(
        &self,
        view: &ReadView,
        input: &AdmissionInput,
        time: CommandTime,
        mut authorize: impl FnMut(CommandAccess, Option<&CommandRecord>) -> Result<(), AtomicError>,
    ) -> Result<AdmissionDecision, AtomicError> {
        authorize(CommandAccess::Admit, None)?;
        let identity = command_identity(&input.key)?;
        if identity.hex() != self.fence.command_id {
            return Err(AtomicError::PermissionDenied);
        }
        let bytes = view
            .get(&command_row_key(identity))?
            .ok_or(AtomicError::RecoveryRequired)?;
        let current = CommandRecord::decode(&bytes)?;
        authorize(CommandAccess::Admit, Some(&current))?;
        if current.key() != &input.key || current.source() != &input.source {
            return Err(AtomicError::Conflict);
        }
        // At most sixteen immutable attempt records exist. A repeated retry
        // request may observe a later attempt, so validate the actual historical
        // aborted attempt instead of treating the newest row as its issuer.
        let mut issued = None;
        if !(1..=16).contains(&current.attempt()) {
            return Err(AtomicError::Corrupt);
        }
        for attempt in 1..=current.attempt() {
            let bytes = view
                .get(&attempt_row_key(identity, attempt))?
                .ok_or(AtomicError::Corrupt)?;
            let original = CommandRecord::decode(&bytes)?;
            if original.attempt_id().hex() == self.fence.attempt_id {
                if original.transaction_id().hex() == self.fence.transaction_id
                    && original.source() == current.source()
                    && original.key() == current.key()
                {
                    issued = original
                        .abort_proof()
                        .filter(|proof| proof.bytes().as_slice() == self.fence.owner_fence);
                }
                break;
            }
        }
        let proof = issued.ok_or(AtomicError::RecoveryRequired)?;
        PreparedAdmission::retry(
            view,
            input,
            &RetryRequest {
                request_id: self.request_id.clone(),
                expected_abort: proof,
            },
            time,
            authorize,
        )
    }
}
