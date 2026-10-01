use super::{
    audit, c, gate_error, invalid, native_error, response, Access, Arc,
    AuthenticatedInvocationContext, OwnedPhase4Response, PlatformError,
};
use latent_audit::{AuditOperationResult as ResultKind, AuditReason};
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_effects::runtime::{
    DispatcherControlAction as Action, DispatcherControlError as ControlError,
    DispatcherControlGeneration, DispatcherControlReceipt, DispatcherControlRequest,
};
use latent_state::embedded::StoreError;

struct Retained {
    pending: Option<audit::Pending>,
    finish: Option<audit::Finish>,
    // Last: typed conclusions and all unclaimed native values retire first.
    access: Arc<Access>,
}
fn request(
    context: &AuthenticatedInvocationContext,
    value: &c::ControlDispatcherRequest,
) -> Result<DispatcherControlRequest, PlatformError> {
    let caller = CallerScope::derive(context.principal(), &RecoverySelection::OriginalCaller)?;
    let expected = value.expected_generation.as_ref().ok_or_else(invalid)?;
    DispatcherControlRequest::new(
        context
            .principal()
            .tenant
            .as_ref()
            .ok_or_else(invalid)?
            .0
            .clone(),
        format!("{}:{}", caller.owner_kind, caller.scope),
        value.operation_id.clone(),
        DispatcherControlGeneration::new(expected.owner_epoch, expected.revision)
            .map_err(native_error)?,
        match c::DispatcherAction::try_from(value.action) {
            Ok(c::DispatcherAction::Pause) => Action::Pause,
            Ok(c::DispatcherAction::Resume) => Action::Resume,
            _ => return Err(invalid()),
        },
    )
    .map_err(native_error)
}
pub(super) async fn mutate(
    access: Arc<Access>,
    context: &AuthenticatedInvocationContext,
    value: c::ControlDispatcherRequest,
    mut pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    access.with_current(&mut || Ok(()))?;
    let prepared = access
        .port
        .prepare_control(request(context, &value)?)
        .map_err(native_error)?;
    // Critical audit is reserved and durable before accepted native work. This
    // bookkeeping call and eventual append occur outside every policy fence.
    pending.started()?;
    let policy = Arc::clone(&access.decision);
    let live = Arc::clone(&access);
    let job = access
        .port
        .submit_control_retained(
            prepared,
            Retained {
                pending: Some(pending),
                finish: None,
                access: Arc::clone(&access),
            },
            super::WORK_BYTES as u64,
            move |accept| {
                let mut outcome = None;
                policy
                    .with_current(&mut || {
                        outcome = Some(accept());
                        Ok(())
                    })
                    .map_err(|error| gate_error(&error))?;
                outcome.ok_or(ControlError::InvalidAuthorizationFence)?
            },
            move |accept| {
                if live.inner.services.clock.monotonic_now() >= live.deadline {
                    return Err(ControlError::DeadlineExceeded);
                }
                let mut outcome = None;
                live.permit
                    .with_live(&mut || {
                        outcome = Some(accept());
                    })
                    .map_err(|error| gate_error(&error))?;
                outcome.ok_or(ControlError::InvalidAuthorizationFence)?
            },
            |outcome, retained| {
                let (result, reason, digest, replay) = match outcome {
                    Ok(value) => (
                        ResultKind::Committed,
                        AuditReason::Committed,
                        Some(value.receipt.digest()?),
                        value.replayed,
                    ),
                    Err(ControlError::Store(
                        StoreError::CommitUncertain | StoreError::Unavailable,
                    )) => (
                        ResultKind::Unknown,
                        AuditReason::MutationUncertain,
                        None,
                        false,
                    ),
                    Err(_) => (ResultKind::Rejected, AuditReason::Rejected, None, false),
                };
                retained.finish = Some(
                    retained
                        .pending
                        .take()
                        .ok_or(StoreError::Invalid)?
                        .finish(result, reason, digest, replay),
                );
                Ok(())
            },
        )
        .map_err(native_error)?;
    let result = job
        .await
        .map_err(super::super::io_error)?
        .map_err(super::super::protected_error)?;
    let native = result.outcome.map_err(native_error)?;
    let receipt = super::projection::receipt(&native.receipt)?;
    let ack = audit::ack(result.retained.finish.ok_or_else(invalid)?).await;
    response::owned(
        result.retained.access,
        c::ControlDispatcherResponse {
            receipt: Some(receipt),
            replayed: native.replayed,
            published: native.published,
            paused: native.paused,
            audit_ack: Some(ack),
        }
        .into(),
    )
}
pub(super) async fn receipt(
    access: Arc<Access>,
    context: &AuthenticatedInvocationContext,
    value: c::GetDispatcherOperationRequest,
    pending: audit::Pending,
) -> Result<OwnedPhase4Response, PlatformError> {
    let original = request(context, value.original.as_ref().ok_or_else(invalid)?)?;
    let worker = Arc::clone(&access);
    let job = access
        .port
        .lookup_control_retained(
            original,
            Retained {
                pending: Some(pending),
                finish: None,
                access: Arc::clone(&access),
            },
            super::WORK_BYTES as u64,
            move || {
                worker
                    .with_current(&mut || Ok(()))
                    .map_err(|error| gate_error(&error))
            },
            |result, retained| {
                let digest = result
                    .as_ref()
                    .ok()
                    .and_then(|v| v.as_ref())
                    .map(DispatcherControlReceipt::digest)
                    .transpose()?;
                let (outcome, reason) = if digest.is_some() {
                    (ResultKind::Committed, AuditReason::Committed)
                } else {
                    (ResultKind::Rejected, AuditReason::ReceiptUnavailable)
                };
                retained.finish = Some(
                    retained
                        .pending
                        .take()
                        .ok_or(StoreError::Invalid)?
                        .finish(outcome, reason, digest, true),
                );
                Ok(())
            },
        )
        .map_err(native_error)?;
    let result = job
        .await
        .map_err(super::super::io_error)?
        .map_err(super::super::protected_error)?;
    let native = result
        .receipt
        .map_err(native_error)?
        .ok_or_else(super::super::missing)?;
    let receipt = super::projection::receipt(&native)?;
    let ack = audit::ack(result.retained.finish.ok_or_else(invalid)?).await;
    response::owned(
        result.retained.access,
        c::GetDispatcherOperationResponse {
            receipt: Some(receipt),
            audit_ack: Some(ack),
        }
        .into(),
    )
}
