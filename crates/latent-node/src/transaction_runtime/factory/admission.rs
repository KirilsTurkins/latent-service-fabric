use super::{
    atomic, authorization, error, policy, Arc, AtomicError, CommandRecord, NamespaceCatalog,
    NativeTransactionAdmission, PlatformError, State, StateTransactionHost,
    TransactionAdmissionResult, TransactionSelection,
};
use crate::transaction_runtime::command_role::CommandRole;
use crate::transaction_runtime::observation::{self, Phase};
use crate::transaction_runtime::{CommandHostSelection, StateAuthorization};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{NamespaceAdmission, NamespaceAuthority};
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, CommandAccess, PreparedAdmission, PublishedAdmission,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    ActivationBudget, BoxFuture, StateNamespaceId,
};
use latent_executor::transaction::{TransactionHost, ViewIdentity};
use latent_manifest::TransactionOperationMode;
use latent_policy::capability::OwnedPolicyDecision;
use latent_state::{
    embedded::StoreError,
    namespace::catalog::NamespaceRead,
    session::{StateMode, StateScope},
    store_io::StoreIoKind,
};
enum PendingPublication {
    New(latent_commit::atomic::AdmittedCommand),
    Existing(CommandRecord),
    // A positively completed read/preparation refused before any writer.
    // This is distinct from unknown physical Pending publication.
    Refused(AtomicError),
}

fn source_pin(source: &latent_commit::atomic::SourceIdentity) -> Result<[u8; 32], PlatformError> {
    use sha2::{Digest, Sha256};
    source.validate().map_err(atomic)?;
    let mut hash = Sha256::new();
    hash.update(b"LSF queued command source v1\0");
    for value in [
        &source.publication,
        &source.revision,
        &source.release_digest,
        &source.component_digest,
        &source.contract_digest,
        &source.state_schema,
        &source.input_format,
        &source.result_format,
    ] {
        hash.update((value.len() as u64).to_le_bytes());
        hash.update(value.as_bytes());
    }
    hash.update(source.route_generation.to_le_bytes());
    Ok(hash.finalize().into())
}

struct ClaimNotification<'a>(&'a super::super::entity_queue::EntityQueue);
impl Drop for ClaimNotification<'_> {
    fn drop(&mut self) {
        self.0.claimed();
    }
}

fn entity_queue_error(failure: super::super::entity_queue::QueueError) -> PlatformError {
    use super::super::entity_queue::QueueError;
    use latent_core::PlatformErrorCode as Code;
    use latent_state::entity_lanes::{EntityLaneError, EntityRejection};
    if failure == QueueError::DuplicateConflict {
        return atomic(AtomicError::Conflict);
    }
    let (code, message) = match failure {
        QueueError::Expired
        | QueueError::Lane(EntityLaneError::Expired)
        | QueueError::Rejected(EntityRejection::WaitExpired) => {
            (Code::DeadlineExceeded, "entity-queue-expired")
        }
        QueueError::Rejected(EntityRejection::AuthorityChanged) => {
            (Code::PermissionDenied, "entity-queue-authority-changed")
        }
        QueueError::Rejected(EntityRejection::CancelledBeforeExecution) => {
            (Code::Cancelled, "entity-queue-cancelled")
        }
        QueueError::Lane(EntityLaneError::Backpressure(_)) => {
            (Code::ResourceExhausted, "entity-queue-backpressure")
        }
        QueueError::DuplicateCapacity => (Code::ResourceExhausted, "entity-duplicate-backpressure"),
        QueueError::OriginalOwnerEnded => (Code::Unavailable, "entity-original-owner-ended"),
        _ => (Code::Unavailable, "entity-queue-unavailable"),
    };
    error(code, message)
}

