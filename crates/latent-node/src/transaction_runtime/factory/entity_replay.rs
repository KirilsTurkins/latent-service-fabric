//! Read-only duplicate detection before waiting for an entity owner.
use super::{admission, atomic, authorization, error, policy, NativeTransactionAdmission, State};
use latent_activation::ActivationEnvelope;
use latent_commit::atomic::{self as durable, AtomicError, CommandRecord};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    ActivationBudget, PlatformError, PlatformErrorCode,
};
use latent_state::{embedded::StoreError, store_io::StoreIoKind};
use std::sync::Arc;

impl NativeTransactionAdmission {
    #[expect(
        clippy::too_many_lines,
        reason = "Keep current authorization, fingerprint validation and the bounded read-only replay together"
    )]
    pub(super) async fn replay_existing_entity(
        &self,
        selection: &super::TransactionSelection,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<(), PlatformError> {
        let initial = policy::initial(
            &self.owners,
            &self.installation,
            selection,
            envelope,
            budget,
        )?;
        let namespace = self
            .read_namespace(selection, &envelope.target.tenant)
            .await?;
        admission::check_view(
            selection,
            &namespace,
            &self.installation.declaration.state_schema,
        )?;
        let before = self.seal(initial.before, namespace, envelope, budget, None)?;
        let key = CommandKey {
            tenant: envelope.target.tenant.0.clone(),
            namespace: selection.namespace.clone(),
            incarnation: selection.incarnation.to_string(),
            recovery_scope: initial.caller.scope,
            operation: selection.operation.clone(),
            entity: selection.entity.clone(),
            client_key: selection
                .client_key
                .clone()
                .ok_or_else(authorization::denied)?,
        };
        let expected = durable::fingerprint(
            &CommandFingerprint {
                input_format: selection.input_format.clone(),
                input: Value {
                    bytes: envelope.input.clone(),
                    media_type: envelope.input_media_type.clone(),
                    metadata: envelope
                        .metadata
                        .iter()
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect(),
                },
                expected_versions: selection.expected_versions.clone(),
            },
            None,
        )
        .map_err(atomic)?;
        let auth = Arc::clone(&before);
        let time = Arc::clone(&self.owners.time);
        let policy = self.installation.result_read_policy.clone();
        let retained = self.retained_capacity()?;
        let keeper: Arc<dyn std::any::Any + Send + Sync> =
            Arc::new((auth.clone(), retained.clone()));
        let job = self
            .owners
            .store
            .with_store_retaining(
                StoreIoKind::Read,
                retained.request_bytes(),
                keeper,
                move |store| {
                    let observed = time.sample();
                    let view = store.snapshot()?;
                    let read = durable::inspect(&view, &key, observed, |_, record| {
                        if record.is_some_and(|r| r.result_read_policy() != policy) {
                            return Err(AtomicError::PermissionDenied);
                        }
                        let operation = if record.is_some() {
                            "read-result"
                        } else {
                            "commit"
                        };
                        auth.authorize(operation, 0, 0, || Ok(()))
                            .map_err(|_| AtomicError::PermissionDenied)
                    });
                    match read {
                        Ok((record, _result)) if record.fingerprint() == expected => {
                            Ok(Ok(Some(record)))
                        }
                        Ok(_) => Ok(Err(AtomicError::Conflict)),
                        Err(AtomicError::NotFound) => Ok(Ok(None)),
                        Err(AtomicError::Corrupt) => Err(StoreError::Corrupt),
                        Err(reason) => Ok(Err(reason)),
                    }
                },
            )
            .map_err(|_| atomic(AtomicError::Unavailable))?;
        let existing: Option<CommandRecord> = job
            .await
            .map_err(|_| atomic(AtomicError::Unavailable))?
            .map_err(|_| atomic(AtomicError::RecoveryRequired))?
            .map_err(atomic)?;
        if let Some(command) = existing {
            self.retain_response_authority(before, false)?;
            *self.state.lock().map_err(|_| authorization::denied())? =
                State::Ready(Some(super::TransactionAdmissionResult::Existing {
                    command,
                    retained,
                }));
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "transaction-already-admitted",
            ));
        }
        Ok(())
    }
}
