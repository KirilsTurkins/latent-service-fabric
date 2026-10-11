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
}

impl NativeTransactionAdmission {
    pub(super) async fn persist_conflict_abort(
        &self,
        disposition: CommandCompletionDisposition,
        host: &Arc<StateTransactionHost>,
    ) -> CommandCompletionDisposition {
        let CommandCompletionDisposition::Retired {
            command,
            proof,
            reason: AtomicError::Conflict,
            retained,
            retained_native,
        } = disposition
        else {
            return disposition;
        };
        let Ok(writer) = AbortWriter::new(self, host, &command) else {
            return CommandCompletionDisposition::Retired {
                command,
                proof,
                reason: AtomicError::Conflict,
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
            move |store| active.publish(store, *proof, &identity),
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
    fn new(
        admission: &NativeTransactionAdmission,
        host: &Arc<StateTransactionHost>,
        command: &CommandRecord,
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
        }))
    }

    fn publish(
        &self,
        store: &EmbeddedStore,
        proof: RetiredAttempt,
        identity: &CommandRecord,
    ) -> Result<Publication, StoreError> {
        let view = store.snapshot()?;
        let namespace = NamespaceCatalog::read_in(
            &view,
            &latent_core::TenantId(identity.key().tenant.clone()),
            &latent_core::StateNamespaceId(identity.key().namespace.clone()),
        )
        .map_err(|_| StoreError::Corrupt)?
        .ok_or(StoreError::Corrupt)?;
        let Ok(authorization) =
            self.original
                .fresh_abort_authority(namespace, &self.namespaces, &self.selection)
        else {
            return Ok(None);
        };
        let Ok(envelope) = CompleteEnvelope::technical_abort(
            &view,
            proof,
            "state-conflict".into(),
            self.time.sample(),
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
            self.role.with_current(|_| {
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
                                    self.reservation
                                        .with_live(|| ())
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
