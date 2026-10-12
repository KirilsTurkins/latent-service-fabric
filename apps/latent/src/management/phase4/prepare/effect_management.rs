use super::{c, decode, effect, invalid, target, Request, ResolvedConfig, STANDARD};
use crate::{
    args::phase4::{EffectMutationAction, EffectPlanArgs, PlanEffectArgs},
    error::Failure,
};
use base64::Engine;
use prost::Message;

fn action(value: EffectMutationAction) -> c::StateMutationKind {
    match value {
        EffectMutationAction::Redrive => c::StateMutationKind::RetryKnownFailedEffect,
        EffectMutationAction::Reconcile => c::StateMutationKind::ReconcileEffect,
        EffectMutationAction::Terminate => c::StateMutationKind::TerminateEffect,
    }
}
pub(super) fn plan(args: &PlanEffectArgs, config: &ResolvedConfig) -> Result<Request, Failure> {
    Ok(c::PlanEffectMutationRequest {
        effect: Some(effect(&args.effect, config)),
        operation_id: args.operation_id.clone(),
        mutation: action(args.action) as i32,
        expected_version: decode(&args.expected_version)?,
        expected_policy_digest: args.expected_policy_digest.clone(),
        reason: args.reason.clone(),
        retry_delay_millis: args.retry_delay_millis.unwrap_or(0),
    }
    .into())
}
fn decode_plan(args: &EffectPlanArgs) -> Result<c::EffectManagementPlan, Failure> {
    if args.plan.len() > 21_848 {
        return Err(invalid());
    }
    let bytes = STANDARD.decode(&args.plan).map_err(|_| invalid())?;
    if bytes.len() > 16 * 1024 || STANDARD.encode(&bytes) != args.plan {
        return Err(invalid());
    }
    let plan = c::EffectManagementPlan::decode(bytes.as_slice()).map_err(|_| invalid())?;
    if plan.encode_to_vec() != bytes {
        return Err(invalid());
    }
    Ok(plan)
}
pub(super) fn apply(args: &EffectPlanArgs, config: &ResolvedConfig) -> Result<Request, Failure> {
    let plan = decode_plan(args)?;
    let original = plan.original.as_ref().ok_or_else(invalid)?;
    let effect = original.effect.as_ref().ok_or_else(invalid)?;
    Ok(c::MutateStateRequest {
        namespace: Some(target(&args.target, config)),
        operation_id: original.operation_id.clone(),
        mutation: original.mutation,
        expected_version: original.expected_version.clone(),
        expected_policy_digest: original.expected_policy_digest.clone(),
        reason: original.reason.clone(),
        record_id: Some(effect.effect_id.clone()),
        effect_plan: Some(plan),
    }
    .into())
}
pub(super) fn receipt(args: &EffectPlanArgs, config: &ResolvedConfig) -> Result<Request, Failure> {
    let plan = decode_plan(args)?;
    let original = plan.original.as_ref().ok_or_else(invalid)?;
    Ok(c::GetStateOperationReceiptRequest {
        namespace: Some(target(&args.target, config)),
        operation_id: original.operation_id.clone(),
        original_effect_plan: Some(plan),
    }
    .into())
}
