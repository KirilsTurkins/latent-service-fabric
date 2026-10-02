use latent_state::embedded::{Family, ReadView, RowKey, StoreError};
use latent_state::reservation::{LogicalReservation, KEY_PREFIX as RESERVATION_PREFIX};

use crate::dispatch::{Disposition, EffectRecord};
use crate::dispatch_store::codec::{
    attempt_reservation_key, history_key, HistoryRecord, HistoryReservation, OwnerRecord,
    ATTEMPT_RESERVATION_PREFIX, DISPOSITION_RESERVED_BYTES, HISTORY_PREFIX,
};
use crate::dispatch_store::{
    effect_from_key, effect_payload_key, effect_row_key, storage_error, validate_row, DueRecord,
    DUE_PREFIX, EFFECT_PREFIX, PAYLOAD_PREFIX,
};
use crate::effect_identity;
use crate::payload::PayloadRecord;

use super::DispatchCatalog;

impl DispatchCatalog {
    /// Validate closed dispatcher rows and their links in one startup snapshot.
    /// Other families/prefixes are left to the complete command registry. No
    /// native view, engine owner or materialized backlog escapes this callback.
    pub fn validate_view(view: &ReadView) -> Result<(), StoreError> {
        crate::dispatch_store::control::ControlCatalog::validate_view(view)?;
        let owner = view
            .get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()?;
        walk(view, Family::Outbox, EFFECT_PREFIX, |key, bytes| {
            validate_effect(view, owner, key, bytes)
        })?;
        walk(
            view,
            Family::PayloadReference,
            PAYLOAD_PREFIX,
            |key, bytes| {
                validate_row(key, bytes)?;
                let effect = effect_from_key(key, PAYLOAD_PREFIX)?;
                let record = load(view, &effect)?;
                PayloadRecord::decode(bytes)
                    .map_err(storage_error)?
                    .verify(&record.authority().map_err(storage_error)?)
                    .map_err(storage_error)
            },
        )?;
        walk(view, Family::Maintenance, DUE_PREFIX, |key, bytes| {
            let due = DueRecord::decode(key, bytes)?;
            let record = load(view, &due.effect)?;
            if expected_due(&record)? != Some(due) {
                return Err(StoreError::Corrupt);
            }
            Ok(())
        })?;
        walk(view, Family::Attempt, HISTORY_PREFIX, |key, bytes| {
            validate_history(view, key, bytes)
        })?;
        let mut prefix = RESERVATION_PREFIX.to_vec();
        prefix.extend_from_slice(ATTEMPT_RESERVATION_PREFIX);
        walk(view, Family::Maintenance, &prefix, |key, bytes| {
            validate_row(key, bytes)?;
            let effect = effect_from_key(key, &prefix)?;
            let record = load(view, &effect)?;
            if record.disposition() != Disposition::Dispatching
                || LogicalReservation::decode(bytes)?
                    != (LogicalReservation {
                        generation: record.claim_generation(),
                        bytes: DISPOSITION_RESERVED_BYTES,
                    })
            {
                return Err(StoreError::Corrupt);
            }
            Ok(())
        })
    }

    /// A persisted dispatcher epoch requires an admitted external checkpoint at
    /// runtime startup. A wall-clock continuity flag does not approve a restore.
    pub fn has_owner_history(view: &ReadView) -> Result<bool, StoreError> {
        view.get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()
            .map(|owner| owner.is_some())
    }
}

