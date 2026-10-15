//! A physical retirement proof permits one bounded metadata-only OCC abort.
use super::*;
use crate::transaction_runtime::{
    command_role::CommandRole, CommandCompletionDisposition, StateAuthorization,
};
use latent_commit::atomic::{CompleteEnvelope, PreparedDisposition, RetiredAttempt};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservationRequest,
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    store_io::StoreIoKind,
};

const REQUEST_BYTES: u64 = 32 * 1024;
const WORK_BYTES: u64 = 256 * 1024;
const RESPONSE_BYTES: u64 = 16 * 1024;
type Publication = Option<(PreparedDisposition, Arc<StateAuthorization>)>;

#[cfg(test)]
mod tests;

struct AbortWriter {
    original: Arc<StateAuthorization>,
    namespaces: Arc<NamespaceCatalog>,
    selection: RecoverySelection,
    time: Arc<dyn CommandTimeSource>,
    role: Arc<CommandRole>,
    reservation: Arc<NativeReservation>,
    _buffers: [NativeBufferPermit; 3],
    // The frozen original host-memory envelope covers metadata work. Its
    // physically retired guest/session can never be reopened by this owner.
    _host: Arc<StateTransactionHost>,
    cancellation: Mutex<Option<super::super::cancellation::PendingCancellationAbort>>,
}

impl NativeTransactionAdmission {
    pub(super) async fn persist_terminal_abort(
        &self,
        disposition: CommandCompletionDisposition,
        host: &Arc<StateTransactionHost>,
        failure_code: Option<latent_core::PlatformErrorCode>,
        control: &crate::TransactionCommitControl,
        original_failure: Option<&latent_activation::ActivationOutcome>,
    ) -> CommandCompletionDisposition {
        let CommandCompletionDisposition::Retired {
            command,
            proof,
            reason,
            retained,
            retained_native,
        } = disposition
        else {
            return disposition;
        };
        let code = match (reason, failure_code) {
            (AtomicError::Conflict, _) => latent_core::PlatformErrorCode::StateConflict,
            (AtomicError::Unavailable, Some(code)) => code,
            _ => {
                return CommandCompletionDisposition::Retired {
                    command,
                    proof,
                    reason,
                    retained,
                    retained_native,
                };
            }
        };
        let cancelled_failure = original_failure.is_some_and(|outcome| {
            matches!(outcome,
            latent_activation::ActivationOutcome::Failed {
                terminal_state: latent_core::ActivationTerminalState::Cancelled, error, ..
            } if error.code == latent_core::PlatformErrorCode::Cancelled)
        });
        let cancellation = (code == latent_core::PlatformErrorCode::Cancelled && cancelled_failure)
            .then(|| {
                let slot = self.cancellation_abort.lock().ok()?.as_ref()?.clone();
                slot.take_original(&command, host, control)
            })
            .flatten();
        let Ok(writer) = AbortWriter::new_with_cancellation(self, host, &command, cancellation)
        else {
            return CommandCompletionDisposition::Retired {
                command,
                proof,
                reason,
                retained,
                retained_native,
            };
        };
        let active = Arc::clone(&writer);
        let identity = command.clone();
        let keeper: Arc<dyn std::any::Any + Send + Sync> = writer.clone();
        let job = self.owners.store.with_store_retaining(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES,
            keeper,
            move |store| active.publish(store, *proof, &identity, code),
        );
        let observed = match job {
            Ok(job) => job.await.ok().and_then(Result::ok),
            Err(_) => {
                // A rejected queue admission never owned a physical writer.
                let _ = writer.role.retire();
                return CommandCompletionDisposition::RecoveryRequired {
                    command,
                    retained_native,
                    cleanup_failure: None,
                };
            }
        };
        AbortCompletion {
            command,
            retained,
            retained_native,
            writer,
        }
        .finish(self, observed)
    }
}

impl AbortWriter {
    #[cfg(test)]
    fn new(
        admission: &NativeTransactionAdmission,
        host: &Arc<StateTransactionHost>,
        command: &CommandRecord,
    ) -> Result<Arc<Self>, AtomicError> {
        Self::new_with_cancellation(admission, host, command, None)
    }

