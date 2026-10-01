//! Descriptive original plan checks. No bytes or identifier in this module
//! supplies current policy, physical retirement, or provider retry authority.
use super::{
    bounds::{digest, required, Budget},
    request as request_checks, ValidationError,
};
use crate::{control::v1 as c, transaction::v1 as t};

pub(super) fn version(b: &mut Budget, value: &Vec<u8>) -> Result<(), ValidationError> {
    b.bytes(value, 32)?;
    if value.len() != 32 || value.iter().all(|byte| *byte == 0) {
        return Err(ValidationError::Shape);
    }
    Ok(())
}

pub(super) fn request(
    b: &mut Budget,
    value: &c::PlanEffectMutationRequest,
) -> Result<(), ValidationError> {
    b.charge(std::mem::size_of::<c::PlanEffectMutationRequest>())?;
    let effect = required(value.effect.as_ref())?;
    request_checks::effect(b, effect)?;
    if effect.effect_id.len() != 64
        || !effect
            .effect_id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ValidationError::Shape);
    }
    b.id(&value.operation_id)?;
    version(b, &value.expected_version)?;
    b.string(&value.expected_policy_digest, 71)?;
    digest(&value.expected_policy_digest)?;
    request_checks::reason(b, &value.reason)?;
    match c::StateMutationKind::try_from(value.mutation) {
        Ok(c::StateMutationKind::RetryKnownFailedEffect)
            if (1..=60_000).contains(&value.retry_delay_millis) =>
        {
            Ok(())
        }
        Ok(c::StateMutationKind::ReconcileEffect | c::StateMutationKind::TerminateEffect)
            if value.retry_delay_millis == 0 =>
        {
            Ok(())
        }
        _ => Err(ValidationError::Shape),
    }
}

pub(super) fn plan(b: &mut Budget, value: &c::EffectManagementPlan) -> Result<(), ValidationError> {
    b.charge(std::mem::size_of::<c::EffectManagementPlan>())?;
    let original = required(value.original.as_ref())?;
    request(b, original)?;
    version(b, &value.plan_digest)?;
    if !(1..=128).contains(&value.management_sequence)
        || value.prepared_at_unix_millis == 0
        || value.expires_at_unix_millis <= value.prepared_at_unix_millis
        || value.expires_at_unix_millis - value.prepared_at_unix_millis > 30_000
        || value.dispatch_attempt > 128
        || !matches!(
            (
                value.owner_epoch,
                value.claim_generation,
                value.dispatch_attempt
            ),
            (0, 0, 0) | (1.., 1.., 1..)
        )
    {
        return Err(ValidationError::Shape);
    }
    let before =
        t::EffectDisposition::try_from(value.before).map_err(|_| ValidationError::Shape)?;
    let safety = c::EffectPlanSafety::try_from(value.safety).map_err(|_| ValidationError::Shape)?;
    let original_attempt = value.dispatch_attempt > 0;
    let valid = match (
        c::StateMutationKind::try_from(original.mutation).map_err(|_| ValidationError::Shape)?,
        safety,
    ) {
        (c::StateMutationKind::RetryKnownFailedEffect, c::EffectPlanSafety::KnownNonexecution) => {
            original_attempt && before == t::EffectDisposition::KnownFailure
        }
        (
            c::StateMutationKind::RetryKnownFailedEffect,
            c::EffectPlanSafety::QualifiedDeduplication,
        ) => {
            original_attempt
                && matches!(
                    before,
                    t::EffectDisposition::KnownFailure
                        | t::EffectDisposition::UncertainAfterDispatch
                )
        }
        (c::StateMutationKind::ReconcileEffect, c::EffectPlanSafety::ProviderReceiptLookup) => {
            original_attempt
                && matches!(
                    before,
                    t::EffectDisposition::KnownFailure
                        | t::EffectDisposition::UncertainAfterDispatch
                )
        }
        (c::StateMutationKind::TerminateEffect, c::EffectPlanSafety::AdministratorDeclared) => {
            matches!(
                before,
                t::EffectDisposition::Pending
                    | t::EffectDisposition::KnownFailure
                    | t::EffectDisposition::UncertainAfterDispatch
                    | t::EffectDisposition::PolicyBlocked
                    | t::EffectDisposition::RetryScheduled
            )
        }
        _ => false,
    };
    if !valid
        || (safety == c::EffectPlanSafety::QualifiedDeduplication)
            != value.dedup_valid_until_unix_millis.is_some()
    {
        return Err(ValidationError::Shape);
    }
    if let Some(until) = value.dedup_valid_until_unix_millis {
        if until <= value.expires_at_unix_millis {
            return Err(ValidationError::Shape);
        }
    }
    // Expiry is enforced by creation/application, never by historical decoding.
    Ok(())
}

