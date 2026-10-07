//! One explicit management mutation over the original recovery storage worker.
use super::{
    audit, authorization::Access, c, denied, expired, inspection, invalid, io_error,
    namespace_error, protected_error, response, state_receipt, unsupported, Arc, Inner, Instant,
    NamespaceCatalog, OwnedPhase4Response, PlatformError, PlatformErrorCode,
    StateManagementReservation, WORK_BYTES,
};
use latent_audit::{AuditOperationResult, AuditReason};
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_commit::atomic::{AtomicError, FloorReleaseRequest, Identity};
use latent_policy::capability::ResourceTarget;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, Family, RowKey, RowMutation, StoreError},
    namespace::catalog::{NamespaceOperationContext, NamespaceRead},
    session::{version::ViewIdentity, StateScope},
    store_io::StoreIoKind,
};
use prost::Message;
use sha2::{Digest, Sha256};

pub(super) async fn mutate(
    inner: Arc<Inner>,
    request: Box<c::MutateStateRequest>,
    access: Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    if request.mutation != c::StateMutationKind::ReleaseExpiredCommandFloor as i32 {
        return Err(unsupported());
    }
    let worker = Arc::clone(&inner);
    let retained = Arc::clone(&permit);
    let job = inner
        .services
        .store
        .with_store(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES as u64,
            move |engine| {
                let mut pending = pending;
                let result = write(
                    &worker,
                    engine,
                    &request,
                    &access,
                    retained.as_ref(),
                    deadline,
                    &mut pending,
                );
                let (disposition, reason, digest, replayed) = match &result {
                    Ok(Ok((_, receipt, replayed))) => (
                        AuditOperationResult::Committed,
                        AuditReason::Committed,
                        Some(Sha256::digest(receipt.encode()?).into()),
                        *replayed,
                    ),
                    Ok(Err(_)) => (
                        AuditOperationResult::Rejected,
                        AuditReason::Rejected,
                        None,
                        false,
                    ),
                    Err(StoreError::CommitUncertain | StoreError::Unavailable) => (
                        AuditOperationResult::Unknown,
                        AuditReason::MutationUncertain,
                        None,
                        false,
                    ),
                    Err(_) => (
                        AuditOperationResult::NotStarted,
                        AuditReason::NotStarted,
                        None,
                        false,
                    ),
                };
                let finish = pending.finish(disposition, reason, digest, replayed);
                Ok((result, access.inspect, finish, retained))
            },
        )
        .map_err(protected_error)?;
    let (result, decision, finish, worker_permit) =
        job.await.map_err(io_error)?.map_err(protected_error)?;
    // Retire the durable audit attempt on rejected/native-error paths as well.
    // Returning early would leave the original critical slot pending when the
    // caller immediately makes its next authenticated request.
    let ack = audit::ack(finish).await;
    let (read, receipt, replayed) = result.map_err(|error| {
        protected_error(latent_state::protected_store::ProtectedStoreError::Store(
            error,
        ))
    })??;
    response::owned(
        inner,
        worker_permit,
        decision,
        read,
        None,
        deadline,
        c::MutateStateResponse {
            receipt: Some(receipt.public),
            audit_ack: Some(ack),
            replayed,
        }
        .into(),
    )
}

