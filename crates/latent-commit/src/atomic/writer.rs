//! Worker-borrowed admission and complete-envelope writer.

use super::{
    codec::{Decoder, Encoder, METADATA_BYTES},
    command_identity, fingerprint, id, incarnation,
    record::{attempt_row_key, command_row_key, outcome_tag, result_row_key},
    AdmissionInput, AtomicError, CommandAccess, CommandRecord, CommandTime, DurableResult,
    Identity, Outcome,
};
use latent_core::{transaction_contract::Value, StateNamespaceId, TenantId};
use latent_effects::authority::{
    CommitLink, DurableEffectAuthority, EffectAuthorityOwner, EffectScope, EffectTime,
};
use latent_state::{
    embedded::{
        AtomicBatch, EmbeddedStore, ExpectedRow, Family, FencedStoreError, ReadView, RowKey,
        RowMutation,
    },
    namespace::{namespace_record_key, NamespacePins, NamespaceRecord, NamespaceStatus},
    reservation::{reservation_key, LogicalReservation},
    session::StatePlan,
};

pub enum AdmissionDecision {
    New(PreparedAdmission),
    Existing(CommandRecord),
}
pub struct PreparedAdmission {
    record: CommandRecord,
    batch: AtomicBatch,
}
/// Once-only host claim, deliberately not cloneable or reconstructible from a
/// caller-supplied receipt. The runtime owns physical executor/IO guards separately.
pub struct AdmittedCommand {
    pub(super) record: CommandRecord,
    pub(super) expected: Vec<u8>,
    pub(super) physical: std::sync::Arc<super::ownership::AttemptState>,
}
pub struct CompleteEnvelope {
    claim: AdmittedCommand,
    terminal: CommandRecord,
    result: DurableResult,
    batch: AtomicBatch,
    authorities: Vec<DurableEffectAuthority>,
}

/// A bounded closed observation of the namespace expectation in an actually
/// prepared complete envelope. This is not a grant or a durable disposition.
pub struct EnvelopeNamespaceExpectation {
    expected: ExpectedRow,
    outcome: Outcome,
}
impl EnvelopeNamespaceExpectation {
    #[must_use]
    pub fn is_technical_abort(&self) -> bool {
        self.outcome == Outcome::Aborted
    }
    #[must_use]
    pub fn matches(&self, expected: &ExpectedRow) -> bool {
        self.expected.key == expected.key && self.expected.value == expected.value
    }

    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        self.expected.key.key.len() + self.expected.value.as_ref().map_or(0, Vec::len) + 256
    }
}
pub enum PreparedDisposition {
    Confirmed {
        command: Box<CommandRecord>,
        result: Box<DurableResult>,
    },
    KnownNotCommitted {
        command: Box<AdmittedCommand>,
        reason: AtomicError,
    },
    RecoveryRequired {
        identity: Box<CommandRecord>,
    },
}