pub(super) fn mutation_association(
    value: &c::MutateStateRequest,
    plan: &c::EffectManagementPlan,
) -> Result<(), ValidationError> {
    let original = required(plan.original.as_ref())?;
    let namespace = required(value.namespace.as_ref())?;
    let effect = required(original.effect.as_ref())?;
    if namespace.namespace != required(effect.command.as_ref())?.namespace
        || namespace.authorization_publication != effect.authorization_publication
        || namespace.profile != effect.profile
        || value.operation_id != original.operation_id
        || value.mutation != original.mutation
        || value.record_id.as_ref() != Some(&effect.effect_id)
        || value.expected_version != original.expected_version
        || value.expected_policy_digest != original.expected_policy_digest
        || value.reason != original.reason
    {
        return Err(ValidationError::Association);
    }
    Ok(())
}

pub(super) fn recovery_association(
    value: &c::GetStateOperationReceiptRequest,
    plan: &c::EffectManagementPlan,
) -> Result<(), ValidationError> {
    let original = required(plan.original.as_ref())?;
    let namespace = required(value.namespace.as_ref())?;
    let effect = required(original.effect.as_ref())?;
    if namespace.namespace != required(effect.command.as_ref())?.namespace
        || namespace.profile != effect.profile
        || value.operation_id != original.operation_id
    {
        return Err(ValidationError::Association);
    }
    // The requested current publication may legitimately differ from the
    // historical original access selector. It does not revive that old grant.
    Ok(())
}

pub(super) fn receipt(
    b: &mut Budget,
    value: &c::StateOperationReceipt,
    expected: &c::EffectManagementPlan,
) -> Result<(), ValidationError> {
    let details = required(value.effect.as_ref())?;
    b.charge(std::mem::size_of::<c::EffectManagementReceiptDetails>())?;
    let actual = required(details.original_plan.as_ref())?;
    plan(b, actual)?;
    let original = required(actual.original.as_ref())?;
    if actual != expected
        || value.mutation != original.mutation
        || value.operation_id != original.operation_id
        || value.record_id.as_ref() != Some(&required(original.effect.as_ref())?.effect_id)
        || value.before_version != original.expected_version
        || value.policy_digest != original.expected_policy_digest
        || details.before != actual.before
    {
        return Err(ValidationError::Association);
    }
    version(b, &value.before_version)?;
    version(b, &value.after_version)?;
    if value.disposition != c::StateOperationDisposition::Committed as i32
        || value.completed_at_unix_millis < actual.prepared_at_unix_millis
        || value.completed_at_unix_millis >= actual.expires_at_unix_millis
    {
        return Err(ValidationError::Shape);
    }
    let valid = matches!(
        (
            c::EffectManagementFact::try_from(details.fact),
            c::StateMutationKind::try_from(original.mutation),
            t::EffectDisposition::try_from(details.after)
        ),
        (
            Ok(c::EffectManagementFact::RedriveScheduled),
            Ok(c::StateMutationKind::RetryKnownFailedEffect),
            Ok(t::EffectDisposition::RetryScheduled)
        ) | (
            Ok(c::EffectManagementFact::ProviderConfirmed),
            Ok(c::StateMutationKind::ReconcileEffect),
            Ok(t::EffectDisposition::ProviderAcknowledged)
        ) | (
            Ok(c::EffectManagementFact::AdministratorTerminated),
            Ok(c::StateMutationKind::TerminateEffect),
            Ok(t::EffectDisposition::AdministrativelyTerminated
                | t::EffectDisposition::DeadLettered)
        )
    );
    if !valid
        || (details.fact == c::EffectManagementFact::ProviderConfirmed as i32)
            != details.provider_receipt.is_some()
        || details.provider_receipt.is_some() != details.provider_observed_at_unix_millis.is_some()
    {
        return Err(ValidationError::Shape);
    }
    b.optional_id(details.provider_receipt.as_ref())?;
    if details
        .provider_observed_at_unix_millis
        .is_some_and(|time| time == 0 || time > value.completed_at_unix_millis)
    {
        return Err(ValidationError::Shape);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