fn write(
    inner: &Inner,
    engine: &EmbeddedStore,
    request: &c::MutateStateRequest,
    access: &Access,
    permit: &dyn StateManagementReservation,
    deadline: Instant,
    pending: &mut audit::Pending,
) -> Result<Result<(NamespaceRead, state_receipt::Receipt, bool), PlatformError>, StoreError> {
    if let Err(error) = inspection::before_lookup(inner, access, deadline, permit) {
        return Ok(Err(error));
    }
    let view = engine.snapshot()?;
    let Some(read) = inspection::read_in(&view, access).map_err(inspection::native_namespace)?
    else {
        return Ok(Err(super::missing()));
    };
    if let Err(error) = inspection::inspection_gate(inner, access, &read, None) {
        return Ok(Err(error));
    }
    let context = operation_context(access, request);
    if let Some(receipt) = state_receipt::read(&view, &context)? {
        if receipt.request.encode_to_vec() != request.encode_to_vec() {
            return Ok(Err(conflict()));
        }
        return Ok(Ok((read, receipt, true)));
    }
    if NamespaceCatalog::outcome_in(&view, &context)
        .map_err(inspection::native_namespace)?
        .is_some()
    {
        return Ok(Err(conflict()));
    }
    if inspection::namespace_view(&view, read.record())? != request.expected_version {
        return Ok(Err(conflict()));
    }
    let scope = StateScope {
        tenant: read.record().tenant.clone(),
        namespace: read.record().id.clone(),
        incarnation: read.record().version.incarnation,
        state_schema: read.record().state_schema.clone(),
        entity: None,
        mode: latent_state::session::StateMode::Query,
    };
    let mut version = ViewIdentity::from_token(&scope, &request.expected_version)
        .map_err(|_| StoreError::Corrupt)?;
    let command = Identity::parse_hex(request.record_id.as_deref().ok_or(StoreError::Invalid)?)
        .map_err(|_| StoreError::Invalid)?;
    let clock = match inner.services.maintenance_clock.sample() {
        Ok(clock) => clock,
        Err(error) => return Ok(Err(error)),
    };
    let mut prepared = match inner.services.maintenance.prepare_floor_release(
        &view,
        &FloorReleaseRequest {
            tenant: scope.tenant.clone(),
            namespace: scope.namespace.clone(),
            expected: read.record().version,
            command,
        },
        clock,
    ) {
        Ok(prepared) => prepared,
        Err(error) => return Ok(Err(atomic_error(error))),
    };
    if prepared.before() != read.record() {
        return Ok(Err(conflict()));
    }
    version.namespace = prepared.after().version;
    let after_version = version.token(&scope).map_err(|_| StoreError::Corrupt)?;
    let receipt = state_receipt::Receipt::new(
        request.clone(),
        context.actor.clone(),
        prepared.after().clone(),
        after_version,
        clock.time.unix_millis,
    )?;
    let row = state_receipt::key(&context);
    let namespace_operation = latent_state::namespace::namespace_operation_key(
        &context.tenant,
        &context.actor,
        &context.operation_id,
    )
    .map_err(inspection::native_namespace)?;
    prepared
        .append_management_batch(AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: row.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: RowKey {
                        family: Family::Namespace,
                        key: namespace_operation,
                    },
                    value: None,
                },
            ],
            mutations: vec![RowMutation {
                key: row,
                value: Some(receipt.encode()?),
            }],
        })
        .map_err(|_| StoreError::Capacity)?;
    // Native reclamation refuses physically live views before policy acceptance.
    drop(view);
    if let Err(error) = pending.started() {
        return Ok(Err(error));
    }
    let mutation = access.mutation.as_ref().ok_or(StoreError::Invalid)?;
    let mut completion = None;
    let mut rejected = None;
    let committed = prepared.publish(engine, |before, after, _| {
        let result = inner.services.policy.with_retained_decisions(
            &[mutation, &access.inspect],
            &mut |inputs| {
                for (input, operation) in inputs
                    .iter()
                    .zip(["namespace-destroy", "namespace-inspect"])
                {
                    let ResourceTarget::State {
                        namespace,
                        incarnation,
                        entity,
                        recovery_kind,
                        recovery_scope,
                        result_policy,
                    } = input.resource
                    else {
                        return Err(denied());
                    };
                    if input.capability != STATE_CONTRACT
                        || input.operation != operation
                        || input.principal.tenant.as_ref() != Some(&before.tenant)
                        || CallerScope::derive(input.principal, &RecoverySelection::OriginalCaller)?
                            != access.caller
                        || input.publication != access.binding.publication.id.as_str()
                        || namespace != before.id.0
                        || incarnation != before.version.incarnation
                        || entity.is_some()
                        || recovery_kind != access.caller.kind
                        || recovery_scope != access.caller.scope
                        || result_policy != access.binding.result_policy
                    {
                        return Err(denied());
                    }
                }
                let transition = inner
                    .services
                    .namespaces
                    .lifecycle()
                    .begin_transition_with(&read, after, true, || {
                        if inner.services.clock.monotonic_now() >= deadline {
                            return Err(latent_state::namespace::NamespaceError::Cancelled);
                        }
                        let current = inner
                            .services
                            .maintenance_clock
                            .sample()
                            .map_err(|_| latent_state::namespace::NamespaceError::Cancelled)?;
                        if !current.time.continuity_proven
                            || current.boot != clock.boot
                            || current.monotonic_millis < clock.monotonic_millis
                            || current.time.unix_millis < clock.time.unix_millis
                        {
                            return Err(latent_state::namespace::NamespaceError::Cancelled);
                        }
                        permit
                            .with_live(&mut || {})
                            .map_err(|_| latent_state::namespace::NamespaceError::Cancelled)
                    })
                    .map_err(namespace_error)?;
                completion = Some(transition);
                Ok(())
            },
        );
        result.map_err(|error| {
            rejected = Some(error);
            AtomicError::PermissionDenied
        })
    });
    if let Err(error) = committed {
        if let Some(error) = rejected {
            return Ok(Err(error));
        }
        if matches!(
            error,
            AtomicError::RecoveryRequired | AtomicError::Unavailable
        ) {
            return Err(StoreError::CommitUncertain);
        }
        return Ok(Err(atomic_error(error)));
    }
    let view = engine.snapshot()?;
    let current = inspection::read_in(&view, access)
        .map_err(inspection::native_namespace)?
        .ok_or(StoreError::CommitUncertain)?;
    completion
        .ok_or(StoreError::CommitUncertain)?
        .resolve(&current)
        .map_err(|_| StoreError::CommitUncertain)?;
    Ok(Ok((current, receipt, false)))
}

pub(super) fn operation_context(
    access: &Access,
    request: &c::MutateStateRequest,
) -> NamespaceOperationContext {
    NamespaceOperationContext {
        tenant: access
            .binding
            .publication
            .scope
            .tenant()
            .expect("validated tenant")
            .clone(),
        actor: format!("{}:{}", access.caller.owner_kind, access.caller.scope),
        operation_id: request.operation_id.clone(),
    }
}
fn conflict() -> PlatformError {
    super::error(
        PlatformErrorCode::StateConflict,
        "state-operation-precondition-changed",
    )
}
fn atomic_error(error: AtomicError) -> PlatformError {
    match error {
        AtomicError::Invalid => invalid(),
        AtomicError::PermissionDenied => denied(),
        AtomicError::Conflict | AtomicError::InProgress => conflict(),
        AtomicError::Limit => super::capacity(),
        AtomicError::NotFound => super::missing(),
        AtomicError::Expired => expired(),
        AtomicError::RecoveryRequired | AtomicError::Unavailable => super::error(
            PlatformErrorCode::Unavailable,
            "state-maintenance-recovery-required",
        ),
        AtomicError::Corrupt => super::error(
            PlatformErrorCode::Internal,
            "state-maintenance-record-invalid",
        ),
        _ => unsupported(),
    }
}
