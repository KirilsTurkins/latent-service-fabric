//! Once-only completion driven by the node owner after real activation cleanup.
//! The RPC waiter never owns this future. Keep it in a bounded node work slot.
use super::{CommandTimeSource, StateTransactionHost};
use crate::TransactionCommitControl;
use latent_activation::ActivationOutcome;
use latent_commit::atomic::{
    AdmittedCommand, AtomicError, AttemptRetirement, CommandRecord, CompleteEnvelope,
    DurableResult, PreparedDisposition, RetiredAttempt,
};
use latent_core::{transaction_contract::Value, ActivationTerminalState, HostMemoryReservation};
use latent_effects::authority::{EffectAuthorityOwner, EffectTime};
use latent_executor::transaction::StateFailure;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore},
    namespace::NamespaceError,
    store_io::StoreIoKind,
};
use std::sync::Arc;

/// A durable outcome can coexist with a cleanup diagnostic. A failure after
/// acceptance must never be reclassified as an abort or trigger another guest.
pub enum CommandCompletionDisposition {
    Durable {
        command: CommandRecord,
        result: Box<DurableResult>,
        retained: Arc<HostMemoryReservation>,
        retained_native: Option<Arc<super::TransactionRetention>>,
        cleanup_failure: Option<StateFailure>,
    },
    /// This affine proof is issued only after every actual guest/native owner
    /// retires and the complete envelope is known not to have been accepted.
    Retired {
        command: CommandRecord,
        proof: Box<RetiredAttempt>,
        reason: AtomicError,
        retained: Arc<HostMemoryReservation>,
        retained_native: Option<Arc<super::TransactionRetention>>,
    },
    RecoveryRequired {
        command: CommandRecord,
        retained_native: Option<Arc<super::TransactionRetention>>,
        cleanup_failure: Option<StateFailure>,
    },
}

pub struct CommandCompletion {
    claim: AdmittedCommand,
    host: Arc<StateTransactionHost>,
    effects: EffectAuthorityOwner,
    time: Arc<dyn CommandTimeSource>,
    control: TransactionCommitControl,
}
impl CommandCompletion {
    pub fn new(
        claim: AdmittedCommand,
        host: Arc<StateTransactionHost>,
        effects: EffectAuthorityOwner,
        time: Arc<dyn CommandTimeSource>,
        control: TransactionCommitControl,
    ) -> Result<Self, AtomicError> {
        let command = host.command.as_ref().ok_or(AtomicError::PermissionDenied)?;
        let role = host
            .authorization
            .role
            .as_ref()
            .ok_or(AtomicError::PermissionDenied)?;
        if command.command_id != claim.record().id().hex()
            || command.attempt_id != claim.record().attempt().to_string()
            || host.authority().publication() != claim.record().source().publication
            || role.epoch() != claim.record().owner_epoch()
            || !control.matches(&host.activation, &host.authorization.budget)
        {
            return Err(AtomicError::PermissionDenied);
        }
        Ok(Self {
            claim,
            host,
            effects,
            time,
            control,
        })
    }

    /// `outcome` must come from the exact manager handle whose host this owner
    /// installed. Store destruction is checked again before any native handoff.
    pub async fn finish(self, outcome: ActivationOutcome) -> CommandCompletionDisposition {
        let identity = self.claim.record().clone();
        let retirement = self.claim.retirement();
        let prepared = match outcome {
            ActivationOutcome::Succeeded(success) => {
                let value = Value {
                    bytes: success.output,
                    media_type: success.output_media_type,
                    metadata: success.metadata.into_iter().collect(),
                };
                self.prepare_success(value).await
            }
            ActivationOutcome::DeclaredError { error, .. } => {
                let value = Value {
                    bytes: error.payload,
                    media_type: error.media_type,
                    metadata: error.metadata.into_iter().collect(),
                };
                self.prepare_rejection(error.code, value).await
            }
            ActivationOutcome::Failed { .. } => {
                drop(self.claim);
                return retired(&self.host, identity, retirement, AtomicError::Unavailable).await;
            }
        };
        match prepared {
            Ok((host, effects, time, control, envelope)) => {
                publish(host, effects, time, control, envelope, identity, retirement).await
            }
            Err((host, reason)) => retired(&host, identity, retirement, reason).await,
        }
    }