impl PreparedAdmission {
    #[allow(
        clippy::too_many_lines,
        reason = "Keep every admission expectation and reservation in one reviewable atomic plan"
    )]
    pub fn prepare(
        view: &ReadView,
        input: AdmissionInput,
        time: CommandTime,
        mut authorize: impl FnMut(CommandAccess, Option<&CommandRecord>) -> Result<(), AtomicError>,
    ) -> Result<AdmissionDecision, AtomicError> {
        authorize(CommandAccess::Admit, None)?;
        time.check(0)?;
        input.source.validate()?;
        id(&input.result_read_policy)?;
        input.result_policy.validate()?;
        if input.owner_epoch == 0 || input.source.input_format != input.fingerprint.input_format {
            return Err(AtomicError::Invalid);
        }
        let command_id = command_identity(&input.key)?;
        let fingerprint = fingerprint(&input.fingerprint, input.inbox.as_ref())?;
        let key = command_row_key(command_id);
        if let Some(bytes) = view.get(&key)? {
            let existing = CommandRecord::decode(&bytes)?;
            authorize(CommandAccess::Replay, Some(&existing))?;
            if existing.key != input.key || existing.fingerprint != fingerprint {
                return Err(AtomicError::Conflict);
            }
            time.check(existing.clock_floor)?;
            return Ok(AdmissionDecision::Existing(existing));
        }
        let (mut namespace, namespace_key, namespace_bytes) =
            namespace(view, &input.key, &input.source.state_schema)?;
        let result_expires = time
            .unix_millis
            .checked_add(input.result_policy.result_millis)
            .ok_or(AtomicError::Limit)?;
        let identity_expires = time
            .unix_millis
            .checked_add(input.result_policy.identity_millis)
            .ok_or(AtomicError::Limit)?;
        let record = CommandRecord {
            key: input.key,
            id: command_id,
            fingerprint,
            source: input.source,
            result_read_policy: input.result_read_policy,
            result_policy: input.result_policy,
            admitted_at: time.unix_millis,
            clock_floor: time.unix_millis,
            result_expires,
            identity_expires,
            owner_epoch: input.owner_epoch,
            attempt: 1,
            outcome: Outcome::Pending,
            completed_at: 0,
            committed_version: None,
            committed_view_token: vec![],
            result_digest: Identity([0; 32]),
            effects: vec![],
            inbox: input.inbox,
            abort_proof: None,
        };
        let reserve = record.result_policy.reservation()?;
        let (mut usage, usage_key, usage_bytes) = Usage::read(view, &record.key)?;
        usage.results = usage.results.checked_add(1).ok_or(AtomicError::Limit)?;
        usage.result_bytes = usage
            .result_bytes
            .checked_add(reserve)
            .ok_or(AtomicError::Limit)?;
        usage.reserved = usage
            .reserved
            .checked_add(reserve)
            .ok_or(AtomicError::Limit)?;
        usage.recovery_reserved = usage
            .recovery_reserved
            .checked_add(METADATA_BYTES as u64)
            .ok_or(AtomicError::Limit)?;
        usage.check(&namespace)?;
        namespace.pins.retained_results = namespace
            .pins
            .retained_results
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        let encoded = record.encode()?;
        let reservation = reservation_key(&record.id.0)?;
        let attempt_key = attempt_row_key(record.id, record.attempt);
        let result_key = result_row_key(record.id, record.attempt);
        let batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: key.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: attempt_key.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: result_key.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: namespace_key.clone(),
                    value: Some(namespace_bytes),
                },
                ExpectedRow {
                    key: usage_key.clone(),
                    value: usage_bytes,
                },
                ExpectedRow {
                    key: reservation.clone(),
                    value: None,
                },
            ],
            mutations: vec![
                RowMutation {
                    key,
                    value: Some(encoded.clone()),
                },
                RowMutation {
                    key: attempt_key,
                    value: Some(encoded),
                },
                RowMutation {
                    key: result_key,
                    value: Some(pending_result(&record)),
                },
                RowMutation {
                    key: namespace_key,
                    value: Some(namespace.encode().map_err(|_| AtomicError::Invalid)?),
                },
                RowMutation {
                    key: usage_key,
                    value: Some(usage.encode()),
                },
                RowMutation {
                    key: reservation,
                    value: Some(
                        LogicalReservation {
                            generation: 1,
                            bytes: reserve,
                        }
                        .encode()?,
                    ),
                },
            ],
        };
        Ok(AdmissionDecision::New(Self { record, batch }))
    }
    #[must_use]
    pub fn record(&self) -> &CommandRecord {
        &self.record
    }
    #[must_use]
    pub fn batch(&self) -> &AtomicBatch {
        &self.batch
    }
    pub fn publish(
        self,
        store: &EmbeddedStore,
        final_accept: impl FnOnce() -> Result<(), AtomicError>,
    ) -> Result<AdmittedCommand, AtomicError> {
        let expected = self.record.encode()?;
        store
            .apply_fenced(self.batch, final_accept)
            .map_err(fenced_error)?;
        let physical = super::ownership::AttemptState::new(self.record.clone(), expected.clone());
        Ok(AdmittedCommand {
            record: self.record,
            expected,
            physical,
        })
    }
}
impl AdmittedCommand {
    #[must_use]
    pub fn record(&self) -> &CommandRecord {
        &self.record
    }
}

