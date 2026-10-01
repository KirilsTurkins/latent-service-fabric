use super::{
    codec::{Decoder, Encoder, METADATA_BYTES, RESULT_BYTES},
    command_identity, id, incarnation, AtomicError, Identity, Outcome, ReplayPolicy, ResultPolicy,
};
use latent_core::transaction_contract::{CommandKey, Value};
use latent_state::embedded::{Family, RowKey};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceIdentity {
    pub publication: String,
    pub revision: String,
    pub release_digest: String,
    pub component_digest: String,
    pub contract_digest: String,
    pub route_generation: u64,
    pub state_schema: String,
    pub input_format: String,
    pub result_format: String,
}
impl SourceIdentity {
    pub fn validate(&self) -> Result<(), AtomicError> {
        for text in [
            &self.publication,
            &self.revision,
            &self.state_schema,
            &self.input_format,
            &self.result_format,
        ] {
            id(text)?;
        }
        for text in [
            &self.release_digest,
            &self.component_digest,
            &self.contract_digest,
            &self.state_schema,
        ] {
            let digest = text.strip_prefix("sha256:").ok_or(AtomicError::Invalid)?;
            if digest.len() != 64
                || !digest
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            {
                return Err(AtomicError::Invalid);
            }
        }
        if self.route_generation == 0 {
            return Err(AtomicError::Invalid);
        }
        Ok(())
    }
    fn encode(&self, out: &mut Encoder) -> Result<(), AtomicError> {
        self.validate()?;
        for text in [
            &self.publication,
            &self.revision,
            &self.release_digest,
            &self.component_digest,
            &self.contract_digest,
            &self.state_schema,
            &self.input_format,
            &self.result_format,
        ] {
            out.text(text)?;
        }
        out.number(self.route_generation);
        Ok(())
    }
    fn decode(input: &mut Decoder<'_>) -> Result<Self, AtomicError> {
        let source = Self {
            publication: input.text(256)?,
            revision: input.text(256)?,
            release_digest: input.text(71)?,
            component_digest: input.text(71)?,
            contract_digest: input.text(71)?,
            state_schema: input.text(256)?,
            input_format: input.text(256)?,
            result_format: input.text(256)?,
            route_generation: input.number()?,
        };
        source.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(source)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InboxIdentity {
    pub provider: String,
    pub binding: String,
    pub message: String,
    pub payload_digest: Identity,
}
impl InboxIdentity {
    pub fn validate(&self) -> Result<(), AtomicError> {
        for text in [&self.provider, &self.binding, &self.message] {
            id(text)?;
        }
        Ok(())
    }
    pub fn row_key(&self, key: &CommandKey) -> Result<RowKey, AtomicError> {
        self.validate()?;
        let inc = incarnation(key)?.to_le_bytes();
        let identity = Identity::derive(
            b"lsf-inbox-key-v1\0",
            &[
                key.tenant.as_bytes(),
                key.namespace.as_bytes(),
                &inc,
                self.provider.as_bytes(),
                self.binding.as_bytes(),
                self.message.as_bytes(),
            ],
        );
        Ok(row_key(Family::Inbox, b"inbox-v1\0", identity, None))
    }
    fn encode(&self, out: &mut Encoder) -> Result<(), AtomicError> {
        for text in [&self.provider, &self.binding, &self.message] {
            out.text(text)?;
        }
        out.identity(self.payload_digest);
        Ok(())
    }
    fn decode(input: &mut Decoder<'_>) -> Result<Self, AtomicError> {
        let inbox = Self {
            provider: input.text(256)?,
            binding: input.text(256)?,
            message: input.text(256)?,
            payload_digest: input.identity()?,
        };
        inbox.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(inbox)
    }
}

/// Immutable original business scope/source and generation-checked disposition.
/// History uses one bounded row per attempt; bodies are separate result records.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandRecord {
    pub(super) key: CommandKey,
    pub(super) id: Identity,
    pub(super) fingerprint: Identity,
    pub(super) source: SourceIdentity,
    pub(super) result_read_policy: String,
    pub(super) result_policy: ResultPolicy,
    pub(super) admitted_at: u64,
    pub(super) clock_floor: u64,
    pub(super) result_expires: u64,
    pub(super) identity_expires: u64,
    pub(super) owner_epoch: u64,
    pub(super) attempt: u64,
    pub(super) outcome: Outcome,
    pub(super) completed_at: u64,
    pub(super) result_digest: Identity,
    pub(super) effects: Vec<Identity>,
    pub(super) inbox: Option<InboxIdentity>,
    pub(super) abort_proof: Option<Identity>,
}
impl CommandRecord {
    #[must_use]
    pub fn key(&self) -> &CommandKey {
        &self.key
    }
    #[must_use]
    pub const fn id(&self) -> Identity {
        self.id
    }
    #[must_use]
    pub const fn fingerprint(&self) -> Identity {
        self.fingerprint
    }
    #[must_use]
    pub fn source(&self) -> &SourceIdentity {
        &self.source
    }
    #[must_use]
    pub fn result_read_policy(&self) -> &str {
        &self.result_read_policy
    }
    #[must_use]
    pub const fn outcome(&self) -> Outcome {
        self.outcome
    }
    #[must_use]
    pub const fn attempt(&self) -> u64 {
        self.attempt
    }
    #[must_use]
    pub fn effect_ids(&self) -> &[Identity] {
        &self.effects
    }
    #[must_use]
    pub const fn result_expires(&self) -> u64 {
        self.result_expires
    }
    #[must_use]
    pub const fn owner_epoch(&self) -> u64 {
        self.owner_epoch
    }
    #[must_use]
    pub const fn clock_floor(&self) -> u64 {
        self.clock_floor
    }
    #[must_use]
    pub const fn identity_expires(&self) -> u64 {
        self.identity_expires
    }
    #[must_use]
    pub const fn abort_proof(&self) -> Option<Identity> {
        self.abort_proof
    }
    #[must_use]
    pub fn transaction_id(&self) -> Identity {
        Identity::derive(
            b"lsf-transaction-v1\0",
            &[
                &self.id.0,
                &self.attempt.to_le_bytes(),
                &self.owner_epoch.to_le_bytes(),
            ],
        )
    }
    #[must_use]
    pub fn attempt_id(&self) -> Identity {
        Identity::derive(
            b"lsf-attempt-v1\0",
            &[&self.id.0, &self.attempt.to_le_bytes()],
        )
    }
    #[must_use]
    pub fn disposition_id(&self) -> Identity {
        Identity::derive(b"lsf-disposition-v1\0", &[&self.transaction_id().0])
    }
    #[must_use]
    pub fn effect_id(&self, sequence: u32) -> Identity {
        Identity::derive(
            b"lsf-effect-v1\0",
            &[&self.transaction_id().0, &sequence.to_le_bytes()],
        )
    }
    pub fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        self.validate()?;
        let mut out = Encoder::new(b"LCM\0\x01");
        for text in [
            &self.key.tenant,
            &self.key.namespace,
            &self.key.incarnation,
            &self.key.recovery_scope,
            &self.key.operation,
            &self.key.client_key,
        ] {
            out.text(text)?;
        }
        out.optional(self.key.entity.as_deref())?;
        out.identity(self.id);
        out.identity(self.fingerprint);
        self.source.encode(&mut out)?;
        out.text(&self.result_read_policy)?;
        out.policy(self.result_policy);
        for number in [
            self.admitted_at,
            self.clock_floor,
            self.result_expires,
            self.identity_expires,
            self.owner_epoch,
            self.attempt,
            self.completed_at,
        ] {
            out.number(number);
        }
        out.0.push(outcome_tag(self.outcome));
        out.identity(self.result_digest);
        out.0
            .push(u8::try_from(self.effects.len()).map_err(|_| AtomicError::Limit)?);
        for effect in &self.effects {
            out.identity(*effect);
        }
        out.0.push(u8::from(self.inbox.is_some()));
        if let Some(inbox) = &self.inbox {
            inbox.encode(&mut out)?;
        }
        out.0.push(u8::from(self.abort_proof.is_some()));
        if let Some(proof) = self.abort_proof {
            out.identity(proof);
        }
        out.finish(METADATA_BYTES)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LCM\0\x01", METADATA_BYTES)?;
        let key = CommandKey {
            tenant: input.text(256)?,
            namespace: input.text(256)?,
            incarnation: input.text(256)?,
            recovery_scope: input.text(256)?,
            operation: input.text(256)?,
            client_key: input.text(256)?,
            entity: input.optional()?,
        };
        let id = input.identity()?;
        let fingerprint = input.identity()?;
        let source = SourceIdentity::decode(&mut input)?;
        let result_read_policy = input.text(256)?;
        let result_policy = input.policy()?;
        let admitted_at = input.number()?;
        let clock_floor = input.number()?;
        let result_expires = input.number()?;
        let identity_expires = input.number()?;
        let owner_epoch = input.number()?;
        let attempt = input.number()?;
        let completed_at = input.number()?;
        let outcome = decode_outcome(input.byte()?)?;
        let result_digest = input.identity()?;
        let count = usize::from(input.byte()?);
        if count > 128 {
            return Err(AtomicError::Corrupt);
        }
        let mut effects = Vec::with_capacity(count);
        for _ in 0..count {
            effects.push(input.identity()?);
        }
        let inbox = match input.byte()? {
            0 => None,
            1 => Some(InboxIdentity::decode(&mut input)?),
            _ => return Err(AtomicError::Corrupt),
        };
        let abort_proof = match input.byte()? {
            0 => None,
            1 => Some(input.identity()?),
            _ => return Err(AtomicError::Corrupt),
        };
        input.finish()?;
        let record = Self {
            key,
            id,
            fingerprint,
            source,
            result_read_policy,
            result_policy,
            admitted_at,
            clock_floor,
            result_expires,
            identity_expires,
            owner_epoch,
            attempt,
            outcome,
            completed_at,
            result_digest,
            effects,
            inbox,
            abort_proof,
        };
        record.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(record)
    }
    fn validate(&self) -> Result<(), AtomicError> {
        self.source.validate()?;
        id(&self.result_read_policy)?;
        self.result_policy.validate()?;
        if self.clock_floor < self.admitted_at
            || self.completed_at > self.clock_floor
            || self.id != command_identity(&self.key)?
            || self.owner_epoch == 0
            || self.attempt == 0
            || self.attempt > self.result_policy.maximum_attempts
            || self.result_expires
                != self
                    .admitted_at
                    .checked_add(self.result_policy.result_millis)
                    .ok_or(AtomicError::Invalid)?
            || self.identity_expires
                != self
                    .admitted_at
                    .checked_add(self.result_policy.identity_millis)
                    .ok_or(AtomicError::Invalid)?
            || self.effects.len() > 128
        {
            return Err(AtomicError::Invalid);
        }
        if self.outcome == Outcome::Pending {
            if self.completed_at != 0
                || !self.effects.is_empty()
                || self.abort_proof.is_some()
                || self.result_digest != Identity([0; 32])
            {
                return Err(AtomicError::Invalid);
            }
        } else if self.completed_at < self.admitted_at
            || (self.outcome == Outcome::Aborted) != self.abort_proof.is_some()
            || (self.outcome != Outcome::Committed && !self.effects.is_empty())
        {
            return Err(AtomicError::Invalid);
        }
        for (sequence, effect) in self.effects.iter().enumerate() {
            if *effect != self.effect_id(u32::try_from(sequence).map_err(|_| AtomicError::Limit)?) {
                return Err(AtomicError::Invalid);
            }
        }
        if let Some(inbox) = &self.inbox {
            inbox.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DurableResult {
    pub(super) command: Identity,
    pub(super) attempt: u64,
    pub(super) transaction: Identity,
    pub(super) outcome: Outcome,
    pub(super) code: Option<String>,
    pub(super) digest: Identity,
    pub(super) value: Option<Value>,
}
impl DurableResult {
    pub(super) fn new(
        record: &CommandRecord,
        outcome: Outcome,
        code: Option<String>,
        value: Value,
    ) -> Result<Self, AtomicError> {
        value.validate().map_err(|_| AtomicError::Limit)?;
        if value.bytes.len() > record.result_policy.maximum_result_bytes
            || outcome == Outcome::Pending
            || (outcome == Outcome::Committed) != code.is_none()
        {
            return Err(AtomicError::Invalid);
        }
        if let Some(code) = &code {
            id(code)?;
        }
        let digest = result_payload_digest(outcome, code.as_deref(), &value)?;
        Ok(Self {
            command: record.id,
            attempt: record.attempt,
            transaction: record.transaction_id(),
            outcome,
            code,
            digest,
            value: if record.result_policy.replay == ReplayPolicy::Full {
                Some(value)
            } else {
                None
            },
        })
    }
    #[must_use]
    pub fn value(&self) -> Option<&Value> {
        self.value.as_ref()
    }
    #[must_use]
    pub const fn outcome(&self) -> Outcome {
        self.outcome
    }
    #[must_use]
    pub fn code(&self) -> Option<&str> {
        self.code.as_deref()
    }
    pub fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        let mut out = Encoder::new(b"LCR\0\x01");
        out.identity(self.command);
        out.number(self.attempt);
        out.identity(self.transaction);
        out.0.push(outcome_tag(self.outcome));
        out.optional(self.code.as_deref())?;
        out.identity(self.digest);
        out.0.push(u8::from(self.value.is_some()));
        if let Some(value) = &self.value {
            out.value(value)?;
        }
        out.finish(RESULT_BYTES)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LCR\0\x01", RESULT_BYTES)?;
        let command = input.identity()?;
        let attempt = input.number()?;
        let transaction = input.identity()?;
        let outcome = decode_outcome(input.byte()?)?;
        let code = input.optional()?;
        let digest = input.identity()?;
        let value = match input.byte()? {
            0 => None,
            1 => Some(input.value()?),
            _ => return Err(AtomicError::Corrupt),
        };
        input.finish()?;
        if attempt == 0
            || outcome == Outcome::Pending
            || (outcome == Outcome::Committed) != code.is_none()
        {
            return Err(AtomicError::Corrupt);
        }
        if let Some(code) = &code {
            id(code).map_err(|_| AtomicError::Corrupt)?;
        }
        let result = Self {
            command,
            attempt,
            transaction,
            outcome,
            code,
            digest,
            value,
        };
        if let Some(value) = &result.value {
            if result_payload_digest(result.outcome, result.code.as_deref(), value)?
                != result.digest
            {
                return Err(AtomicError::Corrupt);
            }
        }
        Ok(result)
    }
    pub fn verify(&self, record: &CommandRecord) -> Result<(), AtomicError> {
        if self.command != record.id
            || self.attempt != record.attempt
            || self.transaction != record.transaction_id()
            || self.outcome != record.outcome
            || self.digest != record.result_digest
            || (record.result_policy.replay == ReplayPolicy::Full) != self.value.is_some()
        {
            return Err(AtomicError::Corrupt);
        }
        if let Some(value) = &self.value {
            if value.bytes.len() > record.result_policy.maximum_result_bytes
                || result_payload_digest(self.outcome, self.code.as_deref(), value)? != self.digest
            {
                return Err(AtomicError::Corrupt);
            }
        }
        Ok(())
    }
}

fn result_payload_digest(
    outcome: Outcome,
    code: Option<&str>,
    value: &Value,
) -> Result<Identity, AtomicError> {
    let mut full = Encoder::new(b"lsf-result-payload-v1\0");
    full.0.push(outcome_tag(outcome));
    full.optional(code)?;
    full.value(value)?;
    Ok(Identity::derive(
        b"lsf-result-digest-v1\0",
        &[&full.finish(RESULT_BYTES)?],
    ))
}

pub(super) fn outcome_tag(outcome: Outcome) -> u8 {
    match outcome {
        Outcome::Pending => 0,
        Outcome::Committed => 1,
        Outcome::Rejected => 2,
        Outcome::Aborted => 3,
    }
}
fn decode_outcome(tag: u8) -> Result<Outcome, AtomicError> {
    match tag {
        0 => Ok(Outcome::Pending),
        1 => Ok(Outcome::Committed),
        2 => Ok(Outcome::Rejected),
        3 => Ok(Outcome::Aborted),
        _ => Err(AtomicError::Corrupt),
    }
}
pub(super) fn row_key(
    family: Family,
    prefix: &[u8],
    identity: Identity,
    attempt: Option<u64>,
) -> RowKey {
    let mut key = prefix.to_vec();
    key.extend_from_slice(&identity.0);
    if let Some(attempt) = attempt {
        key.extend_from_slice(&attempt.to_be_bytes());
    }
    RowKey { family, key }
}
pub fn command_row_key(identity: Identity) -> RowKey {
    row_key(Family::Command, b"command-v1\0", identity, None)
}
pub fn attempt_row_key(identity: Identity, attempt: u64) -> RowKey {
    row_key(
        Family::Attempt,
        b"command-attempt-v1\0",
        identity,
        Some(attempt),
    )
}
pub fn result_row_key(identity: Identity, attempt: u64) -> RowKey {
    row_key(
        Family::Result,
        b"command-result-v1\0",
        identity,
        Some(attempt),
    )
}
