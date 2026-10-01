use super::{
    atomic, authorization, error, policy, Arc, AtomicError, CommandRecord, NamespaceCatalog,
    NativeTransactionAdmission, PlatformError, State, StateTransactionHost,
    TransactionAdmissionResult, TransactionSelection,
};
use crate::transaction_runtime::command_role::CommandRole;
use crate::transaction_runtime::{CommandHostSelection, StateAuthorization};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{NamespaceAdmission, NamespaceAuthority};
use latent_commit::atomic::{AdmissionDecision, AdmissionInput, CommandAccess, PreparedAdmission};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    ActivationBudget, BoxFuture, StateNamespaceId,
};
use latent_executor::transaction::{TransactionHost, ViewIdentity};
use latent_manifest::TransactionOperationMode;
use latent_policy::capability::OwnedPolicyDecision;
use latent_state::{
    namespace::catalog::NamespaceRead,
    session::{StateMode, StateScope},
    store_io::StoreIoKind,
};
enum PendingPublication {
    New(latent_commit::atomic::AdmittedCommand),
    Existing(CommandRecord),
}

impl crate::TransactionActivationAdmission for NativeTransactionAdmission {
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<Arc<dyn TransactionHost>, PlatformError>> {
        Box::pin(async move { self.admit_native(envelope, budget).await })
    }
}
impl NativeTransactionAdmission {
    async fn admit_native(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<Arc<dyn TransactionHost>, PlatformError> {
        let mut selection = {
            let mut state = self.state.lock().map_err(|_| authorization::denied())?;
            let State::Fresh(selection) = &mut *state else {
                return Err(authorization::denied());
            };
            let selection = selection.take().ok_or_else(authorization::denied)?;
            *state = State::Failed;
            selection
        };
        // Verify pinned source, mode, finite input and original policy BEFORE
        // any native lookup or durable reservation. DTOs supply no source grant.
        let source = self.installation.source(envelope)?;
        let initial = policy::initial(
            &self.owners,
            &self.installation,
            &selection,
            envelope,
            budget,
        )?;
        let bytes = u64::try_from(envelope.input.capacity())
            .map_err(|_| authorization::denied())?
            .checked_mul(2)
            .and_then(|bytes| bytes.checked_add(2 * 1024 * 1024))
            .ok_or_else(authorization::denied)?;
        let _metadata = budget
            .reserve_host_memory(bytes)
            .map_err(|error| error.to_platform_error())?;
        let namespace = self
            .read_namespace(&selection, &envelope.target.tenant)
            .await?;
        check_view(
            &selection,
            &namespace,
            &self.installation.declaration.state_schema,
        )?;
        let before = self.seal(initial.before, namespace, envelope, budget, None)?;
        let mode = selection.mode == TransactionOperationMode::StrictCommand;
        let scope = selected_scope(&selection, envelope, &source.state_schema);
        let authorization = if mode {
            let role = CommandRole::capture(&self.owners.command).map_err(atomic)?;
            let epoch = role.epoch();
            *self.state.lock().map_err(|_| authorization::denied())? = State::Pending {
                claim: None,
                role: Arc::clone(&role),
            };
            let input = AdmissionInput {
                key: CommandKey {
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
                },
                fingerprint: CommandFingerprint {
                    input_format: selection.input_format.clone(),
                    input: Value {
                        bytes: envelope.input.clone(),
                        media_type: envelope.input_media_type.clone(),
                        metadata: envelope
                            .metadata
                            .iter()
                            .map(|(key, value)| (key.clone(), value.clone()))
                            .collect(),
                    },
                    expected_versions: selection.expected_versions.clone(),
                },
                source,
                result_read_policy: self.installation.result_read_policy.clone(),
                result_policy: self.installation.result_policy,
                inbox: None,
                owner_epoch: epoch,
            };
            self.publish_pending(
                input,
                selection.retry.take(),
                Arc::clone(&before),
                Arc::clone(&role),
                bytes,
            )
            .await?;
            let after = self
                .read_namespace(&selection, &envelope.target.tenant)
                .await?;
            self.seal(initial.after, after, envelope, budget, Some(role))?
        } else {
            drop(initial.after);
            before
        };
        self.open_host(envelope, selection, scope, authorization)
            .await
    }

    async fn open_host(
        &self,
        envelope: &ActivationEnvelope,
        selection: TransactionSelection,
        scope: StateScope,
        authorization: Arc<StateAuthorization>,
    ) -> Result<Arc<dyn TransactionHost>, PlatformError> {
        let mode = scope.mode == StateMode::Command;
        let command = if mode {
            let state = self.state.lock().map_err(|_| authorization::denied())?;
            let State::Pending {
                claim: Some(claim), ..
            } = &*state
            else {
                return Err(authorization::denied());
            };
            Some(
                CommandHostSelection::from_claim(
                    claim,
                    ViewIdentity {
                        namespace: scope.namespace.0.clone(),
                        incarnation: scope.incarnation.to_string(),
                        version: Vec::new(),
                        state_schema: scope.state_schema.clone(),
                    },
                )
                .map_err(atomic)?,
            )
        } else {
            None
        };
        let host = StateTransactionHost::open(
            Arc::clone(&self.owners.store),
            authorization,
            envelope.activation_id.clone(),
            scope,
            command,
            mode.then(|| self.owners.effects.clone()),
            Arc::clone(&self.owners.time),
            selection.expected_versions,
        )
        .await
        .map_err(|_| {
            error(
                latent_core::PlatformErrorCode::Unavailable,
                "transaction-host-unavailable",
            )
        })?;
        let result = if mode {
            let mut state = self.state.lock().map_err(|_| authorization::denied())?;
            let State::Pending { claim, .. } = &mut *state else {
                return Err(authorization::denied());
            };
            TransactionAdmissionResult::Command {
                claim: claim.take().ok_or_else(authorization::denied)?,
                host: Arc::clone(&host),
            }
        } else {
            TransactionAdmissionResult::Query {
                host: Arc::clone(&host),
            }
        };
        *self.state.lock().map_err(|_| authorization::denied())? = State::Ready(Some(result));
        Ok(host)
    }

    async fn read_namespace(
        &self,
        selection: &TransactionSelection,
        tenant: &latent_core::TenantId,
    ) -> Result<NamespaceRead, PlatformError> {
        let tenant = tenant.clone();
        let namespace = StateNamespaceId(selection.namespace.clone());
        let result = self
            .owners
            .store
            .with_store(StoreIoKind::Read, 8192, move |store| {
                let view = store.snapshot()?;
                Ok(NamespaceCatalog::read_in(&view, &tenant, &namespace))
            })
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?
            .await
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?;
        result
            .map_err(|_| authorization::denied())?
            .ok_or_else(authorization::denied)
    }
    fn seal(
        &self,
        initial: OwnedPolicyDecision,
        namespace: NamespaceRead,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        role: Option<Arc<CommandRole>>,
    ) -> Result<Arc<StateAuthorization>, PlatformError> {
        let lifecycle = self
            .owners
            .namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| authorization::denied())?;
        let authority = Arc::new(NamespaceAuthority::seal_retained(
            &self.owners.policy,
            initial,
            &namespace,
            NamespaceAdmission {
                activation: envelope.activation_id.clone(),
                deadline: budget
                    .deadline()
                    .monotonic()
                    .ok_or_else(authorization::denied)?,
                recovery: &self.installation.recovery,
                state_schema: &self.installation.declaration.state_schema,
            },
            lifecycle,
        )?);
        let authorization = StateAuthorization::new(
            Arc::clone(&self.owners.policy),
            authority,
            namespace,
            envelope.principal.clone(),
            envelope.target.service.0.clone(),
            self.installation.publication.clone(),
            Arc::clone(&self.installation.state),
            self.installation.intents.clone(),
            budget.clone(),
        )?;
        let authorization = match role {
            Some(role) => authorization.with_command_role(role),
            None => authorization,
        };
        Ok(Arc::new(authorization))
    }