impl crate::TransactionActivationAdmission for NativeTransactionAdmission {
    fn original_command_cancellation(
        &self,
    ) -> Result<Option<crate::transaction_runtime::OriginalCommandCancellation>, PlatformError>
    {
        let state = self.state.lock().map_err(|_| authorization::denied())?;
        match &*state {
            State::Ready(Some(TransactionAdmissionResult::Command { claim, host })) => {
                let original = super::super::cancellation::OriginalCommandCancellation::from_claim(
                    claim, host,
                )?;
                if !super::super::cancellation::CancellationAbortSlot::eligible(
                    &original.identity(),
                    host,
                ) {
                    return Ok(Some(original));
                }
                // The shell is allocated only after the original real ingress
                // metadata/host-memory reservation exists; no separate quota.
                let _prepaid = self.retained_capacity()?;
                let mut shared = self
                    .cancellation_abort
                    .lock()
                    .map_err(|_| authorization::denied())?;
                let slot = shared.get_or_insert_with(Arc::default).clone();
                drop(shared);
                let identity = slot
                    .bind(
                        original.identity(),
                        host,
                        self.owners.policy.clone(),
                        self.owners.namespaces.clone(),
                        self.owners.native.clone(),
                    )
                    .ok()
                    .flatten();
                Ok(Some(match identity {
                    Some(identity) => original.with_abort_slot(&slot, identity),
                    None => original,
                }))
            }
            _ => Ok(None),
        }
    }

    fn requires_prepared_input(&self) -> bool {
        self.validator.is_some()
    }

    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<Arc<dyn TransactionHost>, PlatformError>> {
        Box::pin(async move { self.admit_native(envelope, budget, None).await })
    }