/// Caller-attributable retry identity and server-issued durable abort fence.
pub struct RetryRequest {
    pub request_id: String,
    pub expected_abort: Identity,
}
impl PreparedAdmission {
    #[allow(
        clippy::too_many_lines,
        reason = "Keep the historical attempt, retry receipt and new reservation CAS together"
    )]
    pub fn retry(
        view: &ReadView,
        input: &AdmissionInput,
        request: &RetryRequest,
        time: CommandTime,
        mut authorize: impl FnMut(CommandAccess, Option<&CommandRecord>) -> Result<(), AtomicError>,
    ) -> Result<AdmissionDecision, AtomicError> {
        authorize(CommandAccess::Admit, None)?;
        time.check(0)?;
        id(&request.request_id)?;
        let identity = command_identity(&input.key)?;
        let fingerprint = fingerprint(&input.fingerprint, input.inbox.as_ref())?;
        let command_key = command_row_key(identity);
        let old_bytes = view
            .get(&command_key)?
            .ok_or(AtomicError::RecoveryRequired)?;
        let old = CommandRecord::decode(&old_bytes)?;
        authorize(CommandAccess::Admit, Some(&old))?;
        if old.key != input.key || old.fingerprint != fingerprint || input.owner_epoch == 0 {
            return Err(AtomicError::Conflict);
        }
        time.check(old.clock_floor)?;
        let retry_id = Identity::derive(
            b"lsf-command-retry-v1\0",
            &[&identity.0, request.request_id.as_bytes()],
        );
        let retry_key =
            super::record::row_key(Family::Maintenance, b"command-retry-v1\0", retry_id, None);
        if let Some(bytes) = view.get(&retry_key)? {
            let mut input = Decoder::new(&bytes, b"LCT\0\x01", 77)?;
            let generation = input.number()?;
            let proof = input.identity()?;
            let captured = input.identity()?;
            input.finish()?;
            if proof != request.expected_abort || captured != fingerprint {
                return Err(AtomicError::Conflict);
            }
            let bytes = view
                .get(&attempt_row_key(identity, generation))?
                .ok_or(AtomicError::Corrupt)?;
            return Ok(AdmissionDecision::Existing(CommandRecord::decode(&bytes)?));
        }
        if old.outcome != Outcome::Aborted || old.abort_proof != Some(request.expected_abort) {
            return Err(AtomicError::RecoveryRequired);
        }
        if time.unix_millis >= old.result_expires
            || old.attempt >= old.result_policy.maximum_attempts
        {
            return Err(AtomicError::Expired);
        }
        let (mut namespace, namespace_key, namespace_bytes) =
            namespace(view, &old.key, &old.source.state_schema)?;
        let mut record = old.clone();
        record.attempt = record.attempt.checked_add(1).ok_or(AtomicError::Limit)?;
        record.owner_epoch = input.owner_epoch;
        record.outcome = Outcome::Pending;
        record.completed_at = 0;
        record.committed_version = None;
        record.committed_view_token.clear();
        record.clock_floor = time.unix_millis;
        record.result_digest = Identity([0; 32]);
        record.effects.clear();
        record.abort_proof = None;
        let reserve = record.result_policy.reservation()?;
        let (mut usage, usage_key, usage_bytes) = Usage::read(view, &record.key)?;
        usage.results = usage.results.checked_add(1).ok_or(AtomicError::Limit)?;
        usage.result_bytes = usage
            .result_bytes
            .checked_add(reserve)
            .ok_or(AtomicError::Limit)?;
        usage.reserved = usage
            .reserved
            .checked_add(reserve)
            .ok_or(AtomicError::Limit)?;
        usage.recovery_reserved = usage
            .recovery_reserved
            .checked_add(METADATA_BYTES as u64)
            .ok_or(AtomicError::Limit)?;
        usage.check(&namespace)?;
        namespace.pins.retained_results = namespace
            .pins
            .retained_results
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        let encoded = record.encode()?;
        let attempt = attempt_row_key(identity, record.attempt);
        let reservation = reservation_key(&identity.0)?;
        let result_key = result_row_key(identity, record.attempt);
        let mut retry = Encoder::new(b"LCT\0\x01");
        retry.number(record.attempt);
        retry.identity(request.expected_abort);
        retry.identity(fingerprint);
        let batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: command_key.clone(),
                    value: Some(old_bytes),
                },
                ExpectedRow {
                    key: attempt.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: result_key.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: retry_key.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: reservation.clone(),
                    value: None,
                },
                ExpectedRow {
                    key: namespace_key.clone(),
                    value: Some(namespace_bytes),
                },
                ExpectedRow {
                    key: usage_key.clone(),
                    value: usage_bytes,
                },
            ],
            mutations: vec![
                RowMutation {
                    key: command_key,
                    value: Some(encoded.clone()),
                },
                RowMutation {
                    key: attempt,
                    value: Some(encoded),
                },
                RowMutation {
                    key: result_key,
                    value: Some(pending_result(&record)),
                },
                RowMutation {
                    key: retry_key,
                    value: Some(retry.finish(77)?),
                },
                RowMutation {
                    key: reservation,
                    value: Some(
                        LogicalReservation {
                            generation: record.attempt,
                            bytes: reserve,
                        }
                        .encode()?,
                    ),
                },
                RowMutation {
                    key: namespace_key,
                    value: Some(namespace.encode().map_err(|_| AtomicError::Invalid)?),
                },
                RowMutation {
                    key: usage_key,
                    value: Some(usage.encode()),
                },
            ],
        };
        Ok(AdmissionDecision::New(Self { record, batch }))
    }
}