    fn new_with_cancellation(
        admission: &NativeTransactionAdmission,
        host: &Arc<StateTransactionHost>,
        command: &CommandRecord,
        cancellation: Option<super::super::cancellation::PendingCancellationAbort>,
    ) -> Result<Arc<Self>, AtomicError> {
        let deadline = host.authorization.authority.deadline();
        let reservation = Arc::new(
            admission
                .owners
                .native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        request_bytes: REQUEST_BYTES,
                        work_bytes: WORK_BYTES,
                        response_bytes: RESPONSE_BYTES,
                    },
                    deadline,
                )
                .map_err(|_| AtomicError::Unavailable)?,
        );
        let buffers = [
            reservation.reserve_buffer(NativeBufferClass::Request, REQUEST_BYTES),
            reservation.reserve_buffer(NativeBufferClass::Work, WORK_BYTES),
            reservation.reserve_buffer(NativeBufferClass::Response, RESPONSE_BYTES),
        ];
        let [request, work, response] = buffers;
        let buffers = [
            request.map_err(|_| AtomicError::Unavailable)?,
            work.map_err(|_| AtomicError::Unavailable)?,
            response.map_err(|_| AtomicError::Unavailable)?,
        ];
        let role = CommandRole::capture(&admission.owners.command)?;
        if role.epoch() != command.owner_epoch() {
            role.retire()?;
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(Arc::new(Self {
            original: Arc::clone(&host.authorization),
            namespaces: Arc::clone(&admission.owners.namespaces),
            selection: admission.installation.recovery.clone(),
            time: Arc::clone(&admission.owners.time),
            role,
            reservation,
            _buffers: buffers,
            _host: Arc::clone(host),
            cancellation: Mutex::new(cancellation),
        }))
    }

    fn publish(
        &self,
        store: &EmbeddedStore,
        proof: RetiredAttempt,
        identity: &CommandRecord,
        code: latent_core::PlatformErrorCode,
    ) -> Result<Publication, StoreError> {
        let view = store.snapshot()?;
        let namespace = NamespaceCatalog::read_in(
            &view,
            &latent_core::TenantId(identity.key().tenant.clone()),
            &latent_core::StateNamespaceId(identity.key().namespace.clone()),
        )
        .map_err(|_| StoreError::Corrupt)?
        .ok_or(StoreError::Corrupt)?;
        let Ok(envelope) = CompleteEnvelope::technical_abort(
            &view,
            proof,
            code.wire_code().into(),
            self.time.sample(),
        ) else {
            return Ok(None);
        };
        if envelope.command().id() != identity.id()
            || envelope.command().attempt() != identity.attempt()
            || envelope.command().transaction_id() != identity.transaction_id()
            || envelope.command().key() != identity.key()
            || envelope.command().source() != identity.source()
            || envelope.command().fingerprint() != identity.fingerprint()
        {
            return Ok(None);
        }
        let cancellation = self
            .cancellation
            .lock()
            .map_err(|_| StoreError::Unavailable)?
            .take();
        let cancellation = match cancellation {
            Some(candidate) => match candidate.promote(identity, envelope.command()) {
                Ok(permit) => Some(permit),
                Err(_) => return Ok(None),
            },
            None => None,
        };
        let Ok(authorization) = self.original.fresh_abort_authority(
            namespace,
            &self.namespaces,
            &self.selection,
            cancellation,
        ) else {
            return Ok(None);
        };
        drop(view);
        let expected = authorization.namespace.expectation();
        let namespace_batch = AtomicBatch {
            expectations: envelope
                .batch()
                .expectations
                .iter()
                .filter(|row| row.key == expected.key && row.value == expected.value)
                .cloned()
                .collect(),
            mutations: Vec::new(),
        };
        let disposition = envelope.publish(store, |_| {
            self.role.with_current(|time| {
                if authorization.cancelled_metadata.is_some()
                    && (!time.continuity_proven
                        || time.unix_millis < identity.clock_floor()
                        || time.unix_millis >= identity.identity_expires())
                {
                    return Err(AtomicError::PermissionDenied);
                }
                authorization
                    .with_completion_decision(|decision| {
                        let acceptance = authorization.authority.prepare_commit_io(
                            authorization.policy(),
                            decision,
                            &authorization.namespace,
                            &namespace_batch,
                        )?;
                        // Only this new metadata role and its original finite recovery
                        // reservation can accept. No previous guest commit gate renews.
                        acceptance
                            .accept_with_final(
                                || Ok(()),
                                || {
                                    authorization
                                        .with_metadata_native_acceptance(&self.reservation)
                                        .map_err(|_| NamespaceError::PermissionDenied)
                                },
                            )
                            .map_err(|_| super::super::authorization::denied())
                    })
                    .map_err(|_| AtomicError::PermissionDenied)
            })
        });
        Ok(Some((disposition, authorization)))
    }
}

struct AbortCompletion {
    command: CommandRecord,
    retained: Arc<latent_core::HostMemoryReservation>,
    retained_native: Option<Arc<TransactionRetention>>,
    writer: Arc<AbortWriter>,
}
impl AbortCompletion {
    fn finish(
        self,
        admission: &NativeTransactionAdmission,
        observed: Option<Publication>,
    ) -> CommandCompletionDisposition {
        match observed {
            Some(Some((PreparedDisposition::Confirmed { command, result }, authorization))) => {
                // Actual worker completion precedes retirement of this new role.
                let mut cleanup_failure = self
                    .writer
                    .role
                    .retire()
                    .err()
                    .map(|_| latent_executor::transaction::StateFailure::Unavailable);
                if admission
                    .retain_response_authority(authorization, false)
                    .is_err()
                {
                    cleanup_failure = Some(latent_executor::transaction::StateFailure::Unavailable);
                }
                // Accepted durable metadata is preserved even when response
                // currentness/cleanup fails. Failure cannot turn it into an abort.
                CommandCompletionDisposition::Durable {
                    command: *command,
                    result,
                    retained: self.retained,
                    retained_native: self.retained_native,
                    cleanup_failure,
                }
            }
            Some(Some((PreparedDisposition::KnownNotCommitted { command, .. }, _))) => {
                drop(command);
                self.no_publication()
            }
            Some(None) => self.no_publication(),
            Some(Some((PreparedDisposition::RecoveryRequired { .. }, _))) | None => {
                // Affine role drop quarantines unresolved native acceptance.
                // No elapsed-time refund or durable-abort DTO can be inferred.
                CommandCompletionDisposition::RecoveryRequired {
                    command: self.command,
                    retained_native: self.retained_native,
                    cleanup_failure: None,
                }
            }
        }
    }

    fn no_publication(self) -> CommandCompletionDisposition {
        let _ = self.writer.role.retire();
        CommandCompletionDisposition::RecoveryRequired {
            command: self.command,
            retained_native: self.retained_native,
            cleanup_failure: None,
        }
    }
}
