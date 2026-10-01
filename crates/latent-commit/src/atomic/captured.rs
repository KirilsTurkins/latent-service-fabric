//! Affine guest staging captures authority before any final envelope work.
use super::{
    incarnation, AdmittedCommand, AtomicError, CommandRecord, CommandTime, CompleteEnvelope,
    DurableResult, Outcome, StagedIntent,
};
use latent_core::transaction_contract::{Value, STAGED_BYTES};
use latent_effects::{
    authority::{
        CommitLink, DurableEffectAuthority, EffectAuthorityOwner, EffectScope, EffectTime,
    },
    dispatch_store::{effect_payload_key, effect_row_key, initial_due_mutation},
    payload::PayloadRecord,
};
use latent_state::{
    embedded::{ReadView, RowMutation},
    session::StatePlan,
};

/// Constructed only from the original durable Pending command claim. It holds
/// no guest store, credential, provider operation or general commit method.
pub struct IntentCaptureContext {
    record: CommandRecord,
}
pub struct CapturedIntent {
    authority: DurableEffectAuthority,
    value: Value,
}
impl AdmittedCommand {
    #[must_use]
    pub fn intent_capture_context(&self) -> IntentCaptureContext {
        IntentCaptureContext {
            record: self.record.clone(),
        }
    }
}
impl IntentCaptureContext {
    pub fn capture(
        &self,
        sequence: u32,
        intent: StagedIntent,
        effects: &EffectAuthorityOwner,
        time: CommandTime,
    ) -> Result<CapturedIntent, AtomicError> {
        if sequence >= 128 {
            return Err(AtomicError::Limit);
        }
        intent
            .payload
            .validate()
            .map_err(|_| AtomicError::Invalid)?;
        let scope = EffectScope {
            tenant: self.record.key.tenant.clone(),
            namespace: self.record.key.namespace.clone(),
            incarnation: incarnation(&self.record.key)?,
            publication: self.record.source.publication.clone(),
            binding: intent.binding,
            operation: intent.operation,
        };
        let link = CommitLink {
            command: self.record.id.hex(),
            caller_scope: self.record.key.recovery_scope.clone(),
            attempt: self.record.attempt,
            commit: self.record.disposition_id().hex(),
            effect: self.record.effect_id(sequence).hex(),
            sequence,
        };
        let authority = effects.capture_until(
            &scope,
            link,
            intent.payload.bytes.len() as u64,
            latent_effects::payload::payload_digest(&intent.payload)?,
            effect_time(time),
            intent.expires_at_millis,
        )?;
        Ok(CapturedIntent {
            authority,
            value: intent.payload,
        })
    }
}
impl CapturedIntent {
    #[must_use]
    pub fn authority(&self) -> &DurableEffectAuthority {
        &self.authority
    }
    #[must_use]
    pub fn payload_bytes(&self) -> usize {
        self.value.bytes.len()
    }
}
impl CompleteEnvelope {
    /// Real runtime path. Captured stage permission survives only as its exact
    /// immutable description and a final intersection with current authority.
    pub fn success_captured(
        view: &ReadView,
        claim: AdmittedCommand,
        state: Option<StatePlan>,
        intents: Vec<CapturedIntent>,
        value: Value,
        effects: &EffectAuthorityOwner,
        time: CommandTime,
    ) -> Result<Self, AtomicError> {
        if intents.len() > 128 {
            return Err(AtomicError::Limit);
        }
        value.validate().map_err(|_| AtomicError::Invalid)?;
        let mut bytes = value.bytes.len()
            + value.media_type.len()
            + value
                .metadata
                .iter()
                .map(|(key, value)| key.len() + value.len())
                .sum::<usize>();
        for intent in &intents {
            bytes = bytes
                .checked_add(
                    intent.value.bytes.len()
                        + intent.value.media_type.len()
                        + intent
                            .value
                            .metadata
                            .iter()
                            .map(|(key, value)| key.len() + value.len())
                            .sum::<usize>()
                        + 16_384,
                )
                .ok_or(AtomicError::Limit)?;
        }
        if bytes > STAGED_BYTES {
            return Err(AtomicError::Limit);
        }
        let version = super::writer::next_namespace_version(view, &claim.record)?;
        let token =
            super::writer::disposition_view_token(view, &claim.record, state.as_ref(), version)?;
        let result = DurableResult::new(
            &claim.record,
            Outcome::Committed,
            None,
            value,
            version,
            token,
        )?;
        let mut authorities = Vec::with_capacity(intents.len());
        let mut rows = Vec::with_capacity(intents.len() * 3);
        for (sequence, intent) in intents.into_iter().enumerate() {
            let link = intent.authority.link();
            let scope = intent.authority.scope();
            let sequence = u32::try_from(sequence).map_err(|_| AtomicError::Limit)?;
            if link.command != claim.record.id.hex()
                || link.attempt != claim.record.attempt
                || link.commit != claim.record.disposition_id().hex()
                || link.sequence != sequence
                || link.effect != claim.record.effect_id(sequence).hex()
                || link.caller_scope != claim.record.key.recovery_scope
                || scope.tenant != claim.record.key.tenant
                || scope.namespace != claim.record.key.namespace
                || scope.incarnation != incarnation(&claim.record.key)?
                || scope.publication != claim.record.source.publication
            {
                return Err(AtomicError::PermissionDenied);
            }
            let authority = effects.refresh_for_commit(&intent.authority, effect_time(time))?;
            let payload = PayloadRecord::new(&authority, intent.value)?.encode()?;
            rows.push(RowMutation {
                key: effect_row_key(&authority.link().effect)?,
                value: Some(
                    latent_effects::dispatch::EffectRecord::committed(&authority)?.encode()?,
                ),
            });
            rows.push(RowMutation {
                key: effect_payload_key(&authority.link().effect)?,
                value: Some(payload),
            });
            rows.push(initial_due_mutation(&authority)?);
            authorities.push(authority);
        }
        Self::prepare(view, claim, state, result, authorities, rows, time, None)
    }
}
fn effect_time(time: CommandTime) -> EffectTime {
    EffectTime {
        unix_millis: time.unix_millis,
        continuity_proven: time.continuity_proven,
    }
}
