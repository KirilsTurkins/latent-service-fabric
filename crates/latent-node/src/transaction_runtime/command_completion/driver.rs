use std::sync::{Arc, Mutex};

use latent_activation::ActivationOutcome;
use latent_commit::atomic::{
    AdmittedCommand, AtomicError, AttemptRetirement, CapturedIntent, CommandRecord, CommandTime,
    CompleteEnvelope, PreparedDisposition, RetiredAttempt,
};
use latent_core::{BoxFuture, HostMemoryReservation, PlatformError};
use latent_effects::authority::EffectAuthorityOwner;
use latent_state::{
    embedded::{EmbeddedStore, ReadView, StoreError},
    protected_store::ProtectedStoreOperation,
    session::StatePlan,
    store_io::StoreIoKind,
};

use super::super::{StateAuthorization, StateHandoff, StateTransactionHost};
use super::{
    errors, lookup::failed, native::NativeCommandWork, CommandCoordinator, CommandObservation,
    CommandOutput, CommandResultCodec, TransactionCompletion,
};
use crate::{
    activation_manager::TransactionCompletionHook, command_waiters::CommandNotificationOwner,
};

// Reserved from the actual activation before factory/admission allocations and
// held through accepted worker buffers and the delivered closed observation.
pub(super) const DRIVER_BYTES: u64 = 24 * 1024 * 1024;
// State and intent staging are each bounded by STAGED_BYTES, even before the
// final combined-batch check. Payloads are moved into encoded rows. The extra
// 8 MiB covers bounded result/encoder/authority/key overhead, while the engine
// cache has its separate resident reservation. Keep this below the installed
// protected owner's unchanged 40 MiB per-job cap.
const WRITER_JOB_BYTES: u64 =
    2 * latent_core::transaction_contract::STAGED_BYTES as u64 + 8 * 1024 * 1024;