    fn admit_controlled<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
        control: crate::TransactionAdmissionControl,
    ) -> BoxFuture<'a, Result<Arc<dyn TransactionHost>, PlatformError>> {
        Box::pin(async move { self.admit_native(envelope, budget, Some(control)).await })
    }

    fn complete(
        &self,
        outcome: latent_activation::ActivationOutcome,
        control: crate::TransactionCommitControl,
    ) -> BoxFuture<'_, latent_activation::ActivationOutcome> {
        Box::pin(self.complete_native(outcome, control))
    }
}
impl NativeTransactionAdmission {
    #[expect(
        clippy::too_many_lines,
        reason = "Keep the original source, capacity, queue and durable admission fences in their execution order"
    )]
    async fn admit_native(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        control: Option<crate::TransactionAdmissionControl>,
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
        let source = observation::platform(Phase::Source, self.installation.source(envelope))?;
        let selected_source = if selection.mode == TransactionOperationMode::StrictCommand
            && selection.entity.is_some()
            && selection.retry.is_none()
        {
            source_pin(&source)?
        } else {
            [0; 32]
        };
        let initial = observation::platform(
            Phase::InitialPolicy,
            policy::initial(
                &self.owners,
                &self.installation,
                &selection,
                envelope,
                budget,
            ),
        )?;
        let retention =
            observation::platform(Phase::Retention, self.reserve_retention(envelope, budget))?;
        let bytes = retention.request_bytes();
        *self.retention.lock().map_err(|_| authorization::denied())? = Some(Arc::clone(&retention));
        let mut claim_changes = None;
        let mut replay_probe = None;
        if selection.mode == TransactionOperationMode::StrictCommand
            && selection.entity.is_some()
            && selection.retry.is_none()
        {
            // Subscribe before the lookup so a claim published between the
            // snapshot and queue registration cannot be missed.
            claim_changes = Some(self.owners.lanes.claim_changes());
            let read = self.replay_existing_entity(&selection, envelope, budget);
            replay_probe = Some(match control.as_ref() {
                Some(control) => control.wait(read).await?,
                None => read.await?,
            });
        }
        // Pending command publication updates the namespace generation. Wait
        // before that write, then read and seal a fresh namespace. Duplicates
        // still use the ordinary durable admission/replay path after selection.
        let lane = if selection.mode == TransactionOperationMode::StrictCommand {
            self.acquire_entity_lane(
                &selection,
                envelope,
                budget,
                control.as_ref(),
                claim_changes,
                replay_probe,
                selected_source,
            )
            .await?
        } else {
            None
        };
        let namespace = observation::platform(
            Phase::NamespaceRead,
            self.read_namespace(&selection, &envelope.target.tenant)
                .await,
        )?;
        check_view(
            &selection,
            &namespace,
            &self.installation.declaration.state_schema,
        )?;
        let before = observation::platform(
            Phase::InitialSeal,
            self.seal(initial.before, namespace, envelope, budget, None),
        )?;
        let mode = selection.mode == TransactionOperationMode::StrictCommand;
        self.retain_response_authority(Arc::clone(&before), !mode)?;
        let scope = selected_scope(&selection, envelope, &source.state_schema);
        let mut _claim_notification = None;
        let authorization = if mode {
            let role = CommandRole::capture(&self.owners.command).map_err(atomic)?;
            if let Some(lane) = lane {
                role.bind_lane(lane).map_err(atomic)?;
            }
            let epoch = role.epoch();
            *self.state.lock().map_err(|_| authorization::denied())? = State::Pending {
                claim: None,
                role: Arc::clone(&role),
                conflict: None,
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
            if selection.entity.is_some() {
                _claim_notification = Some(ClaimNotification(&self.owners.lanes));
            }
            observation::platform(
                Phase::PendingPublication,
                self.publish_pending(
                    input,
                    selection.retry.take(),
                    Arc::clone(&before),
                    Arc::clone(&role),
                    bytes,
                )
                .await,
            )?;
            let after = self
                .read_namespace(&selection, &envelope.target.tenant)
                .await?;
            let authorization = observation::platform(
                Phase::FinalSeal,
                self.seal(initial.after, after, envelope, budget, Some(role)),
            )?;
            authorization.authorize("info", 0, 0, || Ok(()))?;
            authorization
        } else {
            drop(initial.after);
            before
        };
        self.retain_response_authority(Arc::clone(&authorization), !mode)?;
        observation::platform(
            Phase::HostOpen,
            self.open_host(envelope, selection, scope, authorization)
                .await,
        )
    }

    #[expect(
        clippy::too_many_arguments,
        clippy::too_many_lines,
        reason = "Keep the original budget, control, claim observation, and selected source together"
    )]
    async fn acquire_entity_lane(
        &self,
        selection: &TransactionSelection,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        control: Option<&crate::TransactionAdmissionControl>,
        mut claims: Option<tokio::sync::watch::Receiver<u64>>,
        probe: Option<super::entity_replay::ReplayProbe>,
        selected_source: [u8; 32],
    ) -> Result<Option<super::super::entity_queue::Physical>, PlatformError> {
        use latent_core::native_capacity::NativeBufferClass;
        use latent_state::entity_lanes::EntityScope;

        let Some(entity) = selection.entity.as_ref() else {
            return Ok(None);
        };
        let retained = self.retained_capacity()?;
        let scope = EntityScope::new(
            envelope.target.tenant.clone(),
            StateNamespaceId(selection.namespace.clone()),
            selection.incarnation,
            latent_core::EntityKey(entity.clone()),
        )
        .map_err(|_| authorization::denied())?;
        let deadline = budget
            .deadline()
            .monotonic()
            .ok_or_else(authorization::denied)?;
        let current_retention = Arc::clone(&retained);
        let current = Arc::new(move || current_retention.check_current().is_ok());
        let retained_bytes = retained.total_native_bytes()?;
        let command = probe.map(|probe| {
            (
                probe.identity,
                probe.fingerprint,
                selected_source,
                self.shared_owner.clone(),
            )
        });
        let wait = async {
            let mut duplicate_authorized = false;
            let mut first_owner = None;
            loop {
                // Each waiter and its queue objects are prepaid from the
                // original ingress; reacquire after the authorization read.
                let permit = retained
                    .native()
                    .reserve_buffer(NativeBufferClass::Request, 16 * 1024)
                    .map_err(|_| {
                        error(
                            latent_core::PlatformErrorCode::ResourceExhausted,
                            "entity-queue-capacity",
                        )
                    })?;
                let result = self
                    .owners
                    .lanes
                    .acquire_for_command(
                        scope.clone(),
                        envelope.activation_id.0.as_bytes().to_vec(),
                        retained_bytes,
                        deadline,
                        current.clone(),
                        permit,
                        command.clone(),
                        duplicate_authorized,
                        first_owner,
                    )
                    .await;
                if let Err(super::super::entity_queue::QueueError::DuplicateNeedsAuthorization {
                    source,
                    owner,
                    wait_until,
                }) = &result
                {
                    let source = *source;
                    let owner = *owner;
                    let wait_until = *wait_until;
                    // Authorization is itself part of waiting for the first
                    // owner. Prepay and count it before starting the bounded
                    // read, and keep that charge until the waiter is dropped.
                    let waiter_permit = retained
                        .native()
                        .reserve_buffer(NativeBufferClass::Request, 16 * 1024)
                        .map_err(|_| {
                            error(
                                latent_core::PlatformErrorCode::ResourceExhausted,
                                "entity-queue-capacity",
                            )
                        })?;
                    let waiter = self
                        .owners
                        .lanes
                        .reserve_authorizing_duplicate(&scope)
                        .map_err(entity_queue_error)?;
                    let authorized = self.authorize_entity_duplicate(selection, envelope, budget);
                    tokio::select! {
                        result = authorized => result?,
                        () = self.owners.lanes.wait_for_waiter_expiry(wait_until) => {
                            return Err(entity_queue_error(super::super::entity_queue::QueueError::Expired));
                        }
                    }
                    drop(waiter);
                    drop(waiter_permit);
                    first_owner = Some((owner, source, wait_until));
                    duplicate_authorized = true;
                    continue;
                }
                if matches!(
                    result,
                    Err(super::super::entity_queue::QueueError::OriginalOwnerEnded)
                ) {
                    // Recover a durable claim if it became visible just before
                    // the original lane retired; otherwise refuse takeover.
                    self.replay_existing_entity(selection, envelope, budget)
                        .await?;
                }
                break result.map_err(entity_queue_error);
            }
        };
        tokio::pin!(wait);
        loop {
            let next = async {
                if let Some(changes) = claims.as_mut() {
                    tokio::select! {
                        result = &mut wait => result.map(Some),
                        changed = changes.changed() => changed
                            .map(|()| None)
                            .map_err(|_| error(latent_core::PlatformErrorCode::Unavailable, "entity-queue-unavailable")),
                    }
                } else {
                    (&mut wait).await.map(Some)
                }
            };
            let next = match control {
                Some(control) => control.wait(next).await?,
                None => next.await?,
            };
            if let Some(lane) = next {
                return Ok(Some(lane));
            }
            // The read job keeps its own physical owner after waiter loss. A
            // cancellation or a duplicate result drops the queued reservation.
            let read = self.replay_existing_entity(selection, envelope, budget);
            match control {
                Some(control) => control.wait(read).await?,
                None => read.await?,
            };
        }
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
            Arc::clone(&authorization),
            envelope.activation_id.clone(),
            scope,
            command,
            mode.then(|| self.owners.effects.clone()),
            Arc::clone(&self.owners.time),
            selection.expected_versions,
            selection.minimum_view_version,
        )
        .await
        .map_err(|failure| {
            if failure == latent_executor::transaction::StateFailure::Conflict {
                self.record_pre_host_conflict(&authorization, envelope);
            }
            error(
                match failure {
                    latent_executor::transaction::StateFailure::Conflict => {
                        latent_core::PlatformErrorCode::StateConflict
                    }
                    latent_executor::transaction::StateFailure::PermissionDenied => {
                        latent_core::PlatformErrorCode::PermissionDenied
                    }
                    _ => latent_core::PlatformErrorCode::Unavailable,
                },
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

    pub(super) async fn read_namespace(
        &self,
        selection: &TransactionSelection,
        tenant: &latent_core::TenantId,
    ) -> Result<NamespaceRead, PlatformError> {
        let tenant = tenant.clone();
        let namespace = StateNamespaceId(selection.namespace.clone());
        let retention = self.retained_capacity()?;
        let result = self
            .owners
            .store
            .with_store_retaining(StoreIoKind::Read, 8192, retention, move |store| {
                let view = store.snapshot()?;
                match latent_state::recovery::require_ready(&view) {
                    Ok(()) => {}
                    Err(latent_state::embedded::StoreError::Unavailable) => {
                        return Ok(Err(
                            latent_state::namespace::NamespaceError::RecoveryRequired,
                        ));
                    }
                    Err(error) => return Err(error),
                }
                Ok(NamespaceCatalog::read_in(&view, &tenant, &namespace))
            })
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?
            .await
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?
            .map_err(|_| atomic(latent_commit::atomic::AtomicError::RecoveryRequired))?;
        result
            .map_err(|failure| match failure {
                latent_state::namespace::NamespaceError::RecoveryRequired => {
                    atomic(AtomicError::RecoveryRequired)
                }
                _ => authorization::denied(),
            })?
            .ok_or_else(authorization::denied)
    }
    pub(super) fn seal(
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
        let authorization = authorization.with_retention(self.retained_capacity()?);
        let authorization = match role {
            Some(role) => authorization.with_command_role(role),
            None => authorization,
        };
        Ok(Arc::new(authorization))
    }

    async fn publish_pending(
        &self,
        input: AdmissionInput,
        retry: Option<super::TransactionRetrySelection>,
        authorization: Arc<StateAuthorization>,
        role: Arc<CommandRole>,
        bytes: u64,
    ) -> Result<(), PlatformError> {
        let retained_role = Arc::clone(&role);
        let time = role.captured_time();
        let keeper: Arc<dyn std::any::Any + Send + Sync> =
            Arc::new((Arc::clone(&authorization), Arc::clone(&role)));
        let job = self.owners.store.with_store_retaining(
            StoreIoKind::Write,
            bytes,
            keeper,
            move |store| {
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
                    observation::platform(
                        Phase::PendingAuthorization,
                        authorization.authorize(operation, 0, 0, || Ok(())),
                    )
                    .map_err(|_| AtomicError::PermissionDenied)
                };
                let first_attempt = retry.is_none();
                let mut retained_input = Some(input);
                let prepared = if let Some(retry) = retry.as_ref() {
                    authorize(CommandAccess::Admit, None).and_then(|()| {
                        let input = retained_input.as_ref().ok_or(AtomicError::Invalid)?;
                        super::retry::check_association(&view, input, retry)?;
                        PreparedAdmission::retry(&view, input, &retry.request, time, &authorize)
                    })
                } else {
                    match retained_input.take() {
                        Some(input) => PreparedAdmission::prepare(&view, input, time, &authorize),
                        None => Err(AtomicError::Invalid),
                    }
                };
                let prepared = observation::atomic(Phase::PendingPreparation, prepared);
                // A CAS loser may take one fresh view to inspect the winning
                // command. Retire the original planning view first.
                drop(view);
                let result = match prepared {
                    Ok(AdmissionDecision::New(prepared)) => {
                        let expected = authorization.namespace.expectation();
                        if !prepared
                            .batch()
                            .expectations
                            .iter()
                            .any(|row| row.key == expected.key && row.value == expected.value)
                        {
                            return Ok(Ok(PendingPublication::Refused(AtomicError::Conflict)));
                        }
                        let final_accept = || {
                            retained_role.with_current(|_| {
                                authorization
                                    .authorize("commit", 0, 0, || Ok(()))
                                    .map_err(|_| AtomicError::PermissionDenied)
                            })
                        };
                        if first_attempt {
                            prepared
                                .publish_or_existing(
                                    store,
                                    || {
                                        retained_role.with_current(|now| {
                                            Ok(super::super::command_role::command_time(now))
                                        })
                                    },
                                    final_accept,
                                    &authorize,
                                )
                                .map(|result| match result {
                                    PublishedAdmission::New(claim) => {
                                        PendingPublication::New(claim)
                                    }
                                    PublishedAdmission::Existing(record) => {
                                        PendingPublication::Existing(record)
                                    }
                                })
                        } else if let (Some(retry), Some(input)) =
                            (retry.as_ref(), retained_input.as_ref())
                        {
                            prepared
                                .publish_retry_or_existing(
                                    store,
                                    input,
                                    &retry.request,
                                    || {
                                        retained_role.with_current(|now| {
                                            Ok(super::super::command_role::command_time(now))
                                        })
                                    },
                                    final_accept,
                                    &authorize,
                                )
                                .map(|result| match result {
                                    PublishedAdmission::New(claim) => {
                                        PendingPublication::New(claim)
                                    }
                                    PublishedAdmission::Existing(record) => {
                                        PendingPublication::Existing(record)
                                    }
                                })
                        } else {
                            Err(AtomicError::Invalid)
                        }
                    }
                    Ok(AdmissionDecision::Existing(record)) => {
                        Ok(PendingPublication::Existing(record))
                    }
                    Err(AtomicError::Corrupt) => {
                        // The planning view is retired and no writer or guest
                        // was accepted. Release this contender's role before
                        // the protected store quarantines its physical worker.
                        retained_role
                            .retire()
                            .map_err(|_| StoreError::CommitUncertain)?;
                        return Err(StoreError::Corrupt);
                    }
                    Err(error) => Ok(PendingPublication::Refused(error)),
                };
                match result {
                    Err(AtomicError::Corrupt) => {
                        // Corrupt is a known noncommitted engine result;
                        // uncertain commits use RecoveryRequired instead.
                        retained_role
                            .retire()
                            .map_err(|_| StoreError::CommitUncertain)?;
                        Err(StoreError::Corrupt)
                    }
                    other => Ok(other),
                }
            },
        );
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
        self.record_pending_publication(role, result)
    }

    fn record_pending_publication(
        &self,
        role: Arc<CommandRole>,
        result: Result<PendingPublication, AtomicError>,
    ) -> Result<(), PlatformError> {
        let mut state = self.state.lock().map_err(|_| authorization::denied())?;
        match result {
            Ok(PendingPublication::New(claim)) => {
                *state = State::Pending {
                    claim: Some(claim),
                    role,
                    conflict: None,
                };
                Ok(())
            }
            Ok(PendingPublication::Existing(record)) => {
                role.retire().map_err(atomic)?;
                *state = State::Ready(Some(TransactionAdmissionResult::Existing {
                    command: record,
                    retained: self.retained_capacity()?,
                }));
                Err(error(
                    latent_core::PlatformErrorCode::AlreadyExists,
                    "transaction-already-admitted",
                ))
            }
            Ok(PendingPublication::Refused(reason)) => {
                // The actual worker completed without accepting any writer or
                // guest. Retire only this contender's new role, preserving the
                // legitimate owner and all existing durable command history.
                role.retire().map_err(atomic)?;
                *state = State::Failed;
                Err(atomic(reason))
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
pub(super) fn check_view(
    selection: &TransactionSelection,
    namespace: &NamespaceRead,
    schema: &str,
) -> Result<(), PlatformError> {
    let record = namespace.record();
    if record.version.incarnation != selection.incarnation || record.state_schema != schema {
        return Err(authorization::denied());
    }
    Ok(())
}
