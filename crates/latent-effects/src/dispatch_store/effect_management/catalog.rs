use crate::authority::{DurableEffectAuthority, EffectTime};
use crate::dispatch::{
    effect_record_version, Disposition, EffectManagementFact, EffectManagementStamp, EffectRecord,
    RetryProof,
};
use crate::dispatch_store::codec::{history_key, HistoryRecord, OwnerRecord};
use crate::dispatch_store::{
    effect_payload_key, effect_row_key, DispatchCatalog, DispatchEpoch, DispatchStoreError,
    DueRecord,
};
use crate::payload::PayloadRecord;
use crate::runtime::{ProviderConfirmation, ProviderReconciliationRequest};
use latent_state::embedded::{AtomicBatch, ExpectedRow, ReadView, RowMutation, StoreError};
use latent_state::reservation::LogicalReservation;

use super::{
    codec, EffectManagementAction, EffectManagementError, EffectManagementPlan,
    EffectManagementReceipt, EffectManagementRequest, EffectManagementSafety, COUNTER_PREFIX,
    MAXIMUM_PLAN_LIFETIME_MILLIS, PLAN_PREFIX, RECEIPT_PREFIX, RESERVED_DISPOSITION_BYTES,
};

pub struct EffectManagementCatalog;

/// Affine prepared metadata. The protected runtime applies this batch only
/// under the original current policy/lifecycle/operator/capacity acceptance.
pub struct PreparedEffectPlan {
    batch: AtomicBatch,
    plan: EffectManagementPlan,
    replayed: bool,
}
impl PreparedEffectPlan {
    #[must_use]
    pub fn into_parts(self) -> (AtomicBatch, EffectManagementPlan, bool) {
        (self.batch, self.plan, self.replayed)
    }
}
pub struct PreparedEffectMutation {
    batch: AtomicBatch,
    receipt: EffectManagementReceipt,
    replayed: bool,
    authority: DurableEffectAuthority,
}
impl PreparedEffectMutation {
    #[must_use]
    pub fn authority(&self) -> &DurableEffectAuthority {
        &self.authority
    }
    #[must_use]
    pub fn requires_dispatch_authority(&self) -> bool {
        !self.replayed && self.receipt.plan.request.0.action == EffectManagementAction::Redrive
    }
    #[must_use]
    pub fn into_parts(self) -> (AtomicBatch, EffectManagementReceipt, bool) {
        (self.batch, self.receipt, self.replayed)
    }
}

/// Provider evidence is created only by the installed trusted adapter. Operators
/// submit the bounded plan and action, never a retry proof or remote receipt.
pub enum EffectManagementEvidence {
    Retry(RetryProof),
    Provider(ProviderConfirmation),
    Administrator,
}

struct Loaded {
    bytes: Vec<u8>,
    record: EffectRecord,
    authority: DurableEffectAuthority,
}
impl Loaded {
    fn read(
        view: &ReadView,
        request: &EffectManagementRequest,
    ) -> Result<Self, EffectManagementError> {
        let input = request.input();
        let key = effect_row_key(&input.effect)?;
        let bytes = view.get(&key)?.ok_or(EffectManagementError::NotFound)?;
        crate::dispatch_store::validate_row(&key, &bytes)?;
        let record = EffectRecord::decode(&bytes)?;
        let authority = record.authority()?;
        let scope = authority.scope();
        let link = authority.link();
        if scope.tenant != input.actor_tenant
            || scope.namespace != input.namespace
            || scope.incarnation != input.incarnation
            || link.command != input.command
            || link.attempt != input.command_attempt
            || link.caller_scope != input.caller_scope
            || link.effect != input.effect
        {
            return Err(EffectManagementError::PermissionDenied);
        }
        Ok(Self {
            bytes,
            record,
            authority,
        })
    }
    fn exact(&self, request: &EffectManagementRequest) -> Result<(), EffectManagementError> {
        if effect_record_version(&self.bytes)? != request.0.expected_version {
            return Err(EffectManagementError::Conflict);
        }
        Ok(())
    }
}