/// Guest intent requests contain only approved aliases and owned bounded values.
/// Capturing them cannot publish rows; the final writer repeats current rule checks.
pub struct StagedIntent {
    pub binding: String,
    pub operation: String,
    pub payload: Value,
    pub expires_at_millis: Option<u64>,
}

impl CompleteEnvelope {
    /// The coordinator moves this affine guard into the one accepted native
    /// writer. Decoding metadata cannot construct it or assert retirement.
    pub fn physical_work(&self) -> Result<super::PhysicalAttemptWork, AtomicError> {
        self.claim.physical_work()
    }
    /// State-only/no-intent commands need no effect authority owner. They still
    /// use the same complete atomic namespace/state/result/command envelope.
    pub fn success_without_intents(
        view: &ReadView,
        claim: AdmittedCommand,
        state: Option<StatePlan>,
        value: Value,
        time: CommandTime,
    ) -> Result<Self, AtomicError> {
        let version = next_namespace_version(view, &claim.record)?;
        let token = disposition_view_token(view, &claim.record, state.as_ref(), version)?;
        let result = DurableResult::new(
            &claim.record,
            Outcome::Committed,
            None,
            value,
            version,
            token,
        )?;
        Self::prepare(view, claim, state, result, vec![], vec![], time, None)
    }

