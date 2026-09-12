use crate::management::phase2::{invalid_input, invalid_response, projection::Project, proto};
use crate::{client::Session, error::Failure, operation::Operation, output::Outcome};
use proto::rollout_service_client::RolloutServiceClient;

pub(super) async fn execute(operation: Operation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        Operation::StartRollout(request) => start(request, session).await,
        Operation::ChangeRollout(request) => change(request, session).await,
        Operation::GetRollout(request) => get(request, session).await,
        Operation::ListRollouts(request) => list(request, session).await,
        Operation::LookupRolloutReceipt(request) => get_receipt(request, session).await,
        Operation::EvaluateRollout(request) => evaluate(request, session).await,
        _ => Err(invalid_input()),
    }
}
fn receipt(
    value: Option<&proto::RolloutOperationReceipt>,
    session: &Session,
    id: &str,
    op: &proto::RolloutOperationPrecondition,
    action: proto::RolloutAction,
) -> Result<(), Failure> {
    let value = value.ok_or_else(invalid_response)?;
    receipt_identity(value, session, id, &op.operation_id)?;
    if Some(value.expected_revision) != op.expected_revision
        || value.action != action as i32
        || value.revision
            != value
                .expected_revision
                .checked_add(1)
                .ok_or_else(invalid_response)?
    {
        return Err(invalid_response());
    }
    Ok(())
}
fn receipt_identity(
    value: &proto::RolloutOperationReceipt,
    session: &Session,
    id: &str,
    op: &str,
) -> Result<(), Failure> {
    if value.tenant != session.tenant()
        || value.rollout_id != id
        || value.operation_id != op
        || value.actor.is_none()
        || value.outcome != proto::RolloutOperationOutcome::Committed as i32
        || value.revision == 0
        || value.step >= 64
        || [
            &value.request_digest,
            &value.receipt_digest,
            &value.plan_digest,
        ]
        .iter()
        .any(|v| !crate::management::canonical_digest(v))
    {
        return Err(invalid_response());
    }
    Ok(())
}
fn status(value: &proto::RolloutStatus, session: &Session) -> Result<(), Failure> {
    if value.tenant != session.tenant()
        || value.revision == 0
        || value.base.is_none()
        || value.candidate.is_none()
        || value.objects.len() != 2
        || value.candidate_weights.is_empty()
        || value.candidate_weights.last() != Some(&10000)
        || value.current_step as usize >= value.candidate_weights.len()
        || value.candidate_weights.windows(2).any(|v| v[0] >= v[1])
        || !crate::management::canonical_digest(&value.plan_digest)
    {
        return Err(invalid_response());
    }
    Ok(())
}

async fn start(request: proto::StartRolloutRequest, session: &Session) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let op = request
        .operation
        .as_ref()
        .ok_or_else(invalid_input)?
        .clone();
    let value = call!(session, RolloutServiceClient, start_rollout, request);
    receipt(
        value.receipt.as_ref(),
        session,
        &id,
        &op,
        proto::RolloutAction::Start,
    )?;
    let known = value.durability == proto::RolloutDurability::Confirmed as i32;
    let mut output = Outcome::success(value.project());
    output.outcome_known = known;
    Ok(output)
}

async fn change(
    request: proto::ChangeRolloutRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let op = request
        .operation
        .as_ref()
        .ok_or_else(invalid_input)?
        .clone();
    let (action, step, target) = match &request.command {
        Some(proto::change_rollout_request::Command::Advance(v)) => {
            (proto::RolloutAction::Advance, Some(v.next_step), None)
        }
        Some(proto::change_rollout_request::Command::Promote(v)) => {
            (proto::RolloutAction::Promote, Some(v.next_step), None)
        }
        Some(proto::change_rollout_request::Command::Rollback(v)) => (
            proto::RolloutAction::Rollback,
            None,
            Some(v.target_generation),
        ),
        Some(proto::change_rollout_request::Command::Pause(_)) => {
            (proto::RolloutAction::Pause, None, None)
        }
        Some(proto::change_rollout_request::Command::Resume(_)) => {
            (proto::RolloutAction::Resume, None, None)
        }
        Some(proto::change_rollout_request::Command::Abort(_)) => {
            (proto::RolloutAction::Abort, None, None)
        }
        None => return Err(invalid_input()),
    };
    let value = call!(session, RolloutServiceClient, change_rollout, request);
    receipt(value.receipt.as_ref(), session, &id, &op, action)?;
    let receipt = value.receipt.as_ref().ok_or_else(invalid_response)?;
    if step.is_some_and(|step| receipt.step != step)
        || target.is_some_and(|target| {
            receipt
                .rollback_target
                .as_ref()
                .is_none_or(|v| v.historical_route_generation != target)
        })
    {
        return Err(invalid_response());
    }
    let known = value.durability == proto::RolloutDurability::Confirmed as i32;
    let mut output = Outcome::success(value.project());
    output.outcome_known = known;
    Ok(output)
}

async fn get(request: proto::GetRolloutRequest, session: &Session) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let value = call!(session, RolloutServiceClient, get_rollout, request);
    if let Some(value) = &value.status {
        status(value, session)?;
        if value.id != id {
            return Err(invalid_response());
        }
    }
    let found = value.status.is_some();
    Ok(if found {
        Outcome::success(value.project())
    } else {
        Outcome::not_found(value.project())
    })
}

async fn list(request: proto::ListRolloutsRequest, session: &Session) -> Result<Outcome, Failure> {
    let service = request.service.clone();
    let state = request.state;
    let count = request.page.as_ref().map_or(0, |p| p.page_size);
    let value = call!(session, RolloutServiceClient, list_rollouts, request);
    if value.page.is_none() {
        return Err(invalid_response());
    }
    crate::management::association::page_count(value.rollouts.len(), count)?;
    for row in &value.rollouts {
        status(row, session)?;
        if service.as_ref().is_some_and(|v| v != &row.service)
            || state.is_some_and(|v| v != row.state)
        {
            return Err(invalid_response());
        }
    }
    Ok(Outcome::success(value.project()))
}

async fn get_receipt(
    request: proto::GetRolloutOperationRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let op = request.operation_id.clone();
    let value = call!(
        session,
        RolloutServiceClient,
        get_rollout_operation,
        request
    );
    let found = value.disposition == proto::RolloutOperationLookupDisposition::Found as i32;
    if found != value.receipt.is_some() {
        return Err(invalid_response());
    }
    if let Some(value) = &value.receipt {
        receipt_identity(value, session, &id, &op)?;
    }
    let mut output = Outcome::success(value.project());
    output.outcome_known = found;
    Ok(output)
}

async fn evaluate(
    request: proto::EvaluateRolloutRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let revision = request.expected_revision;
    let value = call!(session, RolloutServiceClient, evaluate_rollout, request);
    let report = value.report.as_ref().ok_or_else(invalid_response)?;
    if report.rollout_id != id
        || Some(report.revision) != revision
        || report.revisions.len() > 2
        || report.observation.is_none()
        || !crate::management::canonical_digest(&report.policy_digest)
    {
        return Err(invalid_response());
    }
    for revision in &report.revisions {
        if revision.counters.is_none()
            || !crate::management::canonical_digest(&revision.component_digest)
        {
            return Err(invalid_response());
        }
    }
    Ok(Outcome::success(value.project()))
}
