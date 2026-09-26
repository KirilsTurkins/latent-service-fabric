use super::{check_deadline, mapping};
use latent_audit::{
    AuditControlAction, AuditHandle, AuditOperationAttempt, AuditOperationConclusion, AuditScope,
};
use latent_control_store::{deployment_operations::DeploymentOperationLookup, DeploymentStore};
use latent_core::PlatformErrorCode;
use std::time::Instant;

pub(super) async fn lookup(
    repository: &dyn DeploymentStore,
    expected: &AuditOperationAttempt,
    expires: Instant,
) -> crate::Result<AuditOperationConclusion> {
    check_deadline(expires)?;
    let AuditScope::Tenant(tenant) = &expected.scope else {
        return Ok(mapping::conclusion(expected, None));
    };
    let lookup = tokio::time::timeout_at(
        expires.into(),
        repository.get_operation(tenant, &expected.operation_id),
    )
    .await
    .map_err(|_| super::deadline())?;
    check_deadline(expires)?;
    let lookup = match lookup {
        Ok(lookup) => lookup,
        Err(error)
            if matches!(
                error.code,
                PlatformErrorCode::Unavailable | PlatformErrorCode::NotFound
            ) =>
        {
            return Ok(mapping::conclusion(expected, None));
        }
        Err(error) => return Err(error),
    };
    let actual = match lookup.value() {
        DeploymentOperationLookup::Found(receipt) => Some(receipt),
        DeploymentOperationLookup::Unknown { .. } | DeploymentOperationLookup::Uncertain => None,
    };
    Ok(mapping::conclusion(expected, actual))
}

/// Call after catalog recovery and before generic release audit fallback, even
/// when rollout management is disabled. Historical terminal records stay exact.
pub async fn reconcile_deployment_audit(
    audit: &AuditHandle,
    repository: &dyn DeploymentStore,
    expires: Instant,
) -> crate::Result<()> {
    let pending = crate::audit::pending::read(audit, expires).await?;
    for pending in pending {
        if !matches!(
            pending.attempt.action,
            AuditControlAction::DeploymentApply | AuditControlAction::DeploymentDelete
        ) {
            continue;
        }
        check_deadline(expires)?;
        let terminal = if pending.attempt.expected_state_version.is_some() {
            lookup(repository, &pending.attempt, expires).await?
        } else {
            mapping::conclusion(&pending.attempt, None)
        };
        let wait = crate::audit::pending::reconcile(audit, pending.sequence, &terminal, expires)
            .await?
            .wait();
        tokio::time::timeout_at(expires.into(), wait)
            .await
            .map_err(|_| super::deadline())??;
        check_deadline(expires)?;
    }
    Ok(())
}