    async fn publish_pending(
        &self,
        input: AdmissionInput,
        retry: Option<latent_commit::atomic::RetryRequest>,
        authorization: Arc<StateAuthorization>,
        role: Arc<CommandRole>,
        bytes: u64,
    ) -> Result<(), PlatformError> {
        let retained_role = Arc::clone(&role);
        let time = role.captured_time();
        let job = self
            .owners
            .store
            .with_store(StoreIoKind::Write, bytes, move |store| {
                let view = store.snapshot()?;
                let authorize = |access: CommandAccess, previous: Option<&CommandRecord>| {
                    let operation = if access == CommandAccess::Replay {
                        "read-result"
                    } else {
                        "commit"
                    };
                    if previous.is_some_and(|record| {
                        record.result_read_policy()
                            != authorization.authority.ownership().result_policy
                    }) {
                        return Err(AtomicError::PermissionDenied);
                    }
                    authorization
                        .authorize(operation, 0, 0, || Ok(()))
                        .map_err(|_| AtomicError::PermissionDenied)
                };
                let prepared = if let Some(retry) = retry {
                    PreparedAdmission::retry(&view, &input, &retry, time, authorize)
                } else {
                    PreparedAdmission::prepare(&view, input, time, authorize)
                };
                Ok(match prepared {
                    Ok(AdmissionDecision::New(prepared)) => {
                        let expected = authorization.namespace.expectation();
                        if !prepared
                            .batch()
                            .expectations
                            .iter()
                            .any(|row| row.key == expected.key && row.value == expected.value)
                        {
                            return Ok(Err(AtomicError::Conflict));
                        }
                        prepared
                            .publish(store, || {
                                retained_role.with_current(|_| {
                                    authorization
                                        .authorize("commit", 0, 0, || Ok(()))
                                        .map_err(|_| AtomicError::PermissionDenied)
                                })
                            })
                            .map(PendingPublication::New)
                    }
                    Ok(AdmissionDecision::Existing(record)) => {
                        Ok(PendingPublication::Existing(record))
                    }
                    Err(error) => Err(error),
                })
            });
        let Ok(job) = job else {
            // No native operation was accepted; the copied input is gone.
            role.retire().map_err(atomic)?;
            *self.state.lock().map_err(|_| authorization::denied())? = State::Failed;
            return Err(atomic(AtomicError::Unavailable));
        };
        let result = job
            .await
            .map_err(|_| atomic(AtomicError::RecoveryRequired))?
            .map_err(|_| atomic(AtomicError::RecoveryRequired))?;
        let mut state = self.state.lock().map_err(|_| authorization::denied())?;
        match result {
            Ok(PendingPublication::New(claim)) => {
                *state = State::Pending {
                    claim: Some(claim),
                    role,
                };
                Ok(())
            }
            Ok(PendingPublication::Existing(record)) => {
                role.retire().map_err(atomic)?;
                *state = State::Ready(Some(TransactionAdmissionResult::Existing(record)));
                Err(error(
                    latent_core::PlatformErrorCode::AlreadyExists,
                    "transaction-already-admitted",
                ))
            }
            Err(reason) => {
                if !matches!(
                    reason,
                    AtomicError::RecoveryRequired | AtomicError::Unavailable
                ) {
                    // Actual worker completion plus a known non-accepted writer
                    // result proves there was no command/native owner to retain.
                    role.retire().map_err(atomic)?;
                    *state = State::Failed;
                }
                Err(atomic(reason))
            }
        }
    }
}
fn selected_scope(
    selection: &TransactionSelection,
    envelope: &ActivationEnvelope,
    state_schema: &str,
) -> StateScope {
    StateScope {
        tenant: envelope.target.tenant.clone(),
        namespace: StateNamespaceId(selection.namespace.clone()),
        incarnation: selection.incarnation,
        entity: selection.entity.clone(),
        state_schema: state_schema.to_owned(),
        mode: if selection.mode == TransactionOperationMode::StrictCommand {
            StateMode::Command
        } else {
            StateMode::Query
        },
    }
}
fn check_view(
    selection: &TransactionSelection,
    namespace: &NamespaceRead,
    schema: &str,
) -> Result<(), PlatformError> {
    let record = namespace.record();
    if record.version.incarnation != selection.incarnation || record.state_schema != schema {
        return Err(authorization::denied());
    }
    if let Some(minimum) = &selection.minimum_view_version {
        let incarnation = u64::from_le_bytes(
            minimum[..8]
                .try_into()
                .map_err(|_| authorization::denied())?,
        );
        let generation = u64::from_le_bytes(
            minimum[8..]
                .try_into()
                .map_err(|_| authorization::denied())?,
        );
        if incarnation != record.version.incarnation
            || generation == 0
            || generation > record.version.generation
        {
            return Err(error(
                latent_core::PlatformErrorCode::StateConflict,
                "query-view-unavailable",
            ));
        }
    }
    Ok(())
}