    pub fn namespace_expectation(&self) -> Result<EnvelopeNamespaceExpectation, AtomicError> {
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(
                &TenantId(self.terminal.key.tenant.clone()),
                &StateNamespaceId(self.terminal.key.namespace.clone()),
            )
            .map_err(|_| AtomicError::Invalid)?,
        };
        let mut matching = self.batch.expectations.iter().filter(|row| row.key == key);
        let expected = matching.next().ok_or(AtomicError::Invalid)?.clone();
        if matching.next().is_some() || expected.value.is_none() {
            return Err(AtomicError::Invalid);
        }
        Ok(EnvelopeNamespaceExpectation {
            expected,
            outcome: self.terminal.outcome,
        })
    }

    pub fn success(
        view: &ReadView,
        claim: AdmittedCommand,
        state: Option<StatePlan>,
        intents: Vec<StagedIntent>,
        value: Value,
        effects: &EffectAuthorityOwner,
        time: CommandTime,
    ) -> Result<Self, AtomicError> {
        if intents.len() > 128 {
            return Err(AtomicError::Limit);
        }
        let minimum_bytes = intents
            .iter()
            .try_fold(value.bytes.len(), |bytes, intent| {
                intent.payload.validate().map_err(|_| AtomicError::Limit)?;
                bytes
                    .checked_add(
                        intent.payload.bytes.len()
                            + intent.payload.media_type.len()
                            + intent
                                .payload
                                .metadata
                                .iter()
                                .map(|(a, b)| a.len() + b.len() + 4)
                                .sum::<usize>(),
                    )
                    .ok_or(AtomicError::Limit)
            })?;
        if minimum_bytes > latent_core::transaction_contract::STAGED_BYTES {
            return Err(AtomicError::Limit);
        }
        let version = next_namespace_version(view, &claim.record)?;
        let token = disposition_view_token(view, &claim.record, state.as_ref(), version)?;
        let result = DurableResult::new(
            &claim.record,
            Outcome::Committed,
            None,
            value,
            version,
            token,
        )?;
        let mut authorities = Vec::with_capacity(intents.len());
        let mut effect_rows = Vec::with_capacity(intents.len() * 3);
        for (sequence, intent) in intents.into_iter().enumerate() {
            id(&intent.binding)?;
            id(&intent.operation)?;
            intent.payload.validate().map_err(|_| AtomicError::Limit)?;
            let sequence = u32::try_from(sequence).map_err(|_| AtomicError::Limit)?;
            let effect_id = claim.record.effect_id(sequence);
            let scope = EffectScope {
                tenant: claim.record.key.tenant.clone(),
                namespace: claim.record.key.namespace.clone(),
                incarnation: incarnation(&claim.record.key)?,
                publication: claim.record.source.publication.clone(),
                binding: intent.binding,
                operation: intent.operation,
            };
            let link = CommitLink {
                command: claim.record.id.hex(),
                caller_scope: claim.record.key.recovery_scope.clone(),
                attempt: claim.record.attempt,
                commit: claim.record.disposition_id().hex(),
                effect: effect_id.hex(),
                sequence,
            };
            let authority = effects.capture_until(
                &scope,
                link,
                intent.payload.bytes.len() as u64,
                latent_effects::payload::payload_digest(&intent.payload)?,
                EffectTime {
                    unix_millis: time.unix_millis,
                    continuity_proven: time.continuity_proven,
                },
                intent.expires_at_millis,
            )?;
            let record = latent_effects::dispatch::EffectRecord::committed(&authority)?.encode()?;
            let payload = latent_effects::payload::PayloadRecord::new(&authority, intent.payload)?
                .encode()?;
            effect_rows.push(RowMutation {
                key: latent_effects::dispatch_store::effect_row_key(&effect_id.hex())?,
                value: Some(record),
            });
            effect_rows.push(RowMutation {
                key: latent_effects::dispatch_store::effect_payload_key(&effect_id.hex())?,
                value: Some(payload),
            });
            effect_rows.push(latent_effects::dispatch_store::initial_due_mutation(
                &authority,
            )?);
            authorities.push(authority);
        }
        Self::prepare(
            view,
            claim,
            state,
            result,
            authorities,
            effect_rows,
            time,
            None,
        )
    }
    /// The caller has already discarded every staged application mutation and
    /// intent. Only result/command/accounting and approved terminal inbox rows persist.
    pub fn rejection(
        view: &ReadView,
        claim: AdmittedCommand,
        code: String,
        value: Value,
        time: CommandTime,
    ) -> Result<Self, AtomicError> {
        let version = next_namespace_version(view, &claim.record)?;
        let token = disposition_view_token(view, &claim.record, None, version)?;
        let result = DurableResult::new(
            &claim.record,
            Outcome::Rejected,
            Some(code),
            value,
            version,
            token,
        )?;
        Self::prepare(view, claim, None, result, vec![], vec![], time, None)
    }
    /// Private physical retirement evidence permits terminal technical metadata,
    /// with no application writes, intents or processed-input acknowledgement.
    pub fn technical_abort(
        view: &ReadView,
        retired: super::RetiredAttempt,
        code: String,
        time: CommandTime,
    ) -> Result<Self, AtomicError> {
        let physical =
            super::ownership::AttemptState::new(retired.record.clone(), retired.expected.clone());
        let claim = AdmittedCommand {
            record: retired.record,
            expected: retired.expected,
            physical,
        };
        let proof = Identity::derive(
            b"lsf-proven-abort-v1\0",
            &[&claim.expected, &claim.record.transaction_id().0],
        );
        let value = Value {
            bytes: vec![],
            media_type: String::from("application/vnd.lsf.technical-abort-v1"),
            metadata: vec![],
        };
        let version = next_namespace_version(view, &claim.record)?;
        let token = disposition_view_token(view, &claim.record, None, version)?;
        let result = DurableResult::new(
            &claim.record,
            Outcome::Aborted,
            Some(code),
            value,
            version,
            token,
        )?;
        Self::prepare(view, claim, None, result, vec![], vec![], time, Some(proof))
    }
    #[must_use]
    pub fn authorities(&self) -> &[DurableEffectAuthority] {
        &self.authorities
    }
    #[must_use]
    pub fn batch(&self) -> &AtomicBatch {
        &self.batch
    }
    #[must_use]
    pub fn command(&self) -> &CommandRecord {
        &self.terminal
    }
    pub fn publish(
        self,
        store: &EmbeddedStore,
        final_accept: impl FnOnce(&[DurableEffectAuthority]) -> Result<(), AtomicError>,
    ) -> PreparedDisposition {
        use super::ownership::{ACCEPTED, TERMINAL, UNKNOWN};
        use std::sync::atomic::Ordering;
        match store.apply_fenced(self.batch, || {
            final_accept(&self.authorities)?;
            self.claim.physical.phase.store(ACCEPTED, Ordering::Release);
            Ok(())
        }) {
            Ok(()) => {
                self.claim.physical.phase.store(TERMINAL, Ordering::Release);
                PreparedDisposition::Confirmed {
                    command: Box::new(self.terminal),
                    result: Box::new(self.result),
                }
            }
            Err(FencedStoreError::Store(
                latent_state::embedded::StoreError::CommitUncertain
                | latent_state::embedded::StoreError::Unavailable,
            )) => {
                self.claim.physical.phase.store(UNKNOWN, Ordering::Release);
                PreparedDisposition::RecoveryRequired {
                    identity: Box::new(self.claim.record.clone()),
                }
            }
            Err(error) => PreparedDisposition::KnownNotCommitted {
                command: Box::new(self.claim),
                reason: fenced_error(error),
            },
        }
    }
    #[allow(
        clippy::too_many_arguments,
        clippy::too_many_lines,
        reason = "The complete owned envelope is validated as one physical transaction, never piecemeal"
    )]
    pub(super) fn prepare(
        view: &ReadView,
        claim: AdmittedCommand,
        state: Option<StatePlan>,
        result: DurableResult,
        authorities: Vec<DurableEffectAuthority>,
        effect_rows: Vec<RowMutation>,
        time: CommandTime,
        abort_proof: Option<Identity>,
    ) -> Result<Self, AtomicError> {
        time.check(claim.record.clock_floor)?;
        let (mut namespace, namespace_key, namespace_bytes) =
            namespace(view, &claim.record.key, &claim.record.source.state_schema)?;
        if view.get(&command_row_key(claim.record.id))? != Some(claim.expected.clone()) {
            return Err(AtomicError::Conflict);
        }
        let mut terminal = claim.record.clone();
        let version = latent_state::namespace::NamespaceVersion {
            incarnation: namespace.version.incarnation,
            generation: namespace
                .version
                .generation
                .checked_add(1)
                .ok_or(AtomicError::Limit)?,
        };
        if result.committed_version != version
            || result.committed_view_token
                != disposition_view_token(view, &claim.record, state.as_ref(), version)?
        {
            return Err(AtomicError::Invalid);
        }
        terminal.outcome = result.outcome;
        terminal.committed_version = Some(version);
        terminal
            .committed_view_token
            .clone_from(&result.committed_view_token);
        terminal.completed_at = time.unix_millis;
        terminal.clock_floor = time.unix_millis;
        terminal.result_digest = result.digest;
        terminal.abort_proof = abort_proof;
        terminal.effects = (0..authorities.len())
            .map(|sequence| {
                u32::try_from(sequence)
                    .map(|sequence| terminal.effect_id(sequence))
                    .map_err(|_| AtomicError::Limit)
            })
            .collect::<Result<_, _>>()?;
        let terminal_bytes = terminal.encode()?;
        let result_bytes = result.encode()?;
        let (mut usage, usage_key, usage_bytes) = Usage::read(view, &terminal.key)?;
        let reserve = terminal.result_policy.reservation()?;
        usage.reserved = usage
            .reserved
            .checked_sub(reserve)
            .ok_or(AtomicError::Corrupt)?;
        usage.recovery_reserved = usage
            .recovery_reserved
            .checked_sub(METADATA_BYTES as u64)
            .ok_or(AtomicError::Corrupt)?;
        usage.result_bytes = usage
            .result_bytes
            .checked_sub(reserve)
            .and_then(|bytes| bytes.checked_add(result_bytes.len() as u64))
            .ok_or(AtomicError::Corrupt)?;
        for row in &effect_rows {
            let bytes = row.key.key.len() as u64 + row.value.as_ref().map_or(0, |v| v.len() as u64);
            match row.key.family {
                Family::Outbox => {
                    usage.effects = usage.effects.checked_add(1).ok_or(AtomicError::Limit)?;
                    usage.effect_bytes = usage
                        .effect_bytes
                        .checked_add(bytes)
                        .ok_or(AtomicError::Limit)?;
                }
                Family::PayloadReference => {
                    usage.payload_bytes = usage
                        .payload_bytes
                        .checked_add(bytes)
                        .ok_or(AtomicError::Limit)?;
                }
                Family::Maintenance => {}
                _ => return Err(AtomicError::Invalid),
            }
        }
        usage.check(&namespace)?;
        let mut pins: NamespacePins = namespace.pins;
        pins.unresolved_effects = pins
            .unresolved_effects
            .checked_add(authorities.len() as u64)
            .ok_or(AtomicError::Limit)?;
        pins.payload_references = pins
            .payload_references
            .checked_add(authorities.len() as u64)
            .ok_or(AtomicError::Limit)?;
        let command_key = command_row_key(terminal.id);
        let attempt_key = attempt_row_key(terminal.id, terminal.attempt);
        let result_key = result_row_key(terminal.id, terminal.attempt);
        let reservation = reservation_key(&terminal.id.0)?;
        let mut batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: command_key.clone(),
                    value: Some(claim.expected.clone()),
                },
                ExpectedRow {
                    key: attempt_key.clone(),
                    value: Some(claim.expected.clone()),
                },
                ExpectedRow {
                    key: result_key.clone(),
                    value: Some(pending_result(&terminal)),
                },
                ExpectedRow {
                    key: usage_key.clone(),
                    value: usage_bytes,
                },
                ExpectedRow {
                    key: reservation.clone(),
                    value: Some(
                        LogicalReservation {
                            generation: terminal.attempt,
                            bytes: reserve,
                        }
                        .encode()?,
                    ),
                },
            ],
            mutations: vec![
                RowMutation {
                    key: command_key,
                    value: Some(terminal_bytes.clone()),
                },
                RowMutation {
                    key: attempt_key,
                    value: Some(terminal_bytes),
                },
                RowMutation {
                    key: result_key,
                    value: Some(result_bytes),
                },
                RowMutation {
                    key: usage_key,
                    value: Some(usage.encode()),
                },
                RowMutation {
                    key: reservation,
                    value: None,
                },
            ],
        };
        if result.outcome != Outcome::Aborted {
            if let Some(inbox) = &terminal.inbox {
                let key = inbox.row_key(&terminal.key)?;
                batch.expectations.push(ExpectedRow {
                    key: key.clone(),
                    value: None,
                });
                let mut value = Encoder::new(b"LIC\0\x01");
                value.identity(terminal.id);
                value.number(terminal.attempt);
                value.0.push(outcome_tag(terminal.outcome));
                value.identity(inbox.payload_digest);
                value.number(time.unix_millis);
                batch.mutations.push(RowMutation {
                    key,
                    value: Some(value.finish(METADATA_BYTES)?),
                });
                pins.inbox_protection = pins
                    .inbox_protection
                    .checked_add(1)
                    .ok_or(AtomicError::Limit)?;
            }
        }
        for row in &effect_rows {
            batch.expectations.push(ExpectedRow {
                key: row.key.clone(),
                value: None,
            });
        }
        batch.mutations.extend(effect_rows);
        if let Some(state) = state {
            let scope = state.scope();
            if terminal.outcome != Outcome::Committed
                || scope.tenant.0 != terminal.key.tenant
                || scope.namespace.0 != terminal.key.namespace
                || scope.incarnation != incarnation(&terminal.key)?
                || scope.entity != terminal.key.entity
                || scope.state_schema != terminal.source.state_schema
                || state.version().generation
                    != namespace
                        .version
                        .generation
                        .checked_add(1)
                        .ok_or(AtomicError::Limit)?
            {
                return Err(AtomicError::Invalid);
            }
            state.append_to(&mut batch, pins)?;
        } else {
            let scope = super::record::record_scope(&terminal)?;
            let captured = latent_state::session::version::capture_view(view, &scope)?;
            batch.expectations.push(captured.history_expectation());
            batch.expectations.push(captured.recovery_expectation());
            namespace.pins = pins;
            namespace.version.generation = namespace
                .version
                .generation
                .checked_add(1)
                .ok_or(AtomicError::Limit)?;
            batch.expectations.push(ExpectedRow {
                key: namespace_key.clone(),
                value: Some(namespace_bytes),
            });
            batch.mutations.push(RowMutation {
                key: namespace_key,
                value: Some(namespace.encode().map_err(|_| AtomicError::Invalid)?),
            });
        }
        let staged = batch.mutations.iter().try_fold(0usize, |bytes, row| {
            bytes
                .checked_add(row.key.key.len() + row.value.as_ref().map_or(0, Vec::len))
                .ok_or(AtomicError::Limit)
        })?;
        if staged > latent_core::transaction_contract::STAGED_BYTES
            || batch.expectations.len() > 1024
            || batch.mutations.len() > 1024
        {
            return Err(AtomicError::Limit);
        }
        Ok(Self {
            claim,
            terminal,
            result,
            batch,
            authorities,
        })
    }
}