fn validate_effect(
    view: &ReadView,
    owner: Option<OwnerRecord>,
    key: &RowKey,
    bytes: &[u8],
) -> Result<(), StoreError> {
    validate_row(key, bytes)?;
    let effect = effect_from_key(key, EFFECT_PREFIX)?;
    let record = EffectRecord::decode(bytes).map_err(storage_error)?;
    let authority = record.authority().map_err(storage_error)?;
    if record.attempts() != 0
        && owner.is_none_or(|owner| {
            owner.epoch < record.owner_epoch()
                || owner.clock_floor < authority.committed_at_millis()
                || record
                    .latest()
                    .is_some_and(|receipt| owner.clock_floor < receipt.observed_at_millis)
        })
    {
        return Err(StoreError::Corrupt);
    }
    let payload = view.get(&effect_payload_key(&effect)?)?;
    if let Some(payload) = payload {
        PayloadRecord::decode(&payload)
            .map_err(storage_error)?
            .verify(&authority)
            .map_err(storage_error)?;
    } else if !record.disposition().terminal() {
        return Err(StoreError::Corrupt);
    }
    if let Some(due) = expected_due(&record)? {
        let key = due.key()?;
        let stored = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        if DueRecord::decode(&key, &stored)? != due {
            return Err(StoreError::Corrupt);
        }
    }
    for sequence in 1..=record.history_sequence() {
        let key = history_key(&effect, sequence)?;
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        let history = HistoryRecord::decode(&key, &bytes)?;
        validate_history_attempt(&record, &history)?;
        if sequence == record.history_sequence() && record.latest() != Some(&history.receipt) {
            return Err(StoreError::Corrupt);
        }
    }
    let reservation = view.get(&attempt_reservation_key(&effect)?)?;
    if record.disposition() == Disposition::Dispatching {
        if LogicalReservation::decode(reservation.as_deref().ok_or(StoreError::Corrupt)?)?
            != (LogicalReservation {
                generation: record.claim_generation(),
                bytes: DISPOSITION_RESERVED_BYTES,
            })
        {
            return Err(StoreError::Corrupt);
        }
        let key = history_key(&effect, record.history_sequence() + 1)?;
        let slot = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        if HistoryReservation::decode(&slot)? != expected_history_slot(&record) {
            return Err(StoreError::Corrupt);
        }
    } else if reservation.is_some() {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

fn validate_history(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    validate_row(key, bytes)?;
    let identity = key.key[HISTORY_PREFIX.len()..HISTORY_PREFIX.len() + 32]
        .try_into()
        .map_err(|_| StoreError::Corrupt)?;
    let effect = effect_identity::render(&identity);
    let record = load(view, &effect)?;
    let sequence = u64::from_be_bytes(
        key.key[HISTORY_PREFIX.len() + 32..]
            .try_into()
            .map_err(|_| StoreError::Corrupt)?,
    );
    if HistoryReservation::present(bytes) {
        if record.disposition() != Disposition::Dispatching
            || sequence != record.history_sequence() + 1
            || HistoryReservation::decode(bytes)? != expected_history_slot(&record)
        {
            return Err(StoreError::Corrupt);
        }
    } else {
        let history = HistoryRecord::decode(key, bytes)?;
        if sequence > record.history_sequence() {
            return Err(StoreError::Corrupt);
        }
        validate_history_attempt(&record, &history)?;
    }
    Ok(())
}

fn validate_history_attempt(
    record: &EffectRecord,
    history: &HistoryRecord,
) -> Result<(), StoreError> {
    let Some(attempt) = &history.attempt else {
        return Err(StoreError::Corrupt);
    };
    if attempt.attempt() > record.attempts()
        || attempt.owner_epoch() > record.owner_epoch()
        || attempt.claim_generation() > record.claim_generation()
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

fn expected_history_slot(record: &EffectRecord) -> HistoryReservation {
    HistoryReservation {
        owner_epoch: record.owner_epoch(),
        claim_generation: record.claim_generation(),
        attempt: record.attempts(),
    }
}

fn expected_due(record: &EffectRecord) -> Result<Option<DueRecord>, StoreError> {
    let due = match record.disposition() {
        Disposition::Pending => record
            .authority()
            .map_err(storage_error)?
            .committed_at_millis(),
        Disposition::RetryScheduled => record.retry_at_millis(),
        _ => return Ok(None),
    };
    let authority = record.authority().map_err(storage_error)?;
    Ok(Some(DueRecord {
        due_millis: due,
        effect: authority.link().effect.clone(),
        incarnation: authority.scope().incarnation,
        claim_generation: record.claim_generation(),
    }))
}

fn load(view: &ReadView, effect: &str) -> Result<EffectRecord, StoreError> {
    let key = effect_row_key(effect)?;
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    validate_row(&key, &bytes)?;
    EffectRecord::decode(&bytes).map_err(storage_error)
}

fn walk(
    view: &ReadView,
    family: Family,
    prefix: &[u8],
    mut validate: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    let mut cursor = None;
    loop {
        let page = view.scan_after(family, prefix, cursor.as_deref(), 16, 4 * 1024 * 1024)?;
        for (key, bytes) in &page.rows {
            validate(key, bytes)?;
        }
        cursor = page.resume;
        if cursor.is_none() {
            return Ok(());
        }
    }
}
