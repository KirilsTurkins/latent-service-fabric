use super::authorization::Access;
use super::{
    audit, c, denied, error, expired, io_error, missing, mutation, protected_error, response, Arc,
    Inner, Instant, NamespaceCatalog, NamespaceError, OwnedPhase4Response, PlatformError,
    PlatformErrorCode, StateManagementReservation, WORK_BYTES,
};
use latent_audit::{AuditOperationResult, AuditReason};
use latent_capabilities::namespace::NamespaceControl;
use latent_rpc::transaction::v1 as t;
use latent_state::{
    embedded::{EmbeddedStore, Family, ReadView, StoreError},
    namespace::{
        catalog::{NamespaceOperationContext, NamespaceRead},
        NamespaceRecord,
    },
    store_io::StoreIoKind,
};

pub(super) async fn inspect(
    inner: Arc<Inner>,
    _request: Box<c::InspectNamespaceRequest>,
    access: Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    let worker = Arc::clone(&inner);
    let retained = Arc::clone(&permit);
    let job = inner
        .services
        .store
        .with_store(
            StoreIoKind::RecoveryRead,
            WORK_BYTES as u64,
            move |engine| {
                let result = inspect_in(&worker, engine, &access, deadline, retained.as_ref());
                let finish = pending.finish(
                    if result.as_ref().is_ok_and(Result::is_ok) {
                        AuditOperationResult::Committed
                    } else {
                        AuditOperationResult::Rejected
                    },
                    AuditReason::Verified,
                    None,
                    false,
                );
                // Keep global capacity in the unclaimed native completion as well
                // as the waiter. Its bytes retire after that completion's values.
                result.map(|value| (value, access.inspect, finish, retained))
            },
        )
        .map_err(protected_error)?;
    let (result, decision, finish, worker_permit) =
        job.await.map_err(io_error)?.map_err(protected_error)?;
    let (read, namespace) = result?;
    read_ack(finish).await?;
    response::owned(
        inner,
        worker_permit,
        decision,
        read,
        None,
        deadline,
        c::InspectNamespaceResponse {
            namespace: Some(namespace),
        }
        .into(),
    )
}
fn inspect_in(
    inner: &Inner,
    engine: &EmbeddedStore,
    access: &Access,
    deadline: Instant,
    permit: &dyn StateManagementReservation,
) -> Result<Result<(NamespaceRead, c::NamespaceInspection), PlatformError>, StoreError> {
    if let Err(error) = before_lookup(inner, access, deadline, permit) {
        return Ok(Err(error));
    }
    let view = engine.snapshot()?;
    let read = read_in(&view, access).map_err(native_namespace)?;
    let Some(read) = read else {
        return Ok(Err(missing()));
    };
    if let Err(error) = inspection_gate(inner, access, &read, None) {
        return Ok(Err(error));
    }
    let usage = latent_state::session::inspect_usage(&view, read.record())
        .map_err(|error| error.storage_error().unwrap_or(StoreError::Corrupt))?;
    let (commands, pending_effects, retention) =
        inventory(inner, &view, access, read.record(), deadline)?;
    let (profile, digest) = inner.services.store.inspection_profile();
    let mut version = b"NSV\x01".to_vec();
    version.extend_from_slice(&read.record().version.incarnation.to_le_bytes());
    version.extend_from_slice(&read.record().version.generation.to_le_bytes());
    let value = c::NamespaceInspection {
        view: Some(t::ViewIdentity {
            namespace: Some(response::selector(read.record())),
            version,
            state_schema: read.record().state_schema.clone(),
        }),
        encoded_state_bytes: usage.encoded_bytes,
        command_count: commands,
        pending_effect_count: pending_effects,
        retained_formats: retention,
        engine_profile: profile.into(),
        engine_profile_digest: format!("sha256:{}", response::hex(&digest)),
        status: response::status(read.record().status) as i32,
        quota: Some(response::quota(read.record().quota)),
        generation: read.record().version.generation,
    };
    Ok(Ok((read, value)))
}