fn pending_result(record: &CommandRecord) -> Vec<u8> {
    let mut out = Encoder::new(b"LCP\0\x01");
    out.identity(record.id);
    out.number(record.attempt);
    out.0.push(match record.result_policy.replay {
        super::ReplayPolicy::Full => 1,
        super::ReplayPolicy::ReceiptOnly => 2,
    });
    out.0
}

pub fn inspect(
    view: &ReadView,
    key: &latent_core::transaction_contract::CommandKey,
    time: CommandTime,
    mut authorize: impl FnMut(CommandAccess, Option<&CommandRecord>) -> Result<(), AtomicError>,
) -> Result<(CommandRecord, Option<DurableResult>), AtomicError> {
    authorize(CommandAccess::Replay, None)?;
    let bytes = view
        .get(&command_row_key(command_identity(key)?))?
        .ok_or(AtomicError::NotFound)?;
    let record = CommandRecord::decode(&bytes)?;
    authorize(CommandAccess::Replay, Some(&record))?;
    if record.key != *key {
        return Err(AtomicError::Corrupt);
    }
    time.check(record.clock_floor)?;
    if record.outcome == Outcome::Pending || time.unix_millis >= record.result_expires {
        return Ok((record, None));
    }
    let bytes = view
        .get(&result_row_key(record.id, record.attempt))?
        .ok_or(AtomicError::Corrupt)?;
    let result = DurableResult::decode(&bytes)?;
    result.verify(&record)?;
    Ok((record, Some(result)))
}
#[allow(
    clippy::needless_pass_by_value,
    reason = "Result::map_err transfers the closed engine/fence error into the host error"
)]
pub(super) fn fenced_error(error: FencedStoreError<AtomicError>) -> AtomicError {
    match error {
        FencedStoreError::Store(error) => error.into(),
        FencedStoreError::Fence(error) => error,
    }
}
pub(super) fn next_namespace_version(
    view: &ReadView,
    record: &CommandRecord,
) -> Result<latent_state::namespace::NamespaceVersion, AtomicError> {
    let (namespace, _, _) = namespace(view, &record.key, &record.source.state_schema)?;
    Ok(latent_state::namespace::NamespaceVersion {
        incarnation: namespace.version.incarnation,
        generation: namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?,
    })
}

