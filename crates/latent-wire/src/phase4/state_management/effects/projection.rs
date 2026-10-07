use super::{c, native, Plan, PlatformError, Receipt, Safety};
use latent_effects::dispatch::{Disposition, EffectManagementFact};
use latent_rpc::transaction::v1 as t;

pub(super) fn plan(
    value: &Plan,
    original: &c::PlanEffectMutationRequest,
) -> Result<c::EffectManagementPlan, PlatformError> {
    let (owner_epoch, claim_generation, dispatch_attempt) =
        value.original_attempt().map_or((0, 0, 0), |attempt| {
            (
                attempt.owner_epoch(),
                attempt.claim_generation(),
                attempt.attempt(),
            )
        });
    let (safety, dedup) = match value.safety() {
        Safety::KnownNonexecution => (c::EffectPlanSafety::KnownNonexecution, None),
        Safety::QualifiedDeduplication { valid_until_millis } => (
            c::EffectPlanSafety::QualifiedDeduplication,
            Some(valid_until_millis),
        ),
        Safety::ProviderReceiptLookup => (c::EffectPlanSafety::ProviderReceiptLookup, None),
        Safety::AdministratorDeclared => (c::EffectPlanSafety::AdministratorDeclared, None),
    };
    Ok(c::EffectManagementPlan {
        original: Some(original.clone()),
        plan_digest: value.digest().map_err(native)?.to_vec(),
        management_sequence: value.sequence(),
        owner_epoch,
        claim_generation,
        dispatch_attempt,
        expires_at_unix_millis: value.expires_at_millis(),
        prepared_at_unix_millis: value.prepared_at_millis(),
        before: disposition(value.before()) as i32,
        safety: safety as i32,
        dedup_valid_until_unix_millis: dedup,
    })
}
pub(super) fn receipt(
    value: &Receipt,
    original: &c::PlanEffectMutationRequest,
) -> Result<c::StateOperationReceipt, PlatformError> {
    let native_plan = value.plan();
    let request = native_plan.request().input();
    let fact = match value.fact() {
        EffectManagementFact::RedriveScheduled => c::EffectManagementFact::RedriveScheduled,
        EffectManagementFact::ProviderConfirmed => c::EffectManagementFact::ProviderConfirmed,
        EffectManagementFact::AdministratorTerminated => {
            c::EffectManagementFact::AdministratorTerminated
        }
    };
    let after = if value.fact() == EffectManagementFact::AdministratorTerminated {
        t::EffectDisposition::AdministrativelyTerminated
    } else {
        disposition(value.after())
    };
    Ok(c::StateOperationReceipt {
        operation_id: request.operation_id.clone(),
        receipt_id: format!(
            "effect-management:sha256:{}",
            super::super::response::hex(&value.digest().map_err(native)?)
        ),
        mutation: original.mutation,
        namespace: Some(t::NamespaceSelector {
            tenant: request.actor_tenant.clone(),
            namespace: request.namespace.clone(),
            incarnation: request.incarnation.to_string(),
        }),
        authenticated_operator: request.actor_subject.clone(),
        before_version: request.expected_version.to_vec(),
        after_version: value.after_version().to_vec(),
        completed_at_unix_millis: value.completed_at_millis(),
        record_id: Some(request.effect.clone()),
        policy_digest: request.expected_policy_digest.clone(),
        disposition: c::StateOperationDisposition::Committed as i32,
        effect: Some(c::EffectManagementReceiptDetails {
            original_plan: Some(plan(native_plan, original)?),
            before: disposition(native_plan.before()) as i32,
            after: after as i32,
            fact: fact as i32,
            provider_receipt: value.provider_receipt().map(str::to_owned),
            provider_observed_at_unix_millis: value.provider_observed_at_millis(),
        }),
    })
}
const fn disposition(value: Disposition) -> t::EffectDisposition {
    match value {
        Disposition::Pending => t::EffectDisposition::Pending,
        Disposition::Dispatching => t::EffectDisposition::Dispatching,
        Disposition::ProviderAcknowledged => t::EffectDisposition::ProviderAcknowledged,
        Disposition::KnownFailed => t::EffectDisposition::KnownFailure,
        Disposition::Uncertain => t::EffectDisposition::UncertainAfterDispatch,
        Disposition::RetryScheduled => t::EffectDisposition::RetryScheduled,
        Disposition::PolicyBlocked => t::EffectDisposition::PolicyBlocked,
        Disposition::Expired => t::EffectDisposition::Expired,
        Disposition::DeadLettered => t::EffectDisposition::DeadLettered,
    }
}