pub(super) async fn receipt(
    inner: Arc<Inner>,
    request: Box<c::GetStateOperationReceiptRequest>,
    access: Access,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    let worker = Arc::clone(&inner);
    let retained = Arc::clone(&permit);
    let job = inner
        .services
        .store
        .with_store(StoreIoKind::RecoveryRead, 65536, move |engine| {
            let result = (|| {
                if let Err(error) = before_lookup(&worker, &access, deadline, retained.as_ref()) {
                    return Ok(Err(error));
                }
                let view = engine.snapshot()?;
                let read = read_in(&view, &access).map_err(native_namespace)?;
                let Some(read) = read else {
                    return Ok(Err(missing()));
                };
                if let Err(error) = inspection_gate(&worker, &access, &read, None) {
                    return Ok(Err(error));
                }
                let context = NamespaceOperationContext {
                    tenant: read.record().tenant.clone(),
                    actor: format!("{}:{}", access.caller.owner_kind, access.caller.scope),
                    operation_id: request.operation_id,
                };
                let receipt =
                    NamespaceCatalog::outcome_in(&view, &context).map_err(native_namespace)?;
                let Some(receipt) = receipt else {
                    return Ok(Err(missing()));
                };
                if let Err(error) = inspection_gate(&worker, &access, &read, Some(&receipt)) {
                    return Ok(Err(error));
                }
                let public = mutation::receipt_to_proto(&receipt).map_err(native_namespace)?;
                Ok(Ok((read, receipt, public)))
            })();
            let finish = pending.finish(
                if result.as_ref().is_ok_and(Result::is_ok) {
                    AuditOperationResult::Committed
                } else {
                    AuditOperationResult::Rejected
                },
                AuditReason::Verified,
                None,
                true,
            );
            result.map(|value| (value, access.inspect, finish, retained))
        })
        .map_err(protected_error)?;
    let (result, decision, finish, worker_permit) =
        job.await.map_err(io_error)?.map_err(protected_error)?;
    let (read, receipt, public) = result?;
    read_ack(finish).await?;
    response::owned(
        inner,
        worker_permit,
        decision,
        read,
        Some(receipt),
        deadline,
        c::GetStateOperationReceiptResponse {
            receipt: None,
            namespace_receipt: Some(public),
        }
        .into(),
    )
}
pub(super) fn before_lookup(
    inner: &Inner,
    access: &Access,
    deadline: Instant,
    permit: &dyn StateManagementReservation,
) -> Result<(), PlatformError> {
    if inner.services.clock.monotonic_now() >= deadline {
        return Err(expired());
    }
    inner
        .services
        .policy
        .with_retained_decision(&access.inspect, &mut |_, _| permit.with_live(&mut || {}))
}
pub(super) fn read_in(
    view: &ReadView,
    access: &Access,
) -> Result<Option<NamespaceRead>, NamespaceError> {
    NamespaceCatalog::read_in(
        view,
        access
            .binding
            .publication
            .scope
            .tenant()
            .ok_or(NamespaceError::PermissionDenied)?,
        &access.binding.namespace,
    )
}
pub(super) fn inspection_gate(
    inner: &Inner,
    access: &Access,
    read: &NamespaceRead,
    receipt: Option<&latent_state::namespace::catalog::NamespaceOperationReceipt>,
) -> Result<(), PlatformError> {
    if read.record().state_schema != access.binding.state_schema {
        return Err(denied());
    }
    NamespaceControl::with_inspection_retained(
        &inner.services.policy,
        &access.inspect,
        inner.services.namespaces.lifecycle(),
        read,
        receipt,
        || Ok(()),
    )
}
pub(super) fn native_namespace(error: NamespaceError) -> StoreError {
    match error {
        NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
        NamespaceError::Capacity => StoreError::Capacity,
        NamespaceError::Unavailable => StoreError::Unavailable,
        NamespaceError::RecoveryRequired => StoreError::CommitUncertain,
        _ => StoreError::Corrupt,
    }
}
async fn read_ack(finish: audit::Finish) -> Result<(), PlatformError> {
    let ack = audit::ack(finish).await;
    if ack.status == c::AuditAckStatus::OutcomeUnknown as i32 {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "namespace-audit-outcome-unknown",
        ));
    }
    Ok(())
}
fn inventory(
    inner: &Inner,
    view: &ReadView,
    access: &Access,
    namespace: &NamespaceRecord,
    deadline: Instant,
) -> Result<(u64, u64, Vec<t::LinkedRetention>), StoreError> {
    use latent_commit::atomic::{command_row_key, CommandRecord};
    let mut commands = 0u64;
    let mut effects = 0u64;
    let mut retention = Vec::new();
    for (family, prefix) in [
        (Family::Command, b"command-v1\0".as_slice()),
        (
            Family::Outbox,
            latent_effects::dispatch_store::EFFECT_PREFIX,
        ),
    ] {
        let mut after = None;
        let mut rows = 0usize;
        let mut bytes = 0usize;
        loop {
            if inner.services.clock.monotonic_now() >= deadline {
                return Err(StoreError::SnapshotExpired);
            }
            let page = view.scan_after(family, prefix, after.as_deref(), 128, 4 * 1024 * 1024)?;
            for (key, value) in page.rows {
                rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
                bytes = bytes
                    .checked_add(key.key.len() + value.len())
                    .ok_or(StoreError::Capacity)?;
                if rows > 65536 || bytes > 128 * 1024 * 1024 {
                    return Err(StoreError::Capacity);
                }
                if family == Family::Command {
                    let record = CommandRecord::decode(&value).map_err(|_| StoreError::Corrupt)?;
                    if key != command_row_key(record.id()) {
                        return Err(StoreError::Corrupt);
                    }
                    if record.key().tenant == namespace.tenant.0
                        && record.key().namespace == namespace.id.0
                        && record.key().incarnation == namespace.version.incarnation.to_string()
                    {
                        commands = commands.checked_add(1).ok_or(StoreError::Capacity)?;
                        if record.key().recovery_scope == access.caller.scope
                            && record.result_read_policy() == access.binding.result_policy
                        {
                            if retention.len() == 128 || record.effect_ids().len() >= 128 {
                                return Err(StoreError::Capacity);
                            }
                            let required = std::iter::once(record.id().hex())
                                .chain(record.effect_ids().iter().map(|identity| identity.hex()))
                                .collect();
                            let payload_available = if record.outcome()
                                == latent_commit::atomic::Outcome::Pending
                            {
                                false
                            } else if let Some(bytes) =
                                view.get(&latent_commit::atomic::result_row_key(
                                    record.id(),
                                    record.attempt(),
                                ))?
                            {
                                let result = latent_commit::atomic::DurableResult::decode(&bytes)
                                    .map_err(|_| StoreError::Corrupt)?;
                                result.verify(&record).map_err(|_| StoreError::Corrupt)?;
                                result.value().is_some()
                            } else {
                                false
                            };
                            retention.push(t::LinkedRetention {
                                record_format: "latent.command.v1".into(),
                                record_version: 1,
                                payload_expires_at_unix_millis: Some(record.result_expires()),
                                identity_expires_at_unix_millis: Some(record.identity_expires()),
                                remaining_recovery_millis: None,
                                required_record_ids: required,
                                payload_available,
                            });
                        }
                    }
                } else {
                    let effect = latent_effects::dispatch::EffectRecord::decode(&value)
                        .map_err(|_| StoreError::Corrupt)?;
                    let authority = effect.authority().map_err(|_| StoreError::Corrupt)?;
                    if key
                        != latent_effects::dispatch_store::effect_row_key(&authority.link().effect)?
                    {
                        return Err(StoreError::Corrupt);
                    }
                    let scope = authority.scope();
                    if scope.tenant == namespace.tenant.0
                        && scope.namespace == namespace.id.0
                        && scope.incarnation == namespace.version.incarnation
                        && !effect.disposition().terminal()
                    {
                        effects = effects.checked_add(1).ok_or(StoreError::Capacity)?;
                    }
                }
            }
            after = page.resume;
            if after.is_none() {
                break;
            }
        }
    }
    Ok((commands, effects, retention))
}
