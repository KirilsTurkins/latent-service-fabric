//! Node control over the installed dispatcher, current policy and original
//! global reservation. No public selector supplies node-operator authority.
mod control;
mod projection;
mod response;
use super::{
    audit, c, capacity, contract, denied, error, expired, invalid, unsupported, Arc,
    AuthenticatedInvocationContext, Inner, Instant, OwnedPhase4Response, PlatformError,
    PlatformErrorCode, StateManagementReservation,
};
use crate::management::ManagementDecision;
use latent_audit::{
    AuditControlAction, AuditDispatcherTarget, AuditIdentities, AuditOperationResult, AuditReason,
    AuditScope,
};
use latent_effects::runtime::{DispatcherControlError, DispatcherManagementPort};
use prost::Message;
use sha2::{Digest, Sha256};

pub(super) const WORK_BYTES: usize = 128 * 1024;
pub(super) const RESPONSE_BYTES: usize = 80 * 1024;
pub(super) struct Access {
    inner: Arc<Inner>,
    port: DispatcherManagementPort,
    decision: Arc<dyn ManagementDecision>,
    permit: Arc<dyn StateManagementReservation>,
    deadline: Instant,
}
impl Access {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut calls = 0_u8;
        self.decision.with_current(&mut || {
            if self.inner.services.clock.monotonic_now() >= self.deadline {
                return Err(expired());
            }
            let mut outcome = None;
            self.permit.with_live(&mut || {
                calls = calls.saturating_add(1);
                if calls == 1 {
                    outcome = Some(action());
                }
            })?;
            if calls != 1 {
                return Err(invalid());
            }
            outcome.ok_or_else(invalid)?
        })?;
        if calls != 1 {
            return Err(invalid());
        }
        Ok(())
    }
}
pub(super) async fn execute(
    inner: Arc<Inner>,
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    decision: Arc<dyn ManagementDecision>,
    deadline: Instant,
    permit: Arc<dyn StateManagementReservation>,
) -> Result<OwnedPhase4Response, PlatformError> {
    let port = inner.dispatcher.clone().ok_or_else(unsupported)?;
    let access = Arc::new(Access {
        inner: Arc::clone(&inner),
        port,
        decision,
        permit,
        deadline,
    });
    access.with_current(&mut || Ok(()))?;
    // Node controls always reserve durable critical audit before preparing a
    // mutation. Supplying a receipt/epoch cannot replace this actual owner.
    if inner.services.audit.is_none() {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "dispatcher-audit-owner-required",
        ));
    }
    let pending = begin(&inner, &access, &context, &request).await?;
    match request {
        contract::Request::InspectDispatcher(_) => {
            access.with_current(&mut || Ok(()))?;
            let value = access.port.snapshot().map_err(|_| unsupported())?;
            let value = projection::snapshot(&value, access.port.clock_continuity_proven())?;
            let finish = pending.finish(
                AuditOperationResult::Committed,
                AuditReason::Committed,
                None,
                false,
            );
            let ack = audit::ack(finish).await;
            response::owned(
                access,
                c::InspectDispatcherResponse {
                    dispatcher: Some(value),
                    audit_ack: Some(ack),
                }
                .into(),
            )
        }
        contract::Request::ControlDispatcher(request) => {
            control::mutate(access, &context, *request, pending).await
        }
        contract::Request::GetDispatcherOperation(request) => {
            control::receipt(access, &context, *request, pending).await
        }
        _ => Err(unsupported()),
    }
}
async fn begin(
    inner: &Inner,
    access: &Access,
    context: &AuthenticatedInvocationContext,
    request: &contract::Request,
) -> Result<audit::Pending, PlatformError> {
    let (operation_id, action, expected, epoch, bytes) = match request {
        contract::Request::InspectDispatcher(value) => (
            audit::read_operation_id("dispatcher")?,
            AuditControlAction::DispatcherInspect,
            None,
            access
                .port
                .snapshot()
                .map_err(|_| unsupported())?
                .control
                .generation
                .owner_epoch(),
            value.encode_to_vec(),
        ),
        contract::Request::ControlDispatcher(value) => (
            value.operation_id.clone(),
            match c::DispatcherAction::try_from(value.action) {
                Ok(c::DispatcherAction::Pause) => AuditControlAction::DispatcherPause,
                Ok(c::DispatcherAction::Resume) => AuditControlAction::DispatcherResume,
                _ => return Err(invalid()),
            },
            value.expected_generation.as_ref().map(|v| v.revision),
            value
                .expected_generation
                .as_ref()
                .ok_or_else(invalid)?
                .owner_epoch,
            value.encode_to_vec(),
        ),
        contract::Request::GetDispatcherOperation(value) => {
            let original = value.original.as_ref().ok_or_else(invalid)?;
            (
                original.operation_id.clone(),
                AuditControlAction::DispatcherOperationRead,
                original.expected_generation.as_ref().map(|v| v.revision),
                original
                    .expected_generation
                    .as_ref()
                    .ok_or_else(invalid)?
                    .owner_epoch,
                value.encode_to_vec(),
            )
        }
        _ => return Err(unsupported()),
    };
    let mut hash = Sha256::new();
    hash.update(b"lsf-dispatcher-management-request-v1\0");
    hash.update(bytes);
    audit::begin_operation(
        inner,
        context,
        audit::OperationAudit {
            scope: AuditScope::Node,
            identities: AuditIdentities {
                dispatcher: Some(AuditDispatcherTarget {
                    owner_epoch: epoch,
                    actor_tenant: context
                        .principal()
                        .tenant
                        .as_ref()
                        .ok_or_else(denied)?
                        .0
                        .clone(),
                }),
                ..Default::default()
            },
            operation_id,
            action,
            expected,
            request_digest: format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(hash.finalize())
            )
            .parse()
            .map_err(|_| invalid())?,
        },
    )
    .await
}
fn native_error(value: DispatcherControlError) -> PlatformError {
    use DispatcherControlError as E;
    match value {
        E::PermissionDenied => denied(),
        E::DeadlineExceeded => expired(),
        E::Invalid => invalid(),
        E::Capacity => capacity(),
        E::Conflict => error(
            PlatformErrorCode::StateConflict,
            "dispatcher-generation-conflict",
        ),
        E::RestoreReviewRequired => error(
            PlatformErrorCode::StateConflict,
            "dispatcher-restore-review-required",
        ),
        E::ClockDiscontinuity => error(
            PlatformErrorCode::Unavailable,
            "dispatcher-clock-continuity-required",
        ),
        _ => unsupported(),
    }
}
fn gate_error(value: &PlatformError) -> DispatcherControlError {
    match value.code {
        PlatformErrorCode::PermissionDenied => DispatcherControlError::PermissionDenied,
        PlatformErrorCode::DeadlineExceeded | PlatformErrorCode::Cancelled => {
            DispatcherControlError::DeadlineExceeded
        }
        _ => DispatcherControlError::AuthorityUnavailable,
    }
}