struct Attempt {
    claim: AdmittedCommand,
    operation: ProtectedStoreOperation,
    notification: CommandNotificationOwner,
    memory: Arc<HostMemoryReservation>,
}
struct HandoffPayload {
    claim: AdmittedCommand,
    plan: StatePlan,
    intents: Vec<CapturedIntent>,
    value: latent_core::transaction_contract::Value,
}
pub(super) struct CommandCompletion {
    coordinator: CommandCoordinator,
    host: Arc<StateTransactionHost>,
    attempt: Mutex<Option<Attempt>>,
    result_read: Arc<StateAuthorization>,
    codec: Arc<dyn CommandResultCodec>,
}
impl CommandCompletion {
    #[allow(
        clippy::too_many_arguments,
        reason = "Every affine owner is retained from the same admitted attempt"
    )]
    pub fn new(
        coordinator: CommandCoordinator,
        host: Arc<StateTransactionHost>,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        notification: CommandNotificationOwner,
        result_read: Arc<StateAuthorization>,
        codec: Arc<dyn CommandResultCodec>,
        memory: Arc<HostMemoryReservation>,
    ) -> Self {
        Self {
            coordinator,
            host,
            attempt: Mutex::new(Some(Attempt {
                claim,
                operation,
                notification,
                memory,
            })),
            result_read,
            codec,
        }
    }

    async fn finish(&self, outcome: ActivationOutcome, attempt: Attempt) -> TransactionCompletion {
        let Attempt {
            claim,
            operation,
            notification,
            memory,
        } = attempt;
        let record = claim.record().clone();
        let retirement = claim.retirement();
        let validated = self.codec.validate(&outcome);
        let completion = match validated {
            Ok(CommandOutput::Success(value)) => match self.host.handoff().await {
                Ok(handoff) => {
                    Box::pin(self.success(
                        claim, operation, retirement, record, value, handoff, outcome, memory,
                    ))
                    .await
                }
                Err(error) => {
                    self.abort(
                        claim,
                        operation,
                        retirement,
                        record,
                        failure(outcome, errors::state(error)),
                        memory,
                    )
                    .await
                }
            },
            Ok(CommandOutput::Rejection { code, value }) => {
                Box::pin(self.rejection(
                    claim, operation, retirement, record, code, value, outcome, memory,
                ))
                .await
            }
            Err(error) => {
                self.abort(
                    claim,
                    operation,
                    retirement,
                    record,
                    failure(outcome, error),
                    memory,
                )
                .await
            }
        };
        // Both explicit finish and Drop are hints. The next observer reads the
        // original durable row under fresh current permission, regardless of this result.
        notification.notify_reload();
        completion
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "Original claim, physical owners, output and handoff remain affine"
    )]
    async fn success(
        &self,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        retirement: AttemptRetirement,
        record: CommandRecord,
        value: latent_core::transaction_contract::Value,
        handoff: StateHandoff,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let work = match claim.physical_work() {
            Ok(work) => work,
            Err(error) => {
                handoff.view.retire().await;
                return self
                    .abort(
                        claim,
                        operation,
                        retirement,
                        record,
                        failure(outcome, errors::atomic(error)),
                        memory,
                    )
                    .await;
            }
        };
        let StateHandoff {
            view,
            plan,
            intents,
            memory: session_memory,
        } = handoff;
        let effects = self.coordinator.effects.clone();
        let time = Arc::clone(&self.coordinator.time);
        let mut native = NativeCommandWork::new(operation, Some(work), Some(Arc::clone(&memory)));
        let preparation = self
            .coordinator
            .store
            .with_view(view, WRITER_JOB_BYTES, move |view| {
                native.enter();
                let prepared = prepare_handoff(
                    view,
                    HandoffPayload {
                        claim,
                        plan,
                        intents,
                        value,
                    },
                    effects,
                    time.sample(),
                );
                let prepared = match prepared {
                    Ok(value) => Ok(value),
                    Err(error) => Err(errors::storage(error)?),
                };
                let operation = native
                    .into_operation()
                    .map_err(|_| StoreError::Unavailable)?;
                Ok((prepared, operation, session_memory))
            });
        let (view, prepared) = match preparation {
            Ok(job) => match job.await {
                Ok(result) => result,
                Err(_) => return self.recovery(record, outcome, memory).await,
            },
            Err(_) => return self.recovery(record, outcome, memory).await,
        };
        view.retire().await;
        let Ok((prepared, operation, session_memory)) = prepared else {
            return self.recovery(record, outcome, memory).await;
        };
        if let Err(error) = self.host.retire().await {
            operation.retire().await;
            return self
                .recovery(record, failure(outcome, errors::state(error)), memory)
                .await;
        }
        match prepared {
            Ok(envelope) => {
                self.publish(
                    envelope,
                    operation,
                    retirement,
                    record,
                    outcome,
                    memory,
                    Some(session_memory),
                )
                .await
            }
            Err(error) => {
                operation.retire().await;
                self.abort_retired(
                    retirement,
                    record,
                    failure(outcome, errors::atomic(error)),
                    memory,
                )
                .await
            }
        }
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "Rejection drops the actual staged owners before preparing the same terminal envelope"
    )]
    async fn rejection(
        &self,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        retirement: AttemptRetirement,
        record: CommandRecord,
        code: String,
        value: latent_core::transaction_contract::Value,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        if let Err(error) = self.host.retire().await {
            drop(claim);
            operation.retire().await;
            return self
                .recovery(record, failure(outcome, errors::state(error)), memory)
                .await;
        }
        let work = match claim.physical_work() {
            Ok(work) => work,
            Err(error) => {
                drop(claim);
                operation.retire().await;
                return self
                    .abort_retired(
                        retirement,
                        record,
                        failure(outcome, errors::atomic(error)),
                        memory,
                    )
                    .await;
            }
        };
        let time = Arc::clone(&self.coordinator.time);
        let mut native = NativeCommandWork::new(operation, Some(work), Some(Arc::clone(&memory)));
        let preparation =
            self.coordinator
                .store
                .with_store(StoreIoKind::Read, WRITER_JOB_BYTES, move |store| {
                    native.enter();
                    let view = store.snapshot()?;
                    let prepared =
                        match CompleteEnvelope::rejection(&view, claim, code, value, time.sample())
                        {
                            Ok(value) => Ok(value),
                            Err(error) => Err(errors::storage(error)?),
                        };
                    let operation = native
                        .into_operation()
                        .map_err(|_| StoreError::Unavailable)?;
                    Ok((prepared, operation))
                });
        let prepared = match preparation {
            Ok(job) => match job.await {
                Ok(Ok(result)) => result,
                _ => return self.recovery(record, outcome, memory).await,
            },
            Err(_) => return self.recovery(record, outcome, memory).await,
        };
        match prepared {
            (Ok(envelope), operation) => {
                self.publish(
                    envelope, operation, retirement, record, outcome, memory, None,
                )
                .await
            }
            (Err(error), operation) => {
                operation.retire().await;
                self.abort_retired(
                    retirement,
                    record,
                    failure(outcome, errors::atomic(error)),
                    memory,
                )
                .await
            }
        }
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "Publication retains all original physical and memory owners until the actual worker returns"
    )]
    async fn publish(
        &self,
        envelope: CompleteEnvelope,
        operation: ProtectedStoreOperation,
        retirement: AttemptRetirement,
        record: CommandRecord,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
        session_memory: Option<Arc<HostMemoryReservation>>,
    ) -> TransactionCompletion {
        let fence = match envelope.namespace_expectation() {
            Ok(fence) => fence,
            Err(error) => {
                drop(envelope);
                operation.retire().await;
                return self
                    .abort_retired(
                        retirement,
                        record,
                        failure(outcome, errors::atomic(error)),
                        memory,
                    )
                    .await;
            }
        };
        let work = match envelope.physical_work() {
            Ok(work) => work,
            Err(error) => {
                drop(envelope);
                operation.retire().await;
                return self
                    .abort_retired(
                        retirement,
                        record,
                        failure(outcome, errors::atomic(error)),
                        memory,
                    )
                    .await;
            }
        };
        let auth = Arc::clone(&self.host.authorization);
        let effects = self.coordinator.effects.clone();
        let time = Arc::clone(&self.coordinator.time);
        let mut native = NativeCommandWork::new(operation, Some(work), Some(Arc::clone(&memory)));
        let job =
            self.coordinator
                .store
                .with_store(StoreIoKind::Write, WRITER_JOB_BYTES, move |store| {
                    native.enter();
                    let _session_memory = session_memory;
                    let disposition = envelope.publish(store, |authorities| {
                        auth.accept_commit(&fence, effects.as_ref(), authorities, time.sample())
                            .map_err(|_| AtomicError::PermissionDenied)
                    });
                    native.complete();
                    Ok(disposition)
                });
        let disposition = match job {
            Ok(job) => match job.await {
                Ok(Ok(value)) => value,
                _ => return self.recovery(record, outcome, memory).await,
            },
            Err(_) => {
                return self
                    .abort_retired(
                        retirement,
                        record,
                        failure(outcome, errors::atomic(AtomicError::Limit)),
                        memory,
                    )
                    .await
            }
        };
        match disposition {
            PreparedDisposition::Confirmed { command, result } => {
                self.coordinator
                    .deliver_confirmed(outcome, *command, &result, &self.result_read, memory)
                    .await
            }
            PreparedDisposition::KnownNotCommitted { command, reason } => {
                drop(command);
                self.abort_retired(
                    retirement,
                    record,
                    failure(outcome, errors::atomic(reason)),
                    memory,
                )
                .await
            }
            PreparedDisposition::RecoveryRequired { identity } => {
                self.recovery(*identity, outcome, memory).await
            }
        }
    }

    async fn abort(
        &self,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        retirement: AttemptRetirement,
        record: CommandRecord,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let retired = self.host.retire().await;
        drop(claim);
        operation.retire().await;
        if retired.is_err() {
            return self.recovery(record, outcome, memory).await;
        }
        self.abort_retired(retirement, record, outcome, memory)
            .await
    }
    async fn abort_retired(
        &self,
        retirement: AttemptRetirement,
        record: CommandRecord,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        self.coordinator
            .abort_retired(
                retirement,
                record,
                Arc::clone(&self.result_read),
                outcome,
                memory,
            )
            .await
    }
    async fn recovery(
        &self,
        record: CommandRecord,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        self.coordinator
            .observation(
                record,
                outcome,
                CommandObservation::RecoveryRequired,
                &self.result_read,
                memory,
            )
            .await
    }
}
impl TransactionCompletionHook for CommandCompletion {
    fn complete(&self, outcome: ActivationOutcome) -> BoxFuture<'_, TransactionCompletion> {
        Box::pin(async move {
            let attempt = self.attempt.lock().ok().and_then(|mut slot| slot.take());
            match attempt {
                Some(attempt) => Box::pin(self.finish(outcome, attempt)).await,
                None => TransactionCompletion::ordinary(failure(
                    outcome,
                    errors::atomic(AtomicError::RecoveryRequired),
                )),
            }
        })
    }
}

