use super::{c, json, Value};
pub(in crate::management::phase4) fn generation(value: &c::DispatcherGeneration) -> Value {
    json!({"ownerEpoch":value.owner_epoch.to_string(),"revision":value.revision.to_string()})
}
pub(super) fn receipt(value: &c::DispatcherOperationReceipt) -> Value {
    json!({"operationId":value.operation_id,"receiptId":value.receipt_id,
        "action":c::DispatcherAction::try_from(value.action).expect("validated action").as_str_name(),
        "authenticatedOperator":value.authenticated_operator,"actorTenant":value.actor_tenant,
        "beforeGeneration":value.before_generation.as_ref().map(generation),
        "afterGeneration":value.after_generation.as_ref().map(generation),
        "observedAtUnixMillis":value.observed_at_unix_millis.to_string(),
        "clockContinuityProven":value.clock_continuity_proven,"restoreReviewRequired":value.restore_review_required,
        "disposition":c::StateOperationDisposition::try_from(value.disposition).expect("validated disposition").as_str_name()})
}
pub(super) fn snapshot(value: &c::DispatcherSnapshot) -> Value {
    json!({"generation":value.generation.as_ref().map(generation),"paused":value.paused,
        "pendingControl":value.pending_control,"restoreReviewRequired":value.restore_review_required,
        "admissionClosed":value.admission_closed,"quarantined":value.quarantined,
        "failure":c::DispatcherFailure::try_from(value.failure).expect("validated failure").as_str_name(),
        "queued":value.queued.to_string(),"activeJobs":value.active_jobs.to_string(),
        "retainedAttemptBytes":value.retained_attempt_bytes.to_string(),"liveWorkers":value.live_workers.to_string(),
        "acceptedEffects":value.accepted_effects.to_string(),"physicalOwners":value.physical_owners.to_string(),
        "quarantinedPhysicalOwners":value.quarantined_physical_owners.to_string(),"commandOwners":value.command_owners.to_string(),
        "claims":value.claims.to_string(),"pendingEffects":value.pending_effects.to_string(),
        "uncertainEffects":value.uncertain_effects.to_string(),"blockedEffects":value.blocked_effects.to_string(),
        "deadLetterEffects":value.dead_letter_effects.to_string(),
        "countsObservedAtUnixMillis":value.counts_observed_at_unix_millis.to_string(),
        "clockContinuityProven":value.clock_continuity_proven})
}