impl EffectManagementCatalog {
    /// Original persisted plan, addressed by authenticated actor and operation.
    /// The gateway validates its full target/precondition/digest before release.
    /// Knowing an operation ID is never namespace or provider permission.
    pub fn plan_for_actor(
        view: &ReadView,
        tenant: &str,
        subject: &str,
        operation: &str,
    ) -> Result<Option<EffectManagementPlan>, EffectManagementError> {
        for text in [tenant, subject, operation] {
            if text.is_empty() || text.len() > 256 || text.chars().any(char::is_control) {
                return Err(EffectManagementError::Invalid);
            }
        }
        let key = codec::row(
            PLAN_PREFIX,
            &codec::operation_actor(tenant, subject, operation),
        );
        let Some(bytes) = view.get(&key)? else {
            return Ok(None);
        };
        let plan = EffectManagementPlan::decode(&bytes)?;
        let input = plan.request().input();
        if input.actor_tenant != tenant
            || input.actor_subject != subject
            || input.operation_id != operation
        {
            return Err(StoreError::Corrupt.into());
        }
        Ok(Some(plan))
    }

    /// Prepare on a fixed worker's coherent native view. Planning reserves the
    /// finite future disposition in the same engine; it performs no provider IO.
    pub fn prepare_plan(
        view: &ReadView,
        epoch: DispatchEpoch,
        request: EffectManagementRequest,
        time: EffectTime,
        qualification: Option<RetryProof>,
    ) -> Result<PreparedEffectPlan, EffectManagementError> {
        request.validate()?;
        let loaded = Loaded::read(view, &request)?;
        let operation = codec::operation(&request);
        let plan_key = codec::row(PLAN_PREFIX, &operation);
        if let Some(bytes) = view.get(&plan_key)? {
            let plan = EffectManagementPlan::decode(&bytes)?;
            if plan.request != request {
                return Err(EffectManagementError::Conflict);
            }
            return Ok(PreparedEffectPlan {
                batch: AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: plan_key,
                        value: Some(bytes),
                    }],
                    mutations: vec![],
                },
                plan,
                replayed: true,
            });
        }
        loaded.exact(&request)?;
        if loaded.record.disposition() == Disposition::Dispatching {
            return Err(EffectManagementError::PhysicalOwnerLive);
        }
        let original_attempt = DispatchCatalog::last_completed_attempt(view, &request.0.effect)
            .map_err(dispatch_error)?;
        let safety = safety(&loaded.record, &request, qualification, time)?;
        let effect = crate::effect_identity::parse(&request.0.effect)?;
        let counter_key = codec::row(COUNTER_PREFIX, &effect);
        let old_counter = view.get(&counter_key)?;
        let sequence = old_counter
            .as_deref()
            .map(super::validation::decode_counter)
            .transpose()?
            .unwrap_or(0)
            .checked_add(1)
            .filter(|next| *next <= 128)
            .ok_or(EffectManagementError::Capacity)?;
        let plan = EffectManagementPlan {
            expires_at_millis: expiry(&loaded.authority, &request, safety, time)?,
            request,
            sequence,
            original_attempt,
            before: loaded.record.disposition(),
            safety,
            prepared_at_millis: time.unix_millis,
        };
        let reservation_key = codec::reservation(&operation)?;
        let slot_key = codec::slot(&effect, sequence);
        let mut batch = owner_batch(view, epoch, time)?;
        expect(
            &mut batch,
            effect_row_key(&plan.request.0.effect)?,
            Some(loaded.bytes),
        );
        expect(&mut batch, plan_key.clone(), None);
        expect(&mut batch, reservation_key.clone(), None);
        expect(&mut batch, counter_key.clone(), old_counter);
        expect(&mut batch, slot_key.clone(), None);
        put(&mut batch, plan_key, Some(plan.encode()?));
        put(
            &mut batch,
            counter_key,
            Some(super::validation::encode_counter(sequence)?),
        );
        put(&mut batch, slot_key, Some(operation.to_vec()));
        put(
            &mut batch,
            reservation_key,
            Some(
                LogicalReservation {
                    generation: u64::from(sequence),
                    bytes: RESERVED_DISPOSITION_BYTES,
                }
                .encode()?,
            ),
        );
        Ok(PreparedEffectPlan {
            batch,
            plan,
            replayed: false,
        })
    }

    pub fn lookup(
        view: &ReadView,
        plan: &EffectManagementPlan,
    ) -> Result<Option<EffectManagementReceipt>, EffectManagementError> {
        plan.validate()?;
        Loaded::read(view, &plan.request)?;
        let key = codec::row(RECEIPT_PREFIX, &codec::operation(&plan.request));
        let Some(bytes) = view.get(&key)? else {
            return Ok(None);
        };
        let receipt = EffectManagementReceipt::decode(&bytes)?;
        if receipt.plan != *plan {
            return Err(EffectManagementError::Conflict);
        }
        Ok(Some(receipt))
    }

    /// Build an original lookup request from physical history and immutable
    /// payload in the same view. No field from an operator supplies an attempt.
    pub fn provider_request(
        view: &ReadView,
        request: &EffectManagementRequest,
    ) -> Result<ProviderReconciliationRequest, EffectManagementError> {
        let loaded = Loaded::read(view, request)?;
        loaded.exact(request)?;
        let attempt = DispatchCatalog::last_completed_attempt(view, &request.0.effect)
            .map_err(dispatch_error)?
            .ok_or(EffectManagementError::Invalid)?;
        let payload = view
            .get(&effect_payload_key(&request.0.effect)?)?
            .ok_or(StoreError::Corrupt)?;
        Ok(ProviderReconciliationRequest::new(
            loaded.authority,
            PayloadRecord::decode(&payload)?,
            attempt,
            request.0.expected_version,
        )?)
    }

    pub fn prepare_mutation(
        view: &ReadView,
        epoch: DispatchEpoch,
        plan: EffectManagementPlan,
        evidence: EffectManagementEvidence,
        time: EffectTime,
    ) -> Result<PreparedEffectMutation, EffectManagementError> {
        plan.validate()?;
        let mut loaded = Loaded::read(view, &plan.request)?;
        let operation = codec::operation(&plan.request);
        let plan_key = codec::row(PLAN_PREFIX, &operation);
        let plan_bytes = view
            .get(&plan_key)?
            .ok_or(EffectManagementError::NotFound)?;
        if EffectManagementPlan::decode(&plan_bytes)? != plan {
            return Err(EffectManagementError::Conflict);
        }
        let receipt_key = codec::row(RECEIPT_PREFIX, &operation);
        if let Some(receipt) = Self::lookup(view, &plan)? {
            let bytes = view.get(&receipt_key)?.ok_or(StoreError::Corrupt)?;
            return Ok(PreparedEffectMutation {
                batch: AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: receipt_key,
                        value: Some(bytes),
                    }],
                    mutations: vec![],
                },
                receipt,
                replayed: true,
                authority: loaded.authority,
            });
        }
        plan.check_time(time)?;
        loaded.exact(&plan.request)?;
        if loaded.record.disposition() != plan.before {
            return Err(EffectManagementError::Conflict);
        }
        let attempt = DispatchCatalog::last_completed_attempt(view, &plan.request.0.effect)
            .map_err(dispatch_error)?;
        if attempt != plan.original_attempt {
            return Err(EffectManagementError::Conflict);
        }
        let (fact, provider_receipt, provider_observed_at_millis) =
            transition(&mut loaded.record, &plan, evidence, time)?;
        loaded.record.stamp_managed(EffectManagementStamp {
            sequence: plan.sequence,
            operation_digest: crate::effect_identity::render(&operation),
            fact,
            original_attempt: plan.original_attempt.clone(),
            provider_receipt: provider_receipt.clone(),
            provider_observed_at_millis,
            observed_at_millis: time.unix_millis,
        })?;
        let after_bytes = loaded.record.encode()?;
        let receipt = EffectManagementReceipt {
            after_version: effect_record_version(&after_bytes)?,
            after: loaded.record.disposition(),
            plan,
            fact,
            provider_receipt,
            provider_observed_at_millis,
            completed_at_millis: time.unix_millis,
        };
        let mut batch = owner_batch(view, epoch, time)?;
        remove_old_due(view, &mut batch, &loaded, &receipt.plan)?;
        let reservation_key = codec::reservation(&operation)?;
        let reservation = view.get(&reservation_key)?.ok_or(StoreError::Corrupt)?;
        if LogicalReservation::decode(&reservation)?
            != (LogicalReservation {
                generation: u64::from(receipt.plan.sequence),
                bytes: RESERVED_DISPOSITION_BYTES,
            })
        {
            return Err(StoreError::Corrupt.into());
        }
        expect(&mut batch, reservation_key.clone(), Some(reservation));
        expect(&mut batch, plan_key, Some(plan_bytes));
        expect(&mut batch, receipt_key.clone(), None);
        let effect_key = effect_row_key(&receipt.plan.request.0.effect)?;
        expect(&mut batch, effect_key.clone(), Some(loaded.bytes));
        put(&mut batch, effect_key, Some(after_bytes));
        put(&mut batch, reservation_key, None);
        put(&mut batch, receipt_key, Some(receipt.encode()?));
        if fact == EffectManagementFact::RedriveScheduled {
            let due = DueRecord {
                effect: receipt.plan.request.0.effect.clone(),
                due_millis: loaded.record.retry_at_millis(),
                incarnation: loaded.authority.scope().incarnation,
                claim_generation: loaded.record.claim_generation(),
            };
            expect(&mut batch, due.key()?, None);
            put(&mut batch, due.key()?, Some(due.encode()?));
        }
        Ok(PreparedEffectMutation {
            batch,
            receipt,
            replayed: false,
            authority: loaded.authority,
        })
    }
}

