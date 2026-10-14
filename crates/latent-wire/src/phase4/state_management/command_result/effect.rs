use super::{
    contract, denied, missing, unsupported, CommandRecord, CommandTime, Outcome, ReadError,
};
use latent_effects::{
    authority::DurableEffectAuthority,
    dispatch::{Disposition, EffectManagementFact},
    dispatch_store::DispatchCatalog,
};
use latent_rpc::transaction::v1 as t;
use latent_state::embedded::ReadView;

pub(super) fn response(
    view: &ReadView,
    command: &CommandRecord,
    request: &t::GetEffectRequest,
    time: CommandTime,
) -> Result<contract::Response, ReadError> {
    match command.outcome() {
        Outcome::Committed => {}
        Outcome::Pending => return Err(unsupported().into()),
        Outcome::Rejected | Outcome::Aborted => return Err(missing().into()),
    }
    if !command
        .effect_ids()
        .iter()
        .any(|effect| effect.hex() == request.effect_id)
    {
        return Err(denied().into());
    }
    let inspection =
        DispatchCatalog::inspect_effect(view, &request.effect_id)?.ok_or_else(missing)?;
    let record = &inspection.record;
    let authority = record.authority().map_err(|_| unsupported())?;
    associated(command, request, &authority)?;
    let link = authority.link();
    if !time.continuity_proven || time.unix_millis < inspection.occurred_at_millis {
        return Err(unsupported().into());
    }
    let managed = record.management();
    let administratively_terminated =
        managed.is_some_and(|stamp| stamp.fact() == EffectManagementFact::AdministratorTerminated);
    let disposition = if administratively_terminated {
        t::EffectDisposition::AdministrativelyTerminated
    } else {
        disposition(record.disposition())
    };
    let provider_receipt = if record.disposition() == Disposition::ProviderAcknowledged {
        managed
            .and_then(|stamp| stamp.provider_receipt().map(str::to_owned))
            .or_else(|| {
                record
                    .latest()
                    .and_then(|receipt| receipt.provider_receipt.clone())
            })
    } else {
        None
    };
    let (record_format, format_version) = record.durable_format();
    Ok(t::GetEffectResponse {
        effect: Some(t::EffectReceipt {
            effect_id: link.effect.clone(),
            command_id: link.command.clone(),
            command_attempt_id: link.attempt.to_string(),
            dispatch_attempt: record.attempts(),
            disposition: disposition as i32,
            provider_receipt,
            failure_code: failure_code(disposition).map(str::to_owned),
            occurred_at_unix_millis: inspection.occurred_at_millis,
            retention: Some(t::LinkedRetention {
                record_format: record_format.into(),
                record_version: format_version,
                payload_expires_at_unix_millis: Some(authority.expires_at_millis()),
                identity_expires_at_unix_millis: Some(command.identity_expires()),
                remaining_recovery_millis: None,
                required_record_ids: vec![
                    command.id().hex(),
                    command.attempt_id().hex(),
                    command.transaction_id().hex(),
                    link.effect.clone(),
                ],
                payload_available: inspection.payload_available,
            }),
            management_operation_receipt_id: inspection.management_receipt_digest.map(|digest| {
                format!(
                    "effect-management:sha256:{}",
                    super::super::response::hex(&digest)
                )
            }),
            provider_profile: authority.profile().adapter.clone(),
            record_version: inspection.record_version.to_vec(),
            owner_epoch: (record.owner_epoch() != 0).then_some(record.owner_epoch()),
            claim_generation: (record.claim_generation() != 0).then_some(record.claim_generation()),
        }),
    }
    .into())
}

fn associated(
    command: &CommandRecord,
    request: &t::GetEffectRequest,
    authority: &DurableEffectAuthority,
) -> Result<(), ReadError> {
    let scope = authority.scope();
    let link = authority.link();
    if scope.tenant != command.key().tenant
        || scope.namespace != command.key().namespace
        || scope.incarnation.to_string() != command.key().incarnation
        || scope.publication != command.source().publication
        || link.command != command.id().hex()
        || link.caller_scope != command.key().recovery_scope
        || link.attempt != command.attempt()
        || link.commit != command.disposition_id().hex()
        || link.effect != request.effect_id
        || link.sequence >= 128
        || command.effect_id(link.sequence).hex() != request.effect_id
        || !command
            .effect_ids()
            .contains(&command.effect_id(link.sequence))
    {
        return Err(denied().into());
    }
    Ok(())
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

const fn failure_code(value: t::EffectDisposition) -> Option<&'static str> {
    match value {
        t::EffectDisposition::KnownFailure => Some("provider-failure"),
        t::EffectDisposition::UncertainAfterDispatch => Some("delivery-uncertain"),
        t::EffectDisposition::PolicyBlocked => Some("policy-blocked"),
        t::EffectDisposition::Expired => Some("effect-expired"),
        t::EffectDisposition::AdministrativelyTerminated => Some("administratively-terminated"),
        t::EffectDisposition::DeadLettered => Some("dead-lettered"),
        _ => None,
    }
}