pub(super) fn disposition_view_token(
    view: &ReadView,
    record: &CommandRecord,
    state: Option<&StatePlan>,
    version: latent_state::namespace::NamespaceVersion,
) -> Result<Vec<u8>, AtomicError> {
    let scope = super::record::record_scope(record)?;
    let mut actual = latent_state::session::version::capture_view(view, &scope)?.identity();
    actual.namespace = version;
    if let Some(state) = state {
        if state.view_identity() != actual || state.scope() != &scope {
            return Err(AtomicError::Invalid);
        }
        Ok(state.view_token()?)
    } else {
        Ok(actual.token(&scope)?)
    }
}

fn namespace(
    view: &ReadView,
    key: &latent_core::transaction_contract::CommandKey,
    schema: &str,
) -> Result<(NamespaceRecord, RowKey, Vec<u8>), AtomicError> {
    let row = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(
            &TenantId(key.tenant.clone()),
            &StateNamespaceId(key.namespace.clone()),
        )
        .map_err(|_| AtomicError::Invalid)?,
    };
    let bytes = view.get(&row)?.ok_or(AtomicError::NotFound)?;
    let record = NamespaceRecord::decode(&bytes).map_err(|_| AtomicError::Corrupt)?;
    if record.status != NamespaceStatus::Active
        || record.version.incarnation != incarnation(key)?
        || record.state_schema != schema
    {
        return Err(AtomicError::Conflict);
    }
    Ok((record, row, bytes))
}
#[derive(Default)]
pub(super) struct Usage {
    results: u64,
    pub(super) result_bytes: u64,
    effects: u64,
    effect_bytes: u64,
    payload_bytes: u64,
    reserved: u64,
    recovery_reserved: u64,
}
impl Usage {
    pub(super) fn read(
        view: &ReadView,
        key: &latent_core::transaction_contract::CommandKey,
    ) -> Result<(Self, RowKey, Option<Vec<u8>>), AtomicError> {
        let mut bytes = b"command-usage-v1\0".to_vec();
        bytes.extend_from_slice(
            &namespace_record_key(
                &TenantId(key.tenant.clone()),
                &StateNamespaceId(key.namespace.clone()),
            )
            .map_err(|_| AtomicError::Invalid)?,
        );
        bytes.extend_from_slice(&incarnation(key)?.to_le_bytes());
        let row = RowKey {
            family: Family::Maintenance,
            key: bytes,
        };
        let bytes = view.get(&row)?;
        let usage = if let Some(bytes) = &bytes {
            let mut input = Decoder::new(bytes, b"LCU\0\x01", 61)?;
            let usage = Self {
                results: input.number()?,
                result_bytes: input.number()?,
                effects: input.number()?,
                effect_bytes: input.number()?,
                payload_bytes: input.number()?,
                reserved: input.number()?,
                recovery_reserved: input.number()?,
            };
            input.finish()?;
            usage
        } else {
            Self::default()
        };
        Ok((usage, row, bytes))
    }
    pub(super) fn encode(&self) -> Vec<u8> {
        let mut out = Encoder::new(b"LCU\0\x01");
        for number in [
            self.results,
            self.result_bytes,
            self.effects,
            self.effect_bytes,
            self.payload_bytes,
            self.reserved,
            self.recovery_reserved,
        ] {
            out.number(number);
        }
        out.0
    }
    fn check(&self, namespace: &NamespaceRecord) -> Result<(), AtomicError> {
        let quota = namespace.quota;
        if self.results > quota.result_rows
            || self.result_bytes > quota.result_bytes
            || self.effects > quota.effect_rows
            || self.effect_bytes > quota.effect_bytes
            || self.payload_bytes > quota.payload_bytes
            || self.recovery_reserved > quota.recovery_bytes
        {
            return Err(AtomicError::Limit);
        }
        Ok(())
    }
}
