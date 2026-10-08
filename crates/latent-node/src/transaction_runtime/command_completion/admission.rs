use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

use latent_activation::ActivationEnvelope;
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, AdmittedCommand, AtomicError, CommandAccess, CommandRecord,
    PreparedAdmission,
};
use latent_core::{
    transaction_contract::Precondition, ActivationBudget, ActivationId, BoxFuture,
    HostMemoryReservation, PlatformError,
};
use latent_effects::authority::EffectAuthorityOwner;
use latent_state::{
    embedded::StoreError,
    protected_store::{ProtectedStoreOperation, ProtectedStoreOwner},
    session::{StateMode, StateScope},
    store_io::StoreIoKind,
};

use super::super::{
    CommandHostSelection, CommandTimeSource, StateAuthorization, StateTransactionHost,
};
use super::{
    driver::{CommandCompletion, DRIVER_BYTES},
    errors,
    native::NativeCommandWork,
    CommandResultCodec,
};
use crate::{
    activation_manager::{
        TransactionActivationAdmission, TransactionAdmission, TransactionAdmissionControl,
        TransactionExecution,
    },
    command_waiters::{CommandNotificationOwner, CommandWaiterRegistry},
};

/// Configured admission retains the actual selected publication and distinct
/// acquire-command/read-result policy owners. The node supplies its real budget.
pub trait CommandAdmissionFactory: Send + Sync {
    fn select<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<CommandAdmissionSelection, PlatformError>>;
}
pub struct CommandAdmissionSelection {
    input: AdmissionInput,
    conditions: Vec<Precondition>,
    scope: StateScope,
    execution: Arc<StateAuthorization>,
    result_read: Arc<StateAuthorization>,
    codec: Arc<dyn CommandResultCodec>,
}
impl CommandAdmissionSelection {
    pub fn new(
        input: AdmissionInput,
        conditions: Vec<Precondition>,
        scope: StateScope,
        execution: Arc<StateAuthorization>,
        result_read: Arc<StateAuthorization>,
        codec: Arc<dyn CommandResultCodec>,
    ) -> Result<Self, PlatformError> {
        use latent_capabilities::namespace::Mode;
        let ownership = execution.authority.ownership();
        if execution.authority_mode() != Mode::Command
            || result_read.authority_mode() != Mode::Inspection
            || execution.activation_id() != result_read.activation_id()
            || !execution.budget.is_same_instance(&result_read.budget)
            || ownership != result_read.authority.ownership()
            || execution.publication() != result_read.publication()
            || scope.mode != StateMode::Command
            || scope.tenant != ownership.tenant
            || scope.namespace.0 != ownership.namespace
            || scope.incarnation != ownership.incarnation
            || scope.entity != ownership.entity
            || scope.state_schema != execution.namespace.record().state_schema
            || input.key.tenant != ownership.tenant.0
            || input.key.namespace != ownership.namespace
            || input.key.incarnation != ownership.incarnation.to_string()
            || input.key.entity != ownership.entity
            || input.key.recovery_scope != ownership.caller.scope
            || input.result_read_policy != ownership.result_policy
            || input.source.publication != execution.publication()
            || input.source.state_schema != scope.state_schema
            || input.source.result_format != codec.format()
            || conditions != input.fingerprint.expected_versions
        {
            return Err(errors::atomic(AtomicError::PermissionDenied));
        }
        input.source.validate().map_err(errors::atomic)?;
        input.result_policy.validate().map_err(errors::atomic)?;
        latent_core::transaction_contract::identity(codec.format())
            .map_err(|_| errors::atomic(AtomicError::Invalid))?;
        input
            .fingerprint
            .input
            .validate()
            .map_err(|_| errors::atomic(AtomicError::Invalid))?;
        Ok(Self {
            input,
            conditions,
            scope,
            execution,
            result_read,
            codec,
        })
    }
}
struct ExecutionSelection {
    conditions: Vec<Precondition>,
    scope: StateScope,
    execution: Arc<StateAuthorization>,
    result_read: Arc<StateAuthorization>,
    codec: Arc<dyn CommandResultCodec>,
    memory: Arc<HostMemoryReservation>,
}