impl DispatchCatalog {
    pub fn last_completed_attempt(
        view: &ReadView,
        effect: &str,
    ) -> Result<Option<crate::dispatch::AttemptIdentity>, DispatchStoreError> {
        let key = effect_row_key(effect)?;
        let bytes = view
            .get(&key)?
            .ok_or(crate::authority::AuthorityError::Stale)?;
        crate::dispatch_store::validate_row(&key, &bytes)?;
        let record = EffectRecord::decode(&bytes)?;
        if record.disposition() == Disposition::Dispatching {
            return Err(crate::authority::AuthorityError::Unavailable.into());
        }
        if record.history_sequence() == 0 {
            return Ok(None);
        }
        let history_key = history_key(effect, record.history_sequence())?;
        let history_bytes = view.get(&history_key)?.ok_or(StoreError::Corrupt)?;
        let history = HistoryRecord::decode(&history_key, &history_bytes)?;
        let attempt = history.attempt.ok_or(StoreError::Corrupt)?;
        if record.latest() != Some(&history.receipt)
            || attempt.effect() != effect
            || attempt.attempt() != record.attempts()
            || attempt.owner_epoch() > record.owner_epoch()
            || attempt.claim_generation() > record.claim_generation()
        {
            return Err(StoreError::Corrupt.into());
        }
        Ok(Some(attempt))
    }
}

