//! Audit ownership around the existing atomic deployment catalog call.

mod digest;

#[cfg(test)]
mod tests;

use latent_artifacts::{ReleaseAuditAck, ReleaseAuditStatus};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditAttempt, AuditControlAction, AuditHandle,
    AuditIdentities, AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult,
    AuditReason, AuditScope,
};
use latent_control_store::VersionedDeployment;
use latent_core::{
    ArtifactBlobDigest, DeploymentId, InvocationPrincipal, PrincipalKind, RouteGeneration,
};
use latent_manifest::DeploymentManifest;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tonic::Status;

use super::super::{errors::platform_status, ManagementLimits};

static NEXT: AtomicU64 = AtomicU64::new(0);

pub(super) struct DeploymentAudit {
    attempt: Option<AuditAttempt>,
    ack: ReleaseAuditAck,
    delete: bool,
    expected: Option<Expected>,
}

struct Expected {
    id: DeploymentId,
    digest: ArtifactBlobDigest,
    generation: Option<u64>,
}

impl DeploymentAudit {
    pub(super) async fn apply(
        audit: Option<&AuditHandle>,
        principal: &InvocationPrincipal,
        manifest: &DeploymentManifest,
        expected: Option<u64>,
        limits: &ManagementLimits,
    ) -> Result<Self, Status> {
        if audit.is_none() {
            return Ok(Self::disabled(false));
        }
        Self::begin(
            audit,
            principal,
            AuditIdentities {
                deployment: Some(manifest.id.clone()),
                component: Some(manifest.release.clone()),
                ..Default::default()
            },
            expected,
            digest::apply(manifest, expected),
            false,
            limits,
        )
        .await
    }

    pub(super) async fn delete(
        audit: Option<&AuditHandle>,
        principal: &InvocationPrincipal,
        id: &DeploymentId,
        expected: Option<u64>,
        limits: &ManagementLimits,
    ) -> Result<Self, Status> {
        if audit.is_none() {
            return Ok(Self::disabled(true));
        }
        Self::begin(
            audit,
            principal,
            AuditIdentities {
                deployment: Some(id.clone()),
                ..Default::default()
            },
            expected,
            digest::delete(id, expected),
            true,
            limits,
        )
        .await
    }