/// Shared owners; no dispatcher, timer, execution map or second store is created.
#[derive(Clone)]
pub struct CommandCoordinator {
    pub(super) store: Arc<ProtectedStoreOwner>,
    pub(super) waiters: CommandWaiterRegistry,
    pub(super) effects: Option<EffectAuthorityOwner>,
    pub(super) time: Arc<dyn CommandTimeSource>,
}
impl CommandCoordinator {
    #[must_use]
    pub fn new(
        store: Arc<ProtectedStoreOwner>,
        waiters: CommandWaiterRegistry,
        effects: Option<EffectAuthorityOwner>,
        time: Arc<dyn CommandTimeSource>,
    ) -> Self {
        Self {
            store,
            waiters,
            effects,
            time,
        }
    }
    #[must_use]
    pub fn admission(&self, factory: Arc<dyn CommandAdmissionFactory>) -> Arc<CommandAdmission> {
        Arc::new(CommandAdmission {
            coordinator: self.clone(),
            factory,
            control: Mutex::new(None),
            admitted: AtomicBool::new(false),
        })
    }
}
pub struct CommandAdmission {
    coordinator: CommandCoordinator,
    factory: Arc<dyn CommandAdmissionFactory>,
    control: Mutex<Option<TransactionAdmissionControl>>,
    admitted: AtomicBool,
}
impl TransactionActivationAdmission for CommandAdmission {
    fn bind_control(&self, control: TransactionAdmissionControl) -> Result<(), PlatformError> {
        let mut slot = self
            .control
            .lock()
            .map_err(|_| errors::atomic(AtomicError::Unavailable))?;
        if slot.is_some() || self.admitted.load(Ordering::Acquire) {
            return Err(errors::atomic(AtomicError::Conflict));
        }
        *slot = Some(control);
        Ok(())
    }
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(self.admit_owned(envelope, budget))
    }
}
impl CommandAdmission {
    async fn admit_owned(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<TransactionAdmission, PlatformError> {
        if self.admitted.swap(true, Ordering::AcqRel) {
            return Err(errors::atomic(AtomicError::Conflict));
        }
        let control = self
            .control
            .lock()
            .map_err(|_| errors::atomic(AtomicError::Unavailable))?
            .take()
            .ok_or_else(|| errors::atomic(AtomicError::PermissionDenied))?;
        let memory = Arc::new(
            budget
                .reserve_host_memory(DRIVER_BYTES)
                .map_err(|_| errors::atomic(AtomicError::Limit))?,
        );
        let selected = self.factory.select(envelope, budget).await?;
        selected
            .execution
            .accepts_envelope(envelope, budget, &selected.input)?;
        control.bind_command(&selected.execution)?;
        let token = control.token();
        let CommandAdmissionSelection {
            input,
            conditions,
            scope,
            execution,
            result_read,
            codec,
        } = selected;
        let key = input.key.clone();
        let (decision, operation) = self
            .publish_claim(
                input,
                Arc::clone(&execution),
                Arc::clone(&result_read),
                Arc::clone(&memory),
            )
            .await?;
        match decision {
            ClaimDecision::Existing(record) => {
                // Current selection may not replace the original retained source.
                operation.retire().await;
                result_read.accepts_record(&record)?;
                drop(memory);
                let completion = self
                    .coordinator
                    .lookup(key, result_read, codec, true, Some(token))
                    .await;
                Ok(TransactionAdmission::Existing(Box::new(completion)))
            }
            ClaimDecision::New(claim) => {
                self.open_claim(
                    claim,
                    operation,
                    ExecutionSelection {
                        conditions,
                        scope,
                        execution,
                        result_read,
                        codec,
                        memory,
                    },
                    envelope.activation_id.clone(),
                )
                .await
            }
        }
    }

    async fn publish_claim(
        &self,
        input: AdmissionInput,
        auth: Arc<StateAuthorization>,
        read: Arc<StateAuthorization>,
        memory: Arc<HostMemoryReservation>,
    ) -> Result<(ClaimDecision, ProtectedStoreOperation), PlatformError> {
        let retained = admission_bytes(&input)?;
        let operation = self
            .coordinator
            .store
            .reserve_operation()
            .map_err(errors::protected)?;
        let mut native = NativeCommandWork::new(operation, None, Some(memory));
        let time = Arc::clone(&self.coordinator.time);
        let job =
            self.coordinator
                .store
                .with_store(StoreIoKind::Write, retained, move |store| {
                    native.enter();
                    let decision = (|| {
                        let view = store.snapshot()?;
                        let ownership = auth.authority.ownership();
                        latent_state::recovery::require_namespace_ready(
                            &view,
                            &ownership.tenant,
                            &latent_core::StateNamespaceId(ownership.namespace.clone()),
                            ownership.incarnation,
                        )?;
                        let expected = auth.namespace.expectation();
                        if view.get(&expected.key)? != expected.value {
                            return Ok(Err(AtomicError::Conflict));
                        }
                        let prepared = match PreparedAdmission::prepare(
                            &view,
                            input,
                            time.sample(),
                            |access, record| {
                                if access == CommandAccess::Replay {
                                    if let Some(record) = record {
                                        read.accepts_record(record)
                                            .map_err(|_| AtomicError::PermissionDenied)?;
                                    }
                                    read.authorize("read-result", 0, 0, || Ok(()))
                                        .map_err(|_| AtomicError::PermissionDenied)
                                } else {
                                    auth.authorize("acquire-command", 0, 0, || Ok(()))
                                        .map_err(|_| AtomicError::PermissionDenied)
                                }
                            },
                        ) {
                            Ok(value) => value,
                            Err(error) => return errors::storage(error).map(Err),
                        };
                        let result = match prepared {
                            AdmissionDecision::Existing(record) => {
                                Ok(ClaimDecision::Existing(record))
                            }
                            AdmissionDecision::New(prepared) => {
                                if !prepared.batch().expectations.iter().any(|row| {
                                    row.key == expected.key && row.value == expected.value
                                }) {
                                    return Ok(Err(AtomicError::Invalid));
                                }
                                prepared
                                    .publish(store, || {
                                        auth.authorize("acquire-command", 0, 0, || Ok(()))
                                            .map_err(|_| AtomicError::PermissionDenied)
                                    })
                                    .map(ClaimDecision::New)
                            }
                        };
                        match result {
                            Ok(value) => Ok(Ok(value)),
                            Err(error) => errors::storage(error).map(Err),
                        }
                    })();
                    let operation = native
                        .into_operation()
                        .map_err(|_| StoreError::Unavailable)?;
                    Ok((decision, operation))
                })
                .map_err(errors::protected)?;
        let (decision, operation) = job
            .await
            .map_err(|_| errors::atomic(AtomicError::RecoveryRequired))?
            .map_err(errors::protected)?;
        match decision {
            Ok(Ok(value)) => Ok((value, operation)),
            Ok(Err(error)) => {
                operation.retire().await;
                Err(errors::atomic(error))
            }
            Err(error) => {
                operation.retire().await;
                Err(errors::atomic(error.into()))
            }
        }
    }

    async fn open_claim(
        &self,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        mut selected: ExecutionSelection,
        activation: ActivationId,
    ) -> Result<TransactionAdmission, PlatformError> {
        let post = self.coordinator.read_namespace(&selected.execution).await;
        selected.execution =
            match post.and_then(|row| selected.execution.rebind_command_after_claim(&claim, row)) {
                Ok(value) => Arc::new(value),
                Err(error) => {
                    return Ok(self
                        .abort_before_host(claim, operation, selected, None, error)
                        .await)
                }
            };
        let Ok(notification) = self.coordinator.waiters.register(&claim) else {
            return Ok(self
                .abort_before_host(
                    claim,
                    operation,
                    selected,
                    None,
                    errors::atomic(AtomicError::Limit),
                )
                .await);
        };
        let view = latent_executor::transaction::ViewIdentity {
            namespace: selected.scope.namespace.0.clone(),
            incarnation: selected.scope.incarnation.to_string(),
            version: vec![],
            state_schema: selected.scope.state_schema.clone(),
        };
        let host_selection = match CommandHostSelection::from_claim(&claim, view) {
            Ok(value) => value,
            Err(error) => {
                return Ok(self
                    .abort_before_host(
                        claim,
                        operation,
                        selected,
                        Some(notification),
                        errors::atomic(error),
                    )
                    .await)
            }
        };
        let host = match StateTransactionHost::open(
            Arc::clone(&self.coordinator.store),
            Arc::clone(&selected.execution),
            activation,
            selected.scope.clone(),
            Some(host_selection),
            self.coordinator.effects.clone(),
            Arc::clone(&self.coordinator.time),
            std::mem::take(&mut selected.conditions),
        )
        .await
        {
            Ok(host) => host,
            Err(error) => {
                return Ok(self
                    .abort_before_host(
                        claim,
                        operation,
                        selected,
                        Some(notification),
                        errors::state(error),
                    )
                    .await)
            }
        };
        let completion = Arc::new(CommandCompletion::new(
            self.coordinator.clone(),
            Arc::clone(&host),
            claim,
            operation,
            notification,
            selected.result_read,
            selected.codec,
            selected.memory,
        ));
        Ok(TransactionAdmission::Execute(TransactionExecution {
            host,
            completion,
            cancellation: Some(selected.execution.cancellation()),
        }))
    }

    async fn abort_before_host(
        &self,
        claim: AdmittedCommand,
        operation: ProtectedStoreOperation,
        selected: ExecutionSelection,
        notification: Option<CommandNotificationOwner>,
        error: PlatformError,
    ) -> TransactionAdmission {
        let record = claim.record().clone();
        let retirement = claim.retirement();
        drop(claim);
        operation.retire().await;
        let completion = self
            .coordinator
            .abort_unstarted(
                retirement,
                record,
                selected.result_read,
                error,
                selected.memory,
            )
            .await;
        if let Some(notification) = notification {
            notification.notify_reload();
        }
        TransactionAdmission::Existing(Box::new(completion))
    }
}
enum ClaimDecision {
    New(AdmittedCommand),
    Existing(CommandRecord),
}
fn admission_bytes(input: &AdmissionInput) -> Result<u64, PlatformError> {
    let mut bytes = input.fingerprint.input.bytes.len()
        + latent_core::transaction_contract::METADATA_BYTES
        + 131_072;
    for condition in &input.fingerprint.expected_versions {
        bytes = bytes
            .checked_add(condition.key.len() + 1024)
            .ok_or_else(|| errors::atomic(AtomicError::Limit))?;
    }
    u64::try_from(
        bytes
            .checked_mul(3)
            .ok_or_else(|| errors::atomic(AtomicError::Limit))?,
    )
    .map_err(|_| errors::atomic(AtomicError::Limit))
}