fn safety(
    record: &EffectRecord,
    request: &EffectManagementRequest,
    qualification: Option<RetryProof>,
    time: EffectTime,
) -> Result<EffectManagementSafety, EffectManagementError> {
    let input = request.input();
    match input.action {
        EffectManagementAction::Terminate if !record.disposition().terminal() => {
            Ok(EffectManagementSafety::AdministratorDeclared)
        }
        EffectManagementAction::Reconcile
            if record.send_started()
                && matches!(
                    record.disposition(),
                    Disposition::KnownFailed | Disposition::Uncertain
                ) =>
        {
            Ok(EffectManagementSafety::ProviderReceiptLookup)
        }
        EffectManagementAction::Redrive => {
            if record.attempts() >= record.authority()?.ceiling().maximum_attempts {
                return Err(crate::authority::AuthorityError::Capacity.into());
            }
            let proof =
                if record.disposition() == Disposition::KnownFailed && !record.send_started() {
                    RetryProof::KnownNonexecution
                } else {
                    qualification.ok_or(EffectManagementError::PermissionDenied)?
                };
            record
                .clone()
                .schedule_retry(proof, time, input.retry_delay_millis)?;
            match proof {
                RetryProof::KnownNonexecution => Ok(EffectManagementSafety::KnownNonexecution),
                RetryProof::QualifiedDeduplication {
                    valid_until_millis, ..
                } => Ok(EffectManagementSafety::QualifiedDeduplication { valid_until_millis }),
            }
        }
        _ => Err(EffectManagementError::Invalid),
    }
}
fn expiry(
    authority: &DurableEffectAuthority,
    request: &EffectManagementRequest,
    safety: EffectManagementSafety,
    time: EffectTime,
) -> Result<u64, EffectManagementError> {
    if !time.continuity_proven
        || time.unix_millis == 0
        || time.unix_millis < authority.committed_at_millis()
    {
        return Err(crate::authority::AuthorityError::ClockDiscontinuity.into());
    }
    let mut expires = time
        .unix_millis
        .checked_add(MAXIMUM_PLAN_LIFETIME_MILLIS)
        .ok_or(EffectManagementError::Capacity)?;
    if request.0.action == EffectManagementAction::Redrive {
        expires = expires.min(
            authority
                .expires_at_millis()
                .saturating_sub(request.0.retry_delay_millis),
        );
    }
    if let EffectManagementSafety::QualifiedDeduplication { valid_until_millis } = safety {
        expires = expires.min(valid_until_millis.saturating_sub(request.0.retry_delay_millis));
    }
    if expires <= time.unix_millis {
        return Err(crate::authority::AuthorityError::Expired.into());
    }
    Ok(expires)
}
fn transition(
    record: &mut EffectRecord,
    plan: &EffectManagementPlan,
    evidence: EffectManagementEvidence,
    time: EffectTime,
) -> Result<(EffectManagementFact, Option<String>, Option<u64>), EffectManagementError> {
    match (plan.request.0.action, evidence) {
        (EffectManagementAction::Terminate, EffectManagementEvidence::Administrator) => {
            record.terminate_managed(time)?;
            Ok((EffectManagementFact::AdministratorTerminated, None, None))
        }
        (EffectManagementAction::Reconcile, EffectManagementEvidence::Provider(confirmation)) => {
            confirmation.validate_for(
                plan.original_attempt
                    .as_ref()
                    .ok_or(EffectManagementError::Invalid)?,
                plan.request.0.expected_version,
            )?;
            record.confirm_managed(&confirmation, time)?;
            Ok((
                EffectManagementFact::ProviderConfirmed,
                Some(confirmation.provider_receipt().into()),
                Some(confirmation.observed_at_millis()),
            ))
        }
        (EffectManagementAction::Redrive, EffectManagementEvidence::Retry(proof)) => {
            let matches = match (plan.safety, proof) {
                (EffectManagementSafety::KnownNonexecution, RetryProof::KnownNonexecution) => true,
                (
                    EffectManagementSafety::QualifiedDeduplication {
                        valid_until_millis: expected,
                    },
                    RetryProof::QualifiedDeduplication {
                        valid_until_millis,
                        same_payload: true,
                        same_provider_incarnation: true,
                    },
                ) => valid_until_millis == expected,
                _ => false,
            };
            if !matches {
                return Err(EffectManagementError::PermissionDenied);
            }
            record.schedule_retry(proof, time, plan.request.0.retry_delay_millis)?;
            Ok((EffectManagementFact::RedriveScheduled, None, None))
        }
        _ => Err(EffectManagementError::Invalid),
    }
}
fn owner_batch(
    view: &ReadView,
    epoch: DispatchEpoch,
    time: EffectTime,
) -> Result<AtomicBatch, EffectManagementError> {
    let key = OwnerRecord::key();
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    let mut owner = OwnerRecord::decode(&bytes)?;
    if owner.epoch != epoch.generation() {
        return Err(EffectManagementError::Conflict);
    }
    owner.observe(time)?;
    Ok(AtomicBatch {
        expectations: vec![ExpectedRow {
            key: key.clone(),
            value: Some(bytes),
        }],
        mutations: vec![RowMutation {
            key,
            value: Some(owner.encode()?),
        }],
    })
}
fn remove_old_due(
    view: &ReadView,
    batch: &mut AtomicBatch,
    loaded: &Loaded,
    plan: &EffectManagementPlan,
) -> Result<(), EffectManagementError> {
    let due_millis = match plan.before {
        Disposition::Pending => loaded.authority.committed_at_millis(),
        Disposition::RetryScheduled => EffectRecord::decode(&loaded.bytes)?.retry_at_millis(),
        _ => return Ok(()),
    };
    let due = DueRecord {
        effect: plan.request.0.effect.clone(),
        due_millis,
        incarnation: loaded.authority.scope().incarnation,
        claim_generation: loaded.record.claim_generation(),
    };
    let key = due.key()?;
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    if DueRecord::decode(&key, &bytes)? != due {
        return Err(StoreError::Corrupt.into());
    }
    expect(batch, key.clone(), Some(bytes));
    put(batch, key, None);
    Ok(())
}
fn expect(batch: &mut AtomicBatch, key: latent_state::embedded::RowKey, value: Option<Vec<u8>>) {
    batch.expectations.push(ExpectedRow { key, value });
}
fn put(batch: &mut AtomicBatch, key: latent_state::embedded::RowKey, value: Option<Vec<u8>>) {
    batch.mutations.push(RowMutation { key, value });
}
fn dispatch_error(error: DispatchStoreError) -> EffectManagementError {
    match error {
        DispatchStoreError::Storage(error) => error.into(),
        DispatchStoreError::Authority(error) => error.into(),
        DispatchStoreError::StaleEpoch => EffectManagementError::Conflict,
    }
}