impl CommandCoordinator {
    pub(super) async fn abort_unstarted(
        &self,
        retirement: AttemptRetirement,
        record: CommandRecord,
        read: Arc<StateAuthorization>,
        error: PlatformError,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let outcome = failed(error, read.budget.snapshot_at(std::time::Instant::now()));
        self.abort_retired(retirement, record, read, outcome, memory)
            .await
    }

    async fn abort_retired(
        &self,
        retirement: AttemptRetirement,
        record: CommandRecord,
        read: Arc<StateAuthorization>,
        outcome: ActivationOutcome,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let Ok(attempt) = retirement.proven_noncommit() else {
            return self
                .observation(
                    record,
                    outcome,
                    CommandObservation::RecoveryRequired,
                    &read,
                    memory,
                )
                .await;
        };
        let current = match self
            .read_namespace(&read)
            .await
            .and_then(|row| read.rebind_result_read(row))
        {
            Ok(current) => Arc::new(current),
            Err(_) => {
                return self
                    .observation(
                        record,
                        outcome,
                        CommandObservation::RecoveryRequired,
                        &read,
                        memory,
                    )
                    .await
            }
        };
        let Ok(operation) = self.store.reserve_operation() else {
            return self
                .observation(
                    record,
                    outcome,
                    CommandObservation::RecoveryRequired,
                    &read,
                    memory,
                )
                .await;
        };
        let mut native = NativeCommandWork::new(operation, None, Some(Arc::clone(&memory)));
        let time = Arc::clone(&self.time);
        let code = match &outcome {
            ActivationOutcome::Failed { error, .. } => error.code.wire_code(),
            _ => "internal",
        }
        .to_owned();
        let job = self
            .store
            .with_store(StoreIoKind::Write, WRITER_JOB_BYTES, move |store| {
                native.enter();
                let view = store.snapshot()?;
                let disposition =
                    prepare_abort(&view, store, attempt, code, &current, time.sample());
                native.complete();
                disposition
            });
        match job {
            Ok(job) => match job.await {
                Ok(Ok(Ok(PreparedDisposition::Confirmed { command, result }))) => {
                    self.deliver_confirmed(outcome, *command, &result, &read, memory)
                        .await
                }
                _ => {
                    self.observation(
                        record,
                        outcome,
                        CommandObservation::RecoveryRequired,
                        &read,
                        memory,
                    )
                    .await
                }
            },
            Err(_) => {
                self.observation(
                    record,
                    outcome,
                    CommandObservation::RecoveryRequired,
                    &read,
                    memory,
                )
                .await
            }
        }
    }

