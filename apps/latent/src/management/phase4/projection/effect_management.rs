use super::{bytes, c, json, selector, t, Value};

pub(super) fn plan(value: &c::EffectManagementPlan) -> Value {
    let original = value.original.as_ref().expect("validated original");
    let effect = original.effect.as_ref().expect("validated effect");
    json!({"original":{"effect":{"profile":effect.profile.as_ref().map(|p|json!({"profile":p.profile,"hostAbiDigest":p.host_abi_digest,"preparationProfileDigest":p.preparation_profile_digest})),
        "command":effect.command.as_ref().map(selector),"effectId":effect.effect_id,
        "authorizationPublication":effect.authorization_publication.as_ref().map(|p|json!({"tenant":p.tenant,"id":p.id}))},
        "operationId":original.operation_id,"mutation":c::StateMutationKind::try_from(original.mutation).expect("validated action").as_str_name(),
        "expectedVersion":bytes(&original.expected_version),"expectedPolicyDigest":original.expected_policy_digest,"reason":original.reason,"retryDelayMillis":original.retry_delay_millis.to_string()},
        "planDigest":bytes(&value.plan_digest),"managementSequence":value.management_sequence,"ownerEpoch":value.owner_epoch.to_string(),"claimGeneration":value.claim_generation.to_string(),
        "dispatchAttempt":value.dispatch_attempt,"expiresAtUnixMillis":value.expires_at_unix_millis.to_string(),"preparedAtUnixMillis":value.prepared_at_unix_millis.to_string(),
        "before":t::EffectDisposition::try_from(value.before).expect("validated disposition").as_str_name(),"safety":c::EffectPlanSafety::try_from(value.safety).expect("validated safety").as_str_name(),
        "dedupValidUntilUnixMillis":value.dedup_valid_until_unix_millis.map(|v|v.to_string())})
}
pub(super) fn receipt(value: &c::EffectManagementReceiptDetails) -> Value {
    json!({"originalPlan":value.original_plan.as_ref().map(plan),
        "before":t::EffectDisposition::try_from(value.before).expect("validated disposition").as_str_name(),
        "after":t::EffectDisposition::try_from(value.after).expect("validated disposition").as_str_name(),
        "fact":c::EffectManagementFact::try_from(value.fact).expect("validated fact").as_str_name(),
        "providerReceipt":value.provider_receipt,"providerObservedAtUnixMillis":value.provider_observed_at_unix_millis.map(|v|v.to_string())})
}
