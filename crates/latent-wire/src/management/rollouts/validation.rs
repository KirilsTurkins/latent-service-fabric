use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::rollouts as domain;
use latent_core::{InvocationPrincipal, PrincipalKind, TenantId};
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Status};

use super::super::{bounds, deployment, proto, ManagementLimits, RequestBudget};

pub(super) fn deadline<T>(request: &Request<T>) -> Instant {
    let maximum = Instant::now() + Duration::from_secs(30);
    request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |deadline| deadline.min(maximum))
}

pub(super) fn completed(deadline: Instant) -> Result<(), Status> {
    if Instant::now() >= deadline {
        Err(Status::deadline_exceeded("rollout deadline exceeded"))
    } else {
        Ok(())
    }
}

pub(super) fn limits(configured: &ManagementLimits, read: bool) -> ManagementLimits {
    let mut value = configured.clone();
    value.max_request_bytes =
        value
            .max_request_bytes
            .min(if read { 8192 } else { super::MAX_REQUEST_BYTES });
    value.max_response_bytes = value.max_response_bytes.min(super::MAX_RESPONSE_BYTES);
    value.max_page_token_bytes = value.max_page_token_bytes.min(512);
    value.max_page_size = value.max_page_size.min(128);
    value.default_page_size = value.default_page_size.min(32).min(value.max_page_size);
    value
}

pub(super) fn encoded<T: Message>(value: &T, limits: &ManagementLimits) -> Result<(), Status> {
    if value.encoded_len() > limits.max_request_bytes {
        Err(bounds::exhausted())
    } else {
        Ok(())
    }
}

pub(super) fn id(value: &String, budget: &mut RequestBudget, maximum: usize) -> Result<(), Status> {
    budget.string(value, maximum)?;
    bounds::identifier(value, maximum)
}

pub(super) fn tenant(principal: &InvocationPrincipal) -> Result<TenantId, Status> {
    if principal.kind != PrincipalKind::Administrator {
        return Err(Status::permission_denied(
            "rollouts require an administrator",
        ));
    }
    let value = principal
        .tenant
        .as_ref()
        .ok_or_else(|| Status::permission_denied("rollout tenant is required"))?;
    bounds::identifier(&value.0, 256)?;
    bounds::identifier(&principal.subject, 512)?;
    Ok(TenantId(value.0.as_str().into()))
}

pub(super) fn context(
    principal: InvocationPrincipal,
    operation: proto::RolloutOperationPrecondition,
) -> Result<domain::RolloutContext, Status> {
    Ok(domain::RolloutContext {
        tenant: tenant(&principal)?,
        actor: ReleaseActor {
            subject: principal.subject.as_str().into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: domain::RolloutOperationPrecondition {
            operation_id: operation.operation_id,
            expected_revision: operation.expected_revision.expect("validated revision"),
        },
    })
}

pub(super) fn operation(
    value: Option<&proto::RolloutOperationPrecondition>,
    budget: &mut RequestBudget,
    start: bool,
    maximum_id: usize,
) -> Result<(), Status> {
    let value = value.ok_or_else(|| Status::invalid_argument("rollout operation is required"))?;
    budget.allocation::<proto::RolloutOperationPrecondition>(1)?;
    id(&value.operation_id, budget, maximum_id.min(128))?;
    let revision = value
        .expected_revision
        .ok_or_else(|| Status::invalid_argument("rollout revision is required"))?;
    if (start && revision != 0) || (!start && revision == 0) {
        return Err(Status::invalid_argument("invalid rollout revision"));
    }
    Ok(())
}

pub(super) fn start(
    value: &proto::StartRolloutRequest,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut budget = RequestBudget::new::<proto::StartRolloutRequest>(limits)?;
    id(&value.id, &mut budget, limits.max_id_bytes.min(128))?;
    id(
        &value.base_deployment_id,
        &mut budget,
        limits.max_id_bytes.min(128),
    )?;
    operation(
        value.operation.as_ref(),
        &mut budget,
        true,
        limits.max_id_bytes,
    )?;
    if value
        .expected_base_generation
        .is_none_or(|generation| generation == 0)
    {
        return Err(Status::invalid_argument(
            "positive base generation is required",
        ));
    }
    budget.sequence(&value.candidate_weights, 64)?;
    if value.candidate_weights.is_empty()
        || value.candidate_weights.last() != Some(&10_000)
        || value
            .candidate_weights
            .iter()
            .any(|weight| !(1..=10_000).contains(weight))
        || value
            .candidate_weights
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    {
        return Err(Status::invalid_argument("invalid rollout stages"));
    }
    if let Some(policy) = &value.canary_policy {
        budget.allocation::<proto::RolloutCanaryPolicy>(1)?;
        super::canary::policy::decode(policy)?;
        if value.candidate_weights.len() < 2 {
            return Err(Status::invalid_argument(
                "canary rollout requires at least two stages",
            ));
        }
    }
    let candidate = value
        .candidate
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("rollout candidate is required"))?;
    budget.allocation::<proto::Deployment>(1)?;
    deployment::validation::wire(candidate, &mut budget, limits)?;
    if candidate
        .metadata
        .as_ref()
        .and_then(|metadata| metadata.tenant.as_deref())
        != Some(tenant.0.as_str())
    {
        return Err(Status::permission_denied(
            "rollout candidate tenant does not match authenticated scope",
        ));
    }
    if candidate.generation != 0 || candidate.route_weight != value.candidate_weights[0] {
        return Err(Status::invalid_argument(
            "invalid rollout candidate generation or weight",
        ));
    }
    encoded(value, limits)
}

pub(super) fn change(
    value: &proto::ChangeRolloutRequest,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut budget = RequestBudget::new::<proto::ChangeRolloutRequest>(limits)?;
    id(&value.id, &mut budget, limits.max_id_bytes.min(128))?;
    operation(
        value.operation.as_ref(),
        &mut budget,
        false,
        limits.max_id_bytes,
    )?;
    if value.command.is_none() {
        return Err(Status::invalid_argument("rollout command is required"));
    }
    if matches!(
        &value.command,
        Some(proto::change_rollout_request::Command::Rollback(value)) if value.target_generation == 0
    ) {
        return Err(Status::invalid_argument(
            "positive rollback target generation is required",
        ));
    }
    encoded(value, limits)
}