    async fn deliver_confirmed(
        &self,
        mut outcome: ActivationOutcome,
        record: CommandRecord,
        result: &latent_commit::atomic::DurableResult,
        read: &Arc<StateAuthorization>,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let permission = self.release_permission(read, &record).await;
        if let ActivationOutcome::Succeeded(success) = &mut outcome {
            success.committed_state_version = super::output::committed_view_text(&record);
            success.effect_ids = record
                .effect_ids()
                .iter()
                .map(|identity| identity.hex())
                .collect();
        }
        let (delivery_fence, delivery_failure) = match permission {
            Ok(fence) => (Some(Arc::new(fence)), None),
            Err(error) => (None, Some(error)),
        };
        let outcome = match &delivery_failure {
            Some(error) => failure(outcome, error.clone()),
            None => outcome,
        };
        match TransactionCompletion::confirmed(
            outcome,
            record,
            result,
            delivery_failure.is_none(),
            Some(memory),
        ) {
            Ok(mut completion) => {
                completion.delivery_failure = delivery_failure;
                completion.delivery_fence = delivery_fence;
                completion
            }
            Err(error) => TransactionCompletion::ordinary(failed(
                error,
                latent_core::BudgetConsumption::default(),
            )),
        }
    }
    async fn observation(
        &self,
        record: CommandRecord,
        outcome: ActivationOutcome,
        observation: CommandObservation,
        read: &Arc<StateAuthorization>,
        memory: Arc<HostMemoryReservation>,
    ) -> TransactionCompletion {
        let permission = self.release_permission(read, &record).await;
        let (delivery_fence, delivery_failure) = match permission {
            Ok(fence) => (Some(Arc::new(fence)), None),
            Err(error) => (None, Some(error)),
        };
        let outcome = match &delivery_failure {
            Some(error) => failure(outcome, error.clone()),
            None => failure(outcome, errors::atomic(AtomicError::RecoveryRequired)),
        };
        let mut completion = TransactionCompletion::observed(
            outcome,
            record,
            observation,
            delivery_failure.is_none(),
            Some(memory),
        );
        completion.delivery_failure = delivery_failure;
        completion.delivery_fence = delivery_fence;
        completion
    }
}

