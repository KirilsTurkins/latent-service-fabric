use super::authorization::Access;
use super::{
    c, capacity, contract, denied, invalid, response, unsupported, AuthenticatedInvocationContext,
    Inner, PlatformError,
};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditAppendTicket, AuditAttempt, AuditControlAction,
    AuditIdentities, AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult,
    AuditReason, AuditScope, AuditStateTarget,
};
use latent_core::{ArtifactBlobDigest, PrincipalKind};
use prost::Message;
use sha2::{Digest, Sha256};
use std::sync::atomic::{AtomicU64, Ordering};
static NEXT_READ: AtomicU64 = AtomicU64::new(1);
pub(super) struct Pending {
    attempt: Option<AuditAttempt>,
    identities: AuditIdentities,
}
pub(super) struct Finish {
    pub ticket: Option<AuditAppendTicket>,
    pub sequence: Option<u64>,
}
impl Pending {
    pub fn started(&mut self) -> Result<(), PlatformError> {
        if let Some(attempt) = &mut self.attempt {
            attempt.mutation_started()?;
        }
        Ok(())
    }
    pub fn finish(
        self,
        result: AuditOperationResult,
        reason: AuditReason,
        digest: Option<[u8; 32]>,
        replay: bool,
    ) -> Finish {
        let sequence = self.attempt.as_ref().map(AuditAttempt::sequence);
        let conclusion = AuditOperationConclusion {
            canary_decision: None,
            result,
            reason,
            receipt_digest: digest.map(|bytes| {
                format!("sha256:{}", response::hex(&bytes))
                    .parse()
                    .expect("SHA-256 bytes")
            }),
            identities: self.identities,
            replay,
            occurred_at_unix_millis: unix_now(),
        };
        Finish {
            ticket: self.attempt.map(|attempt| attempt.finish(conclusion)),
            sequence,
        }
    }
}
pub(super) async fn begin(
    inner: &Inner,
    access: &Access,
    context: &AuthenticatedInvocationContext,
    request: &contract::Request,
) -> Result<Pending, PlatformError> {
    let identities = AuditIdentities {
        state: Some(AuditStateTarget {
            namespace: access.binding.namespace.0.clone(),
            incarnation: access.binding.incarnation,
            state_schema: access
                .binding
                .state_schema
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| invalid())?,
        }),
        publication: Some(access.binding.publication.id.clone()),
        component: Some(access.binding.component.clone()),
        ..Default::default()
    };
    let Some(audit) = &inner.services.audit else {
        return Ok(Pending {
            attempt: None,
            identities,
        });
    };
    let (operation_id, action, expected) = operation(request)?;
    let mut hash = Sha256::new();
    hash.update(b"lsf-state-management-request-v1\0");
    match request {
        contract::Request::MutateNamespace(value) => hash.update(value.encode_to_vec()),
        contract::Request::InspectNamespace(value) => hash.update(value.encode_to_vec()),
        contract::Request::GetStateOperationReceipt(value) => hash.update(value.encode_to_vec()),
        _ => return Err(unsupported()),
    }
    let attempt = AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: AuditScope::Tenant(context.principal().tenant.clone().ok_or_else(denied)?),
        actor: AuditActorIdentity {
            subject: context.principal().subject.clone(),
            kind: actor(context.principal().kind)?,
        },
        operation_id,
        request_digest: format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(hash.finalize())
        )
        .parse()
        .map_err(|_| invalid())?,
        preview_receipt_digest: None,
        action,
        identities: identities.clone(),
        replay: false,
        expected_generation: expected,
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        occurred_at_unix_millis: unix_now(),
    };
    for result in [
        AuditOperationResult::Committed,
        AuditOperationResult::Rejected,
        AuditOperationResult::NotStarted,
        AuditOperationResult::Unknown,
    ] {
        audit.preflight_conclusion(
            &attempt,
            &AuditOperationConclusion {
                canary_decision: None,
                result,
                reason: AuditReason::MutationUncertain,
                receipt_digest: None,
                identities: identities.clone(),
                replay: false,
                occurred_at_unix_millis: unix_now(),
            },
        )?;
    }
    let accepted = audit.try_reserve_critical(&attempt)?.begin().wait().await?;
    Ok(Pending {
        attempt: Some(accepted),
        identities,
    })
}
fn operation(
    request: &contract::Request,
) -> Result<(String, AuditControlAction, Option<u64>), PlatformError> {
    if let contract::Request::MutateNamespace(value) = request {
        return Ok((
            value.operation_id.clone(),
            action(value.mutation)?,
            value.expected_generation,
        ));
    }
    let read = NEXT_READ
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
            value.checked_add(1)
        })
        .map_err(|_| capacity())?;
    Ok((
        format!(
            "namespace-read-{}-{}-{read}",
            std::process::id(),
            unix_now()
        ),
        AuditControlAction::NamespaceInspect,
        None,
    ))
}
pub(super) async fn ack(finish: Finish) -> c::AuditAck {
    let status = match finish.ticket {
        None => c::AuditAckStatus::Disabled,
        Some(ticket) => {
            if ticket.wait().await.is_ok() {
                c::AuditAckStatus::Durable
            } else {
                c::AuditAckStatus::OutcomeUnknown
            }
        }
    };
    c::AuditAck {
        status: status as i32,
        attempt_sequence: finish.sequence,
    }
}
fn action(value: i32) -> Result<AuditControlAction, PlatformError> {
    Ok(match c::NamespaceMutationKind::try_from(value) {
        Ok(c::NamespaceMutationKind::Create) => AuditControlAction::NamespaceCreate,
        Ok(c::NamespaceMutationKind::Quiesce) => AuditControlAction::NamespaceQuiesce,
        Ok(c::NamespaceMutationKind::Retire) => AuditControlAction::NamespaceRetire,
        Ok(c::NamespaceMutationKind::Destroy) => AuditControlAction::NamespaceDestroy,
        Ok(c::NamespaceMutationKind::Recreate) => AuditControlAction::NamespaceRecreate,
        _ => return Err(invalid()),
    })
}
fn actor(value: PrincipalKind) -> Result<AuditActorKind, PlatformError> {
    Ok(match value {
        PrincipalKind::User => AuditActorKind::User,
        PrincipalKind::Service => AuditActorKind::Service,
        PrincipalKind::Node => AuditActorKind::Node,
        PrincipalKind::Trigger => AuditActorKind::Trigger,
        PrincipalKind::Administrator => AuditActorKind::Administrator,
        _ => return Err(denied()),
    })
}
fn unix_now() -> u64 {
    u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |duration| duration.as_millis()),
    )
    .unwrap_or(u64::MAX)
}