    async fn begin(
        audit: Option<&AuditHandle>,
        principal: &InvocationPrincipal,
        identities: AuditIdentities,
        expected: Option<u64>,
        request_digest: ArtifactBlobDigest,
        delete: bool,
        limits: &ManagementLimits,
    ) -> Result<Self, Status> {
        let Some(audit) = audit else {
            return Ok(Self {
                attempt: None,
                delete,
                expected: None,
                ack: ReleaseAuditAck {
                    status: ReleaseAuditStatus::Disabled,
                    attempt_sequence: None,
                },
            });
        };
        let subject = &principal.subject;
        let kind = match principal.kind {
            PrincipalKind::User => AuditActorKind::User,
            PrincipalKind::Service => AuditActorKind::Service,
            PrincipalKind::Node => AuditActorKind::Node,
            PrincipalKind::Trigger => AuditActorKind::Trigger,
            PrincipalKind::Administrator => AuditActorKind::Administrator,
            PrincipalKind::Anonymous => AuditActorKind::Anonymous,
            _ => {
                return Err(Status::permission_denied(
                    "unsupported deployment audit actor",
                ))
            }
        };
        let sequence = NEXT
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| Status::resource_exhausted("deployment audit operation ids exhausted"))?;
        let expected_identity = Expected {
            id: identities
                .deployment
                .clone()
                .expect("validated deployment identity"),
            digest: request_digest.clone(),
            generation: expected,
        };
        let attempt = AuditOperationAttempt {
            scope: AuditScope::Tenant(principal.tenant.clone().expect("authenticated tenant")),
            actor: AuditActorIdentity {
                kind,
                subject: subject.clone(),
            },
            operation_id: format!("deployment-{}-{}-{sequence}", std::process::id(), now()),
            request_digest,
            action: if delete {
                AuditControlAction::DeploymentDelete
            } else {
                AuditControlAction::DeploymentApply
            },
            identities,
            expected_generation: None,
            expected_deployment_generation: expected,
            replay: false,
            occurred_at_unix_millis: now(),
            preview_receipt_digest: None,
        };
        let mut accepted = audit
            .try_reserve_critical(&attempt)
            .map_err(|error| platform_status(error, limits))?
            .begin()
            .wait()
            .await
            .map_err(|error| platform_status(error, limits))?;
        let sequence = accepted.sequence();
        accepted
            .mutation_started()
            .map_err(|error| platform_status(error, limits))?;
        Ok(Self {
            attempt: Some(accepted),
            delete,
            expected: Some(expected_identity),
            ack: ReleaseAuditAck {
                status: ReleaseAuditStatus::OutcomeUnknown,
                attempt_sequence: Some(sequence),
            },
        })
    }

    fn disabled(delete: bool) -> Self {
        Self {
            attempt: None,
            delete,
            expected: None,
            ack: ReleaseAuditAck {
                status: ReleaseAuditStatus::Disabled,
                attempt_sequence: None,
            },
        }
    }

    pub(super) fn matches(
        &self,
        deployment: &VersionedDeployment,
        generation: RouteGeneration,
    ) -> bool {
        let Some(expected) = &self.expected else {
            return true;
        };
        if deployment.manifest.id != expected.id || generation.0 == 0 || deployment.generation == 0
        {
            return false;
        }
        if self.delete {
            deployment.generation < generation.0
                && expected
                    .generation
                    .is_none_or(|value| value == deployment.generation)
        } else {
            deployment.generation == generation.0
                && expected
                    .generation
                    .is_none_or(|value| deployment.generation > value)
                && digest::apply(&deployment.manifest, expected.generation) == expected.digest
        }
    }

    pub(super) async fn finish(
        mut self,
        actual: Option<(&VersionedDeployment, RouteGeneration)>,
    ) -> ReleaseAuditAck {
        let actual =
            actual.filter(|(deployment, generation)| self.matches(deployment, *generation));
        let Some(attempt) = self.attempt.take() else {
            return self.ack;
        };
        let conclusion = actual.map_or_else(
            || AuditOperationConclusion {
                result: AuditOperationResult::Unknown,
                reason: AuditReason::ReceiptUnavailable,
                receipt_digest: None,
                identities: AuditIdentities::default(),
                replay: false,
                occurred_at_unix_millis: now(),
            },
            |(deployment, generation)| AuditOperationConclusion {
                result: AuditOperationResult::Committed,
                reason: AuditReason::Committed,
                receipt_digest: Some(digest::receipt(deployment, generation, self.delete)),
                identities: AuditIdentities {
                    deployment: Some(deployment.manifest.id.clone()),
                    component: Some(deployment.manifest.release.clone()),
                    deployment_generation: Some(deployment.generation),
                    route_generation: Some(generation),
                    ..Default::default()
                },
                replay: false,
                occurred_at_unix_millis: now(),
            },
        );
        if attempt.finish(conclusion).wait().await.is_ok() && actual.is_some() {
            self.ack.status = ReleaseAuditStatus::Durable;
        }
        self.ack
    }
}

pub(super) fn response(
    deployment: &VersionedDeployment,
    tenant: &latent_core::TenantId,
    limits: &ManagementLimits,
    enabled: bool,
) -> Result<super::super::proto::ApplyDeploymentResponse, Status> {
    let mut ceiling = limits.clone();
    if enabled {
        ceiling.max_response_bytes = ceiling
            .max_response_bytes
            .checked_sub(128 + std::mem::size_of::<super::super::proto::AuditAck>())
            .ok_or_else(super::super::bounds::exhausted)?;
    }
    let mut response = super::response::apply(deployment, tenant, &ceiling)?;
    if enabled {
        response.audit_ack = Some(super::super::control_audit::maximum());
    }
    Ok(response)
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|value| u64::try_from(value.as_millis()).ok())
        .unwrap_or(0)
}
