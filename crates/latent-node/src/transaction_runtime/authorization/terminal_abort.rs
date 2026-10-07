//! One actual noncommit proof permits bounded terminal metadata only.
use super::{denied, DecisionPurpose, StateAuthorization};
use latent_capabilities::namespace::Mode;
use latent_commit::atomic::{
    AtomicError, CommandRecord, CommandTime, CompleteEnvelope, EnvelopeNamespaceExpectation,
    RetiredAttempt,
};
use latent_core::PlatformError;
use latent_state::{embedded::ReadView, namespace::catalog::NamespaceRead};
use std::sync::{Arc, Mutex};

/// Never constructed from an observation, caller receipt or elapsed deadline.
/// The original inspection grant, caller and budget remain fixed. Stopping the
/// guest permits only this already-proven attempt's technical abort metadata;
/// no method grants application work, effects or result-body delivery.
pub(in crate::transaction_runtime) struct TerminalAbortPurpose {
    authorization: Arc<StateAuthorization>,
    original: CommandRecord,
    attempt: Mutex<Option<RetiredAttempt>>,
}

impl TerminalAbortPurpose {
    pub(in crate::transaction_runtime) fn authorization(&self) -> &Arc<StateAuthorization> {
        &self.authorization
    }

    pub(in crate::transaction_runtime) fn new(
        authorization: Arc<StateAuthorization>,
        original: CommandRecord,
        attempt: RetiredAttempt,
    ) -> Result<Self, PlatformError> {
        if authorization.authority_mode() != Mode::Inspection
            || !attempt.matches_original(&original)
            || authorization.budget.descendant_snapshot().is_err()
        {
            return Err(denied());
        }
        authorization.accepts_record(&original)?;
        Ok(Self {
            authorization,
            original,
            attempt: Mutex::new(Some(attempt)),
        })
    }

    pub(in crate::transaction_runtime) fn authorize_metadata(&self) -> Result<(), PlatformError> {
        self.authorization.with_decision(
            "cancel-command",
            0,
            0,
            DecisionPurpose::RetiredAbort,
            |decision| {
                self.authorization.authority.with_operation(
                    &self.authorization.policy,
                    decision,
                    &self.authorization.namespace,
                    "cancel-command",
                    || Ok(()),
                )
            },
        )
    }

    pub(in crate::transaction_runtime) fn rebind(
        &self,
        namespace: NamespaceRead,
    ) -> Result<Self, PlatformError> {
        let authorization = Arc::new(self.authorization.rebind_result_read(namespace)?);
        let attempt = self
            .attempt
            .lock()
            .map_err(|_| denied())?
            .take()
            .ok_or_else(denied)?;
        Self::new(authorization, self.original.clone(), attempt)
    }

    pub(in crate::transaction_runtime) fn prepare(
        &self,
        view: &ReadView,
        code: String,
        time: CommandTime,
    ) -> Result<CompleteEnvelope, AtomicError> {
        let attempt = self
            .attempt
            .lock()
            .map_err(|_| AtomicError::RecoveryRequired)?
            .take()
            .ok_or(AtomicError::RecoveryRequired)?;
        if !attempt.matches_original(&self.original) {
            return Err(AtomicError::PermissionDenied);
        }
        let prepared = CompleteEnvelope::technical_abort(view, attempt, code, time)?;
        let actual = prepared.command();
        if actual.id() != self.original.id()
            || actual.attempt() != self.original.attempt()
            || actual.owner_epoch() != self.original.owner_epoch()
            || actual.key() != self.original.key()
            || actual.source() != self.original.source()
            || actual.result_read_policy() != self.original.result_read_policy()
        {
            return Err(AtomicError::PermissionDenied);
        }
        Ok(prepared)
    }

    pub(in crate::transaction_runtime) fn accept(
        &self,
        envelope: &EnvelopeNamespaceExpectation,
    ) -> Result<(), PlatformError> {
        self.authorization.with_decision(
            "cancel-command",
            0,
            0,
            DecisionPurpose::RetiredAbort,
            |decision| {
                self.authorization.authority.accept_terminal_abort(
                    &self.authorization.policy,
                    decision,
                    &self.authorization.namespace,
                    envelope,
                )
            },
        )
    }
}
