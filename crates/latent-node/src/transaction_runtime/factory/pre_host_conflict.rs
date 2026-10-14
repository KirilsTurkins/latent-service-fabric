//! A failed original opening can retire Pending without ever publishing a host.
#[cfg(all(test, unix))]
mod tests;

use super::{NativeTransactionAdmission, State};
use crate::transaction_runtime::{
    command_role::CommandRole, CommandCompletionDisposition, CommandTimeSource,
    PendingCommandAdmission, StateAuthorization, TransactionCompletionResult,
    TransactionResponseAuthority, TransactionRetention,
};
use crate::TransactionCommitControl;
use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_capabilities::namespace::RecoverySelection;
use latent_commit::atomic::{
    AtomicError, CommandRecord, CompleteEnvelope, PreparedDisposition, RetiredAttempt,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
        NativeReservationRequest,
    },
    PlatformErrorCode,
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    protected_store::ProtectedStoreOwner,
    store_io::StoreIoKind,
};
use std::sync::{Arc, Weak};

const REQUEST_BYTES: u64 = 32 * 1024;
const WORK_BYTES: u64 = 256 * 1024;
const RESPONSE_BYTES: u64 = 16 * 1024;
type Publication = Option<(PreparedDisposition, Arc<StateAuthorization>)>;

/// Constructor is confined to the positively completed original `HostOpen` fault.
/// Fixed identity digests retain no guest input, host, view or staging witness.
pub(in crate::transaction_runtime) struct OriginalConflict {
    original: Arc<StateAuthorization>,
    retained: Arc<TransactionRetention>,
    store: Weak<ProtectedStoreOwner>,
    command: String,
    transaction: String,
    fingerprint: [u8; 32],
    attempt: u64,
    epoch: u64,
}

impl NativeTransactionAdmission {
    pub(super) fn record_pre_host_conflict(
        &self,
        original: &Arc<StateAuthorization>,
        envelope: &ActivationEnvelope,
    ) {
        let Ok(retained) = self.retained_capacity() else {
            return;
        };
        let response = self
            .response
            .lock()
            .ok()
            .and_then(|slot| slot.as_ref().cloned());
        let Some(response) = response else { return };
        if !Arc::ptr_eq(original, &response.original_authorization()) {
            return;
        }
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        let State::Pending {
            claim: Some(claim),
            role,
            conflict,
        } = &mut *state
        else {
            return;
        };
        let record = claim.record();
        let ownership = original.authority.ownership();
        if conflict.is_some()
            || original.authority.activation_id() != &envelope.activation_id
            || original.publication() != record.source().publication
            || ownership.tenant.0 != record.key().tenant
            || ownership.namespace != record.key().namespace
            || ownership.incarnation.to_string() != record.key().incarnation
            || ownership.entity != record.key().entity
            || ownership.caller.scope != record.key().recovery_scope
            || original.namespace.record().state_schema != record.source().state_schema
            || role.epoch() != record.owner_epoch()
            || !original
                .role
                .as_ref()
                .is_some_and(|owner| Arc::ptr_eq(owner, role))
            || !original
                .retention
                .as_ref()
                .is_some_and(|owner| Arc::ptr_eq(owner, &retained))
            || retained.check_current().is_err()
            || original
                .budget
                .retained_authority_is_cancelled_at(std::time::Instant::now())
        {
            return;
        }
        *conflict = Some(OriginalConflict {
            original: Arc::clone(original),
            retained,
            store: Arc::downgrade(&self.owners.store),
            command: record.id().hex(),
            transaction: record.transaction_id().hex(),
            fingerprint: record.fingerprint().bytes(),
            attempt: record.attempt(),
            epoch: record.owner_epoch(),
        });
    }

    pub(super) async fn complete_pre_host(
        &self,
        mut pending: PendingCommandAdmission,
        outcome: &ActivationOutcome,
        control: &TransactionCommitControl,
        original_retention: Arc<TransactionRetention>,
    ) -> TransactionCompletionResult {
        let command = pending.record().clone();
        let marker = pending.conflict.take().filter(|marker| {
            matches!(outcome, ActivationOutcome::Failed { error, .. }
                if error.code == PlatformErrorCode::StateConflict)
                && marker.matches(self, &command, control)
        });
        let proof = pending.retire_without_guest().map(Box::new);
        let (marker, proof) = match (marker, proof) {
            (Some(marker), Ok(proof)) => (marker, *proof),
            (_, proof) => {
                return TransactionCompletionResult::PendingRetired {
                    command,
                    proof,
                    retained: original_retention,
                };
            }
        };
        let retained = Arc::clone(&marker.retained);
        let Ok(writer) = Writer::new(self, marker, &command, control.clone()) else {
            return recovery(command, retained);
        };
        let active = Arc::clone(&writer);
        let identity = command.clone();
        let keeper: Arc<dyn std::any::Any + Send + Sync> = writer.clone();
        let job = self.owners.store.with_store_retaining(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES,
            keeper,
            move |store| active.publish(store, proof, &identity),
        );
        let observed = if let Ok(job) = job {
            job.await.ok().and_then(Result::ok)
        } else {
            let _ = writer.role.retire();
            return recovery(command, retained);
        };
        match observed {
            Some(Some((PreparedDisposition::Confirmed { command, result }, authorization))) => {
                let cleanup_failure = writer
                    .role
                    .retire()
                    .err()
                    .map(|_| latent_executor::transaction::StateFailure::Unavailable);
                let response =
                    TransactionResponseAuthority::new(authorization, Arc::clone(&retained), false)
                        .with_pre_host_control(writer.control.clone());
                if let Ok(mut slot) = self.response.lock() {
                    *slot = Some(Arc::new(response));
                } else {
                    return recovery(*command, retained);
                }
                TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
                    command: *command,
                    result,
                    retained: retained.memory(),
                    retained_native: Some(retained),
                    cleanup_failure,
                })
            }
            Some(None | Some((PreparedDisposition::KnownNotCommitted { .. }, _))) => {
                let _ = writer.role.retire();
                recovery(command, retained)
            }
            None | Some(Some((PreparedDisposition::RecoveryRequired { .. }, _))) => {
                // Unresolved protected acceptance quarantines the new role.
                recovery(command, retained)
            }
        }
    }
}

