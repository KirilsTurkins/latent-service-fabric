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
    /// Original dispatcher codec/link ownership for the shared tenant census.
    /// Delivery/history/payload rows remain covered by the command owner's
    /// original LCU2 reserve. Only closed global control metadata is excluded.
    pub fn tenant_census_contribution(
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<latent_state::tenant::TenantCensusContribution, StoreError> {
        use latent_state::tenant::TenantCensusContribution;
        validate_row(key, bytes)?;
        if key.family == Family::Maintenance
            && key.key.starts_with(crate::recovery_close::RECEIPT_PREFIX)
        {
            let receipt = crate::recovery_close::CloseReceipt::validate_row(key, bytes)?;
            crate::recovery_close::validate_receipt_links(view, &receipt)?;
            return Ok(TenantCensusContribution::Usage {
                tenant: latent_core::TenantId(receipt.plan.scope.tenant),
                usage: latent_state::tenant::TenantUsage {
                    metadata_rows: 1,
                    metadata_bytes: latent_state::tenant::row_charge(key, bytes)?,
                    ..latent_state::tenant::TenantUsage::default()
                },
            });
        }
        if *key == OwnerRecord::key()
            || (key.family == Family::Maintenance
                && (key.key.as_slice() == crate::dispatch_store::control::CONTROL_STATE_KEY
                    || key
                        .key
                        .starts_with(crate::dispatch_store::control::CONTROL_RECEIPT_PREFIX)))
        {
            return Ok(TenantCensusContribution::Global);
        }
        let effect = match key.family {
            Family::Outbox => {
                let owner = view
                    .get(&OwnerRecord::key())?
                    .as_deref()
                    .map(OwnerRecord::decode)
                    .transpose()?;
                validate_effect(view, owner, key, bytes)?;
                effect_from_key(key, EFFECT_PREFIX)?
            }
            Family::PayloadReference => {
                let payload = PayloadRecord::decode(bytes).map_err(storage_error)?;
                let record = load(view, payload.effect())?;
                payload
                    .verify(&record.authority().map_err(storage_error)?)
                    .map_err(storage_error)?;
                payload.effect().to_owned()
            }
            Family::Attempt => {
                validate_history(view, key, bytes)?;
                effect_identity::render(
                    &key.key[HISTORY_PREFIX.len()..HISTORY_PREFIX.len() + 32]
                        .try_into()
                        .map_err(|_| StoreError::Corrupt)?,
                )
            }
            Family::Maintenance if key.key.starts_with(DUE_PREFIX) => {
                let due = DueRecord::decode(key, bytes)?;
                if expected_due(&load(view, &due.effect)?)? != Some(due.clone()) {
                    return Err(StoreError::Corrupt);
                }
                due.effect
            }
            Family::Maintenance if key.key.starts_with(RESERVATION_PREFIX) => {
                let mut prefix = RESERVATION_PREFIX.to_vec();
                prefix.extend_from_slice(ATTEMPT_RESERVATION_PREFIX);
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
                effect
            }
            _ => return Err(StoreError::UnsupportedFormat),
        };
        let record = load(view, &effect)?;
        let authority = record.authority().map_err(storage_error)?;
        Ok(TenantCensusContribution::Covered {
            tenant: latent_core::TenantId(authority.scope().tenant.clone()),
        })
    }

    /// Capture one effect's installed inline payload/history/index closure.
    /// No active physical claim can be reclaimed. Missing or corrupt links
    /// refuse, including extra history slots; metadata never authorizes GC.
    pub fn retention_rows(
        view: &ReadView,
        effect: &str,
    ) -> Result<super::RetainedEffectRows, StoreError> {
        use latent_state::embedded::ExpectedRow;
        let key = effect_row_key(effect)?;
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
        // The V2 explicit close receipt is a separate retained recovery link.
        // Automatic reclamation must not drop that operator decision or leave
        // another selected effect without its shared decoder/receipt closure.
        if record.recovery_close_digest().is_some() {
            return Err(StoreError::UnsupportedFormat);
        }
        if record.disposition() == Disposition::Dispatching {
            return Err(StoreError::Capacity);
        }
        let owner_key = OwnerRecord::key();
        let owner_bytes = view.get(&owner_key)?;
        let owner = owner_bytes
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()?;
        validate_effect(view, owner, &key, &bytes)?;
        let history = Self::history_page(view, effect, None, 128, 1024 * 1024)?;
        if history.resume.is_some()
            || history.pending_slots != 0
            || history.rows.len() as u64 != record.history_sequence()
        {
            return Err(StoreError::Corrupt);
        }
        let payload_key = effect_payload_key(effect)?;
        let payload = view.get(&payload_key)?.ok_or(StoreError::Corrupt)?;
        let reservation_key = attempt_reservation_key(effect)?;
        if view.get(&reservation_key)?.is_some() {
            return Err(StoreError::Corrupt);
        }
        let mut reclaim = vec![key.clone(), payload_key.clone()];
        let mut expectations = vec![
            ExpectedRow {
                key,
                value: Some(bytes),
            },
            ExpectedRow {
                key: payload_key,
                value: Some(payload),
            },
            ExpectedRow {
                key: owner_key,
                value: owner_bytes,
            },
            ExpectedRow {
                key: reservation_key,
                value: None,
            },
        ];
        for item in history.rows {
            let key = item.key()?;
            reclaim.push(key.clone());
            let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
            expectations.push(ExpectedRow {
                key,
                value: Some(bytes),
            });
        }
        let due = expected_due(&record)?;
        let due_key = due.as_ref().map(DueRecord::key).transpose()?;
        if let Some(key) = &due_key {
            reclaim.push(key.clone());
            let bytes = view.get(key)?.ok_or(StoreError::Corrupt)?;
            expectations.push(ExpectedRow {
                key: key.clone(),
                value: Some(bytes),
            });
        }
        Ok(super::RetainedEffectRows {
            record,
            expectations,
            due: due_key,
            reclaim,
        })
    }

    /// Validate closed dispatcher rows and their links in one startup snapshot.
    /// Other families/prefixes are left to the complete command registry. No
    /// native view, engine owner or materialized backlog escapes this callback.
    pub fn validate_view(view: &ReadView) -> Result<(), StoreError> {
        crate::dispatch_store::control::ControlCatalog::validate_view(view)?;
        crate::dispatch_store::effect_management::EffectManagementCatalog::validate_view(view)?;
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
            Family::Maintenance,
            crate::recovery_close::RECEIPT_PREFIX,
            |key, bytes| {
                let receipt = crate::recovery_close::CloseReceipt::validate_row(key, bytes)?;
                crate::recovery_close::validate_receipt_links(view, &receipt)
            },
        )?;
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

    /// Describes the original retained owner epoch and clock floor through its
    /// closed decoder. These numbers grant no restart, restore or dispatch right.
    pub fn owner_checkpoint(view: &ReadView) -> Result<Option<(u64, u64)>, StoreError> {
        view.get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()
            .map(|owner| owner.map(|owner| (owner.epoch, owner.clock_floor)))
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
    crate::dispatch_store::effect_management::EffectManagementCatalog::validate_effect(
        view, &record,
    )?;
    crate::recovery_close::validate_record_link(view, &record)?;
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
