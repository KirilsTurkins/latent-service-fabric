//! Authorized terminal reads reuse the original prepaid physical reservation.
use super::{atomic, authorization, NativeTransactionAdmission, TransactionCompletionResult};
use crate::transaction_runtime::observation::{self, Phase};
use latent_commit::atomic::{AtomicError, CommandRecord, DurableResult};
use latent_core::PlatformError;
use latent_state::store_io::StoreIoKind;
use std::sync::Arc;

impl NativeTransactionAdmission {
    pub(super) async fn replay_existing(
        &self,
        selected: &CommandRecord,
    ) -> Result<(CommandRecord, Option<Arc<DurableResult>>), PlatformError> {
        let authority = self.response_authority()?;
        authority.with_current(&mut || {})?;
        let selected = selected.clone();
        let key = selected.key().clone();
        let time = Arc::clone(&self.owners.time);
        let retained = Arc::clone(&authority);
        let keeper: Arc<dyn std::any::Any + Send + Sync> = Arc::new(Arc::clone(&authority));
        let bytes = self.retained_capacity()?.request_bytes();
        let job = self
            .owners
            .store
            .with_store_retaining(StoreIoKind::Read, bytes, keeper, move |store| {
                // This clock may consult Role; no Policy/Namespace/Native lock
                // is held while it is sampled or the snapshot is read.
                let observed = time.sample();
                retained
                    .with_current(&mut || {})
                    .map_err(|_| latent_state::embedded::StoreError::Invalid)?;
                let view = store.snapshot()?;
                let read = latent_commit::atomic::inspect(&view, &key, observed, |_, record| {
                    if record.is_some_and(|record| {
                        record.result_read_policy() != selected.result_read_policy()
                            || record.id() != selected.id()
                            || record.attempt() < selected.attempt()
                            || record.fingerprint() != selected.fingerprint()
                            || record.source() != selected.source()
                    }) {
                        return Err(AtomicError::PermissionDenied);
                    }
                    retained
                        .with_current(&mut || {})
                        .map_err(|_| AtomicError::PermissionDenied)
                });
                Ok(observation::atomic(
                    Phase::ExistingReplay,
                    read.and_then(|(command, result)| {
                        if command.attempt() == selected.attempt() {
                            return Ok((command, result.map(Arc::new)));
                        }
                        // A durable retry receipt selected this older generation.
                        // Do not replace its immutable outcome with the latest one.
                        drop(result);
                        historical_attempt(&view, &selected, observed)
                    }),
                ))
            })
            .map_err(|_| atomic(AtomicError::Unavailable))?;
        let read = job
            .await
            .map_err(|_| atomic(AtomicError::Unavailable))?
            .map_err(|_| atomic(AtomicError::Unavailable))?
            .map_err(atomic)?;
        observation::platform(
            Phase::ReplayBinding,
            authority.bind_result(
                &read.0,
                read.1
                    .as_ref()
                    .is_some_and(|result| result.value().is_some()),
                Arc::clone(&self.owners.time),
            ),
        )?;
        authority.with_current(&mut || {})?;
        Ok(read)
    }

    fn response_authority(
        &self,
    ) -> Result<Arc<super::super::TransactionResponseAuthority>, PlatformError> {
        self.response
            .lock()
            .map_err(|_| authorization::denied())?
            .as_ref()
            .cloned()
            .ok_or_else(authorization::denied)
    }

    pub(super) fn bind_completion_retention(
        &self,
        result: &TransactionCompletionResult,
    ) -> Result<(), PlatformError> {
        let (command, payload) = match result {
            TransactionCompletionResult::Command(
                super::super::CommandCompletionDisposition::Durable {
                    command, result, ..
                },
            ) => (command, result.value().is_some()),
            TransactionCompletionResult::Existing {
                command,
                result: Err(_),
                ..
            } => (command, false),
            _ => return Ok(()),
        };
        observation::platform(
            Phase::CompletionBinding,
            self.response_authority()?
                .bind_result(command, payload, Arc::clone(&self.owners.time)),
        )
    }
}

fn historical_attempt(
    view: &latent_state::embedded::ReadView,
    selected: &CommandRecord,
    observed: latent_commit::atomic::CommandTime,
) -> Result<(CommandRecord, Option<Arc<DurableResult>>), AtomicError> {
    let key = latent_commit::atomic::attempt_row_key(selected.id(), selected.attempt());
    let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
    latent_commit::atomic::validate_linked_row(view, &key, &bytes)?;
    let command = CommandRecord::decode(&bytes)?;
    if command.id() != selected.id()
        || command.key() != selected.key()
        || command.attempt() != selected.attempt()
        || command.fingerprint() != selected.fingerprint()
        || command.source() != selected.source()
        || command.result_read_policy() != selected.result_read_policy()
        || !observed.continuity_proven
        || observed.unix_millis < command.clock_floor()
    {
        return Err(AtomicError::PermissionDenied);
    }
    if observed.unix_millis >= command.result_expires() {
        return Ok((command, None));
    }
    let key = latent_commit::atomic::result_row_key(command.id(), command.attempt());
    let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
    latent_commit::atomic::validate_linked_row(view, &key, &bytes)?;
    let result = DurableResult::decode(&bytes)?;
    result.verify(&command)?;
    Ok((command, Some(Arc::new(result))))
}
