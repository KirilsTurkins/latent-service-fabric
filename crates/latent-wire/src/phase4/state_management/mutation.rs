use super::authorization::Access;
use super::{
    audit, c, denied, inspection, invalid, io_error, namespace_error, protected_error, response,
    Arc, Inner, Instant, NamespaceCatalog, NamespaceError, NamespaceQuota, OwnedPhase4Response,
    PlatformError, StateManagementBinding, StateManagementReservation,
};
use latent_audit::{AuditOperationResult, AuditReason};
use latent_capabilities::namespace::{NamespaceControl, RetainedNamespaceControlRequest};
use latent_state::{
    embedded::{EmbeddedStore, FencedStoreError, StoreError},
    namespace::{
        catalog::{NamespaceMutation, NamespaceOperationReceipt, NamespaceRead},
        NamespaceTransition, NamespaceVersion,
    },
    store_io::StoreIoKind,
};

pub(super) async fn mutate(
    inner: Arc<Inner>,
    request: Box<c::MutateNamespaceRequest>,
    access: Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    let mutation = mutation(&request, &access.binding)?;
    let worker = Arc::clone(&inner);
    let retained = Arc::clone(&permit);
    let job = inner
        .services
        .store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            131_072,
            Arc::new(Arc::clone(&permit)),
            move |engine| {
                let mut pending = pending;
                let result = write(
                    &worker,
                    engine,
                    &request,
                    &mutation,
                    &WriteAccess {
                        access: &access,
                        permit: retained.as_ref(),
                        deadline,
                    },
                    &mut pending,
                );
                let (disposition, reason, digest, replay) = match &result {
                    Ok(Ok((_, receipt, replay))) => (
                        AuditOperationResult::Committed,
                        AuditReason::Committed,
                        Some(receipt.digest().map_err(inspection::native_namespace)?),
                        *replay,
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
                let finish = pending.finish(disposition, reason, digest, replay);
                result.map(|value| (value, access.inspect, finish, retained))
            },
        )
        .map_err(protected_error)?;
    let (result, inspect, finish, worker_permit) =
        job.await.map_err(io_error)?.map_err(protected_error)?;
    let (read, receipt, replayed) = result?;
    let public = receipt_to_proto(&receipt).map_err(namespace_error)?;
    let ack = audit::ack(finish).await;
    response::owned(
        inner,
        worker_permit,
        inspect,
        read,
        Some(receipt),
        deadline,
        c::MutateNamespaceResponse {
            receipt: Some(public),
            replayed,
            audit_ack: Some(ack),
        }
        .into(),
    )
}
struct WriteAccess<'a> {
    access: &'a Access,
    permit: &'a dyn StateManagementReservation,
    deadline: Instant,
}
fn write(
    inner: &Inner,
    engine: &EmbeddedStore,
    request: &c::MutateNamespaceRequest,
    mutation: &NamespaceMutation,
    captured: &WriteAccess<'_>,
    pending: &mut audit::Pending,
) -> Result<Result<(NamespaceRead, NamespaceOperationReceipt, bool), PlatformError>, StoreError> {
    let WriteAccess {
        access,
        permit,
        deadline,
    } = *captured;
    if let Err(error) = inspection::before_lookup(inner, access, deadline, permit) {
        return Ok(Err(error));
    }
    let decision = access.mutation.as_ref().ok_or(StoreError::Invalid)?;
    let prepared = NamespaceControl::prepare_retained(
        &inner.services.policy,
        decision,
        &inner.services.namespaces,
        engine,
        RetainedNamespaceControlRequest {
            mutation,
            operation_id: &request.operation_id,
            inspection: Some(&access.inspect),
        },
        0,
    );
    let prepared = match prepared {
        Ok(value) => value,
        Err(error) => return Ok(Err(error)),
    };
    let (batch, receipt, replayed, fence) = prepared.into_parts();
    if let Err(error) = pending.started() {
        return Ok(Err(error));
    }
    let mut completion = None;
    let committed = engine.apply_fenced(batch, || {
        fence
            .accept_with(|| {
                let accept = || {
                    if inner.services.clock.monotonic_now() >= deadline {
                        return Err(NamespaceError::Cancelled);
                    }
                    permit
                        .with_live(&mut || {})
                        .map_err(|_| NamespaceError::Cancelled)
                };
                if let (Some(dispatcher), NamespaceMutation::Transition { id, expected, .. }) =
                    (&inner.dispatcher, mutation)
                {
                    dispatcher
                        .prepare_namespace_close(
                            &receipt.record.tenant.0,
                            &id.0,
                            expected.incarnation,
                        )
                        .map_err(|error| match error {
                            latent_effects::authority::AuthorityError::Capacity => {
                                NamespaceError::Capacity
                            }
                            latent_effects::authority::AuthorityError::Unavailable => {
                                NamespaceError::Unavailable
                            }
                            _ => NamespaceError::PermissionDenied,
                        })?
                        .accept(accept)
                } else {
                    accept()
                }
            })
            .map(|value| completion = value)
    });
    match committed {
        Ok(()) => {}
        Err(FencedStoreError::Fence(error)) => return Ok(Err(namespace_error(error))),
        Err(FencedStoreError::Store(StoreError::Conflict)) => {
            return Ok(Err(namespace_error(NamespaceError::Conflict)))
        }
        Err(FencedStoreError::Store(error)) => return Err(error),
    }
    let view = engine.snapshot()?;
    let current = NamespaceCatalog::read_in(&view, &receipt.record.tenant, &receipt.record.id)
        .map_err(inspection::native_namespace)?
        .ok_or(StoreError::CommitUncertain)?;
    if let Some(completion) = completion {
        completion
            .resolve(&current)
            .map_err(|_| StoreError::CommitUncertain)?;
    }
    Ok(Ok((current, receipt, replayed)))
}
fn mutation(
    request: &c::MutateNamespaceRequest,
    binding: &StateManagementBinding,
) -> Result<NamespaceMutation, PlatformError> {
    let configuration = || -> Result<(String, NamespaceQuota), PlatformError> {
        let value = request.configuration.as_ref().ok_or_else(invalid)?;
        let quota = value.quota.as_ref().ok_or_else(invalid)?;
        let quota = NamespaceQuota {
            state_keys: quota.state_keys,
            state_bytes: quota.state_bytes,
            result_rows: quota.result_rows,
            result_bytes: quota.result_bytes,
            effect_rows: quota.effect_rows,
            effect_bytes: quota.effect_bytes,
            payload_bytes: quota.payload_bytes,
            recovery_bytes: quota.recovery_bytes,
        };
        quota.validate().map_err(namespace_error)?;
        let maximum = binding.maximum_quota;
        if value.state_schema != binding.state_schema
            || [
                (quota.state_keys, maximum.state_keys),
                (quota.state_bytes, maximum.state_bytes),
                (quota.result_rows, maximum.result_rows),
                (quota.result_bytes, maximum.result_bytes),
                (quota.effect_rows, maximum.effect_rows),
                (quota.effect_bytes, maximum.effect_bytes),
                (quota.payload_bytes, maximum.payload_bytes),
                (quota.recovery_bytes, maximum.recovery_bytes),
            ]
            .iter()
            .any(|(actual, ceiling)| actual > ceiling)
        {
            return Err(denied());
        }
        Ok((value.state_schema.clone(), quota))
    };
    let kind = c::NamespaceMutationKind::try_from(request.mutation).map_err(|_| invalid())?;
    if kind == c::NamespaceMutationKind::Create {
        if binding.incarnation != 1 || request.expected_generation != Some(0) {
            return Err(invalid());
        }
        let (state_schema, quota) = configuration()?;
        return Ok(NamespaceMutation::Create {
            id: binding.namespace.clone(),
            state_schema,
            quota,
        });
    }
    let action = match kind {
        c::NamespaceMutationKind::Quiesce => NamespaceTransition::Quiesce,
        c::NamespaceMutationKind::Retire => NamespaceTransition::Retire,
        c::NamespaceMutationKind::Destroy => NamespaceTransition::Destroy,
        c::NamespaceMutationKind::Recreate => {
            let (state_schema, quota) = configuration()?;
            NamespaceTransition::Recreate {
                state_schema,
                quota,
            }
        }
        _ => return Err(invalid()),
    };
    Ok(NamespaceMutation::Transition {
        id: binding.namespace.clone(),
        expected: NamespaceVersion {
            incarnation: binding.incarnation,
            generation: request.expected_generation.ok_or_else(invalid)?,
        },
        action,
    })
}
pub(super) fn receipt_to_proto(
    receipt: &NamespaceOperationReceipt,
) -> Result<c::NamespaceOperationReceipt, NamespaceError> {
    let (kind, before) = match receipt.mutation()? {
        NamespaceMutation::Create { .. } => (c::NamespaceMutationKind::Create, None),
        NamespaceMutation::Transition {
            expected, action, ..
        } => (
            match action {
                NamespaceTransition::Quiesce => c::NamespaceMutationKind::Quiesce,
                NamespaceTransition::Retire => c::NamespaceMutationKind::Retire,
                NamespaceTransition::Destroy => c::NamespaceMutationKind::Destroy,
                NamespaceTransition::Recreate { .. } => c::NamespaceMutationKind::Recreate,
            },
            Some(expected.generation),
        ),
    };
    Ok(c::NamespaceOperationReceipt {
        operation_id: receipt.context.operation_id.clone(),
        receipt_id: format!("namespace-receipt:{}", response::hex(&receipt.digest()?)),
        mutation: kind as i32,
        namespace: Some(response::selector(&receipt.record)),
        authenticated_operator: receipt.context.actor.clone(),
        before_generation: before,
        after_generation: receipt.record.version.generation,
        status: response::status(receipt.record.status) as i32,
        state_schema: receipt.record.state_schema.clone(),
        disposition: c::StateOperationDisposition::Committed as i32,
    })
}