    async fn prepare_success(self, value: Value) -> Prepared {
        let handoff = match self.host.handoff().await {
            Ok(handoff) => handoff,
            Err(error) => {
                drop(self.claim);
                return Err((self.host, failure(error)));
            }
        };
        let effects = self.effects.clone();
        let time = self.time.sample();
        let result =
            self.host
                .store
                .with_view(handoff.view, self.host.retained_bytes, move |view| {
                    // Logical rejection remains nested; it cannot poison/quarantine the
                    // protected engine as though it were native corruption.
                    Ok(CompleteEnvelope::success_captured(
                        view,
                        self.claim,
                        Some(handoff.plan),
                        handoff.intents,
                        value,
                        &effects,
                        time,
                    ))
                });
        match result {
            Ok(job) => match job.await {
                Ok((view, result)) => {
                    view.retire().await;
                    match result {
                        Ok(Ok(envelope)) => {
                            Ok((self.host, self.effects, self.time, self.control, envelope))
                        }
                        Ok(Err(error)) => Err((self.host, error)),
                        Err(_) => Err((self.host, AtomicError::RecoveryRequired)),
                    }
                }
                Err(_) => Err((self.host, AtomicError::RecoveryRequired)),
            },
            Err(_) => Err((self.host, AtomicError::RecoveryRequired)),
        }
    }

    async fn prepare_rejection(self, code: String, value: Value) -> Prepared {
        // Discard every staged business mutation/intent before preparing the
        // permitted result/inbox-only envelope. This observes native retirement.
        if let Err(error) = self.host.retire().await {
            drop(self.claim);
            return Err((self.host, failure(error)));
        }
        let time = self.time.sample();
        let result =
            self.host
                .store
                .with_store(StoreIoKind::Read, self.host.retained_bytes, move |store| {
                    let view = store.snapshot()?;
                    Ok(CompleteEnvelope::rejection(
                        &view, self.claim, code, value, time,
                    ))
                });
        match result {
            Ok(job) => match job.await {
                Ok(Ok(Ok(envelope))) => {
                    Ok((self.host, self.effects, self.time, self.control, envelope))
                }
                Ok(Ok(Err(error))) => Err((self.host, error)),
                _ => Err((self.host, AtomicError::RecoveryRequired)),
            },
            Err(_) => Err((self.host, AtomicError::RecoveryRequired)),
        }
    }
}
type Prepared = Result<
    (
        Arc<StateTransactionHost>,
        EffectAuthorityOwner,
        Arc<dyn CommandTimeSource>,
        TransactionCommitControl,
        CompleteEnvelope,
    ),
    (Arc<StateTransactionHost>, AtomicError),
>;

async fn publish(
    host: Arc<StateTransactionHost>,
    effects: EffectAuthorityOwner,
    time: Arc<dyn CommandTimeSource>,
    control: TransactionCommitControl,
    envelope: CompleteEnvelope,
    identity: CommandRecord,
    retirement: AttemptRetirement,
) -> CommandCompletionDisposition {
    let authorization = Arc::clone(&host.authorization);
    let result = host
        .store
        .with_store(StoreIoKind::Write, host.retained_bytes, move |store| {
            Ok(publish_fenced(
                store,
                &authorization,
                &effects,
                time.as_ref(),
                &control,
                envelope,
            ))
        });
    let disposition = match result {
        Ok(job) => match job.await {
            Ok(Ok(result)) => result,
            _ => return recovery(&host, identity).await,
        },
        Err(_) => return recovery(&host, identity).await,
    };
    match disposition {
        PreparedDisposition::Confirmed { command, result } => {
            let mut cleanup_failure = host.retire().await.err();
            if cleanup_failure.is_none() && host.retire_command_role().is_err() {
                cleanup_failure = Some(StateFailure::Unavailable);
            }
            CommandCompletionDisposition::Durable {
                command: *command,
                result,
                retained: Arc::clone(&host.memory),
                retained_native: host.authorization.retention.clone(),
                cleanup_failure,
            }
        }
        PreparedDisposition::KnownNotCommitted { command, reason } => {
            drop(command);
            retired(&host, identity, retirement, reason).await
        }
        PreparedDisposition::RecoveryRequired { identity } => recovery(&host, *identity).await,
    }
}