fn failure(outcome: ActivationOutcome, error: PlatformError) -> ActivationOutcome {
    if matches!(&outcome, ActivationOutcome::Failed { .. }) {
        outcome
    } else {
        failed(
            error,
            crate::activation_runner::outcome_consumption(&outcome),
        )
    }
}

fn prepare_handoff(
    view: &ReadView,
    input: HandoffPayload,
    effects: Option<EffectAuthorityOwner>,
    time: CommandTime,
) -> Result<CompleteEnvelope, AtomicError> {
    let HandoffPayload {
        claim,
        plan,
        intents,
        value,
    } = input;
    if intents.is_empty() {
        CompleteEnvelope::success_without_intents(view, claim, Some(plan), value, time)
    } else if let Some(effects) = effects {
        CompleteEnvelope::success_captured(view, claim, Some(plan), intents, value, &effects, time)
    } else {
        Err(AtomicError::PermissionDenied)
    }
}

fn prepare_abort(
    view: &ReadView,
    store: &EmbeddedStore,
    attempt: RetiredAttempt,
    code: String,
    current: &StateAuthorization,
    time: CommandTime,
) -> Result<Result<PreparedDisposition, AtomicError>, StoreError> {
    let prepared = match CompleteEnvelope::technical_abort(view, attempt, code, time) {
        Ok(value) => value,
        Err(error) => return errors::storage(error).map(Err),
    };
    let fence = match prepared.namespace_expectation() {
        Ok(value) => value,
        Err(error) => return errors::storage(error).map(Err),
    };
    Ok(Ok(prepared.publish(store, |_| {
        current
            .accept_abort(&fence)
            .map_err(|_| AtomicError::PermissionDenied)
    })))
}
