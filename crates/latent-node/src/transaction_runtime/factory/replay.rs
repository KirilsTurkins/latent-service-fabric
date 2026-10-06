//! Authorized terminal reads reuse the original prepaid physical reservation.
use super::{atomic, authorization, NativeTransactionAdmission, TransactionCompletionResult};
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
                let read = latent_commit::atomic::inspect(
                    &store.snapshot()?,
                    &key,
                    observed,
                    |_, record| {
                        if record.is_some_and(|record| {
                            record.result_read_policy() != selected.result_read_policy()
                                || record.id() != selected.id()
                                || record.attempt() != selected.attempt()
                                || record.fingerprint() != selected.fingerprint()
                                || record.source() != selected.source()
                        }) {
                            return Err(AtomicError::PermissionDenied);
                        }
                        retained
                            .with_current(&mut || {})
                            .map_err(|_| AtomicError::PermissionDenied)
                    },
                );
                Ok(read.map(|(command, result)| (command, result.map(Arc::new))))
            })
            .map_err(|_| atomic(AtomicError::Unavailable))?;
        let read = job
            .await
            .map_err(|_| atomic(AtomicError::Unavailable))?
            .map_err(|_| atomic(AtomicError::Unavailable))?
            .map_err(atomic)?;
        authority.bind_result(
            &read.0,
            read.1
                .as_ref()
                .is_some_and(|result| result.value().is_some()),
            Arc::clone(&self.owners.time),
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
        self.response_authority()?
            .bind_result(command, payload, Arc::clone(&self.owners.time))
    }
}