fn publish_fenced(
    store: &EmbeddedStore,
    authorization: &super::StateAuthorization,
    effects: &EffectAuthorityOwner,
    _time: &dyn CommandTimeSource,
    control: &TransactionCommitControl,
    envelope: CompleteEnvelope,
) -> PreparedDisposition {
    let proposed = match envelope.command().outcome() {
        latent_commit::atomic::Outcome::Committed => ActivationTerminalState::Completed,
        latent_commit::atomic::Outcome::Rejected => ActivationTerminalState::Rejected,
        _ => {
            return PreparedDisposition::RecoveryRequired {
                identity: Box::new(envelope.command().clone()),
            }
        }
    };
    // Copy only the already-owned namespace expectation, never the potentially
    // multi-megabyte batch. It is selected from the actual immutable envelope.
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
    envelope.publish(store, |authorities| {
        let role = authorization
            .role
            .as_ref()
            .ok_or(AtomicError::PermissionDenied)?;
        role.with_current(|sample| {
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
                            || {
                                effects
                                    .commit_fence(
                                        authorities,
                                        EffectTime {
                                            unix_millis: sample.unix_millis,
                                            continuity_proven: sample.continuity_proven,
                                        },
                                    )
                                    .map_err(|_| NamespaceError::PermissionDenied)
                            },
                            || {
                                let accept = || {
                                    control
                                        .accept(proposed)
                                        .then_some(())
                                        .ok_or(NamespaceError::PermissionDenied)
                                };
                                // Same global owner and original deadline. Keep
                                // the short Native fence after Policy/Namespace/
                                // Effects and through the original cancellation
                                // CAS; never hold it across physical publication.
                                if let Some(retained) = &authorization.retention {
                                    retained
                                        .with_current(accept)
                                        .map_err(|_| NamespaceError::PermissionDenied)?
                                } else {
                                    accept()
                                }
                            },
                        )
                        .map_err(|_| super::authorization::denied())
                })
                .map_err(|_| AtomicError::PermissionDenied)
        })
    })
}

async fn retired(
    host: &StateTransactionHost,
    command: CommandRecord,
    retirement: AttemptRetirement,
    reason: AtomicError,
) -> CommandCompletionDisposition {
    let cleanup_failure = host.retire().await.err();
    if cleanup_failure.is_none() {
        if let Ok(proof) = retirement.proven_noncommit() {
            if host.retire_command_role().is_err() {
                return CommandCompletionDisposition::RecoveryRequired {
                    command,
                    retained_native: host.authorization.retention.clone(),
                    cleanup_failure: Some(StateFailure::Unavailable),
                };
            }
            return CommandCompletionDisposition::Retired {
                command,
                proof: Box::new(proof),
                reason,
                retained: Arc::clone(&host.memory),
                retained_native: host.authorization.retention.clone(),
            };
        }
    }
    CommandCompletionDisposition::RecoveryRequired {
        command,
        retained_native: host.authorization.retention.clone(),
        cleanup_failure,
    }
}
async fn recovery(
    host: &StateTransactionHost,
    command: CommandRecord,
) -> CommandCompletionDisposition {
    CommandCompletionDisposition::RecoveryRequired {
        command,
        retained_native: host.authorization.retention.clone(),
        cleanup_failure: host.retire().await.err(),
    }
}
fn failure(error: StateFailure) -> AtomicError {
    match error {
        StateFailure::PermissionDenied => AtomicError::PermissionDenied,
        StateFailure::Conflict => AtomicError::Conflict,
        _ => AtomicError::Unavailable,
    }
}