impl OriginalConflict {
    fn matches(
        &self,
        admission: &NativeTransactionAdmission,
        record: &CommandRecord,
        control: &TransactionCommitControl,
    ) -> bool {
        record.outcome() == latent_commit::atomic::Outcome::Pending
            && self.command == record.id().hex()
            && self.transaction == record.transaction_id().hex()
            && self.fingerprint == record.fingerprint().bytes()
            && self.attempt == record.attempt()
            && self.epoch == record.owner_epoch()
            && self.original.publication() == record.source().publication
            && self
                .store
                .upgrade()
                .is_some_and(|store| store.is_same_owner(&admission.owners.store))
            && admission
                .retained_capacity()
                .is_ok_and(|retained| Arc::ptr_eq(&self.retained, &retained))
            && control.matches(
                self.original.authority.activation_id(),
                &self.original.budget,
            )
            && control.is_current()
            && self.retained.check_current().is_ok()
    }
}

struct Writer {
    original: Arc<StateAuthorization>,
    retained: Arc<TransactionRetention>,
    namespaces: Arc<NamespaceCatalog>,
    selection: RecoverySelection,
    time: Arc<dyn CommandTimeSource>,
    role: Arc<CommandRole>,
    reservation: Arc<NativeReservation>,
    _buffers: [NativeBufferPermit; 3],
    control: TransactionCommitControl,
}

impl Writer {
    fn new(
        admission: &NativeTransactionAdmission,
        marker: OriginalConflict,
        command: &CommandRecord,
        control: TransactionCommitControl,
    ) -> Result<Arc<Self>, AtomicError> {
        if !marker.matches(admission, command, &control) {
            return Err(AtomicError::PermissionDenied);
        }
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
                    marker.original.authority.deadline(),
                )
                .map_err(|_| AtomicError::Unavailable)?,
        );
        let buffers = [
            reservation
                .reserve_buffer(NativeBufferClass::Request, REQUEST_BYTES)
                .map_err(|_| AtomicError::Unavailable)?,
            reservation
                .reserve_buffer(NativeBufferClass::Work, WORK_BYTES)
                .map_err(|_| AtomicError::Unavailable)?,
            reservation
                .reserve_buffer(NativeBufferClass::Response, RESPONSE_BYTES)
                .map_err(|_| AtomicError::Unavailable)?,
        ];
        let role = CommandRole::capture(&admission.owners.command)?;
        if role.epoch() != command.owner_epoch() {
            role.retire()?;
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(Arc::new(Self {
            original: marker.original,
            retained: marker.retained,
            namespaces: Arc::clone(&admission.owners.namespaces),
            selection: admission.installation.recovery.clone(),
            time: Arc::clone(&admission.owners.time),
            role,
            reservation,
            _buffers: buffers,
            control,
        }))
    }

    fn publish(
        &self,
        store: &EmbeddedStore,
        proof: RetiredAttempt,
        identity: &CommandRecord,
    ) -> Result<Publication, StoreError> {
        let Some(observed) = self.control.observe_current() else {
            return Ok(None);
        };
        if self.retained.check_current().is_err() {
            return Ok(None);
        }
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
            PlatformErrorCode::StateConflict.wire_code().into(),
            self.time.sample(),
        ) else {
            return Ok(None);
        };
        if envelope.command().id() != identity.id()
            || envelope.command().attempt() != identity.attempt()
            || envelope.command().transaction_id() != identity.transaction_id()
            || envelope.command().source() != identity.source()
            || envelope.command().key() != identity.key()
            || envelope.command().fingerprint() != identity.fingerprint()
        {
            return Ok(None);
        }
        let Ok(authorization) =
            self.original
                .fresh_abort_authority(namespace, &self.namespaces, &self.selection, None)
        else {
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
                if !time.continuity_proven
                    || time.unix_millis < identity.clock_floor()
                    || time.unix_millis >= identity.identity_expires()
                    || !self.control.is_current_at(observed)
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
                        acceptance
                            .accept_with_final(
                                || Ok(()),
                                || {
                                    self.retained
                                        .native()
                                        .with_live_pair_until(
                                            &self.reservation,
                                            self.original.authority.deadline(),
                                            || {
                                                if self.control.is_current_at(observed) {
                                                    Ok(())
                                                } else {
                                                    Err(NamespaceError::PermissionDenied)
                                                }
                                            },
                                        )
                                        .map_err(|_| NamespaceError::PermissionDenied)?
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

fn recovery(
    command: CommandRecord,
    retained: Arc<TransactionRetention>,
) -> TransactionCompletionResult {
    TransactionCompletionResult::Command(CommandCompletionDisposition::RecoveryRequired {
        command,
        retained_native: Some(retained),
        cleanup_failure: None,
    })
}
