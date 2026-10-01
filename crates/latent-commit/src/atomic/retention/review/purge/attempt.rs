use super::super::{operation::Captured, RetentionAudit, RetiredCommand, RetryIndex};
use crate::atomic::{
    codec::Decoder,
    record::{attempt_row_key, command_row_key, result_row_key},
    retention::ExpiredResult,
    writer::{row_charge, Usage},
    AtomicError, CommandRecord, DurableResult, MaintenanceClock, Outcome,
};
use latent_state::embedded::{ReadView, RowKey};

pub(super) fn prior(
    view: &ReadView,
    captured: &mut Captured,
    audit: &mut RetentionAudit,
    usage: &mut Usage,
) -> Result<u64, AtomicError> {
    let generation = audit
        .purged_attempts
        .checked_add(1)
        .ok_or(AtomicError::Limit)?;
    let reclaimed = delete_attempt(view, captured, usage, generation, false)?;
    audit.purged_attempts = generation;
    Ok(reclaimed)
}

pub(super) fn finish(
    view: &ReadView,
    captured: &mut Captured,
    audit: &RetentionAudit,
    usage: &mut Usage,
    clock: MaintenanceClock,
) -> Result<u64, AtomicError> {
    let mut reclaimed = delete_attempt(view, captured, usage, captured.record.attempt, true)?;
    if matches!(
        captured.record.outcome,
        Outcome::Committed | Outcome::Rejected
    ) {
        if let Some(inbox) = captured.record.inbox.clone() {
            let key = inbox.row_key(&captured.record.key)?;
            let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
            let mut input = Decoder::new(&bytes, b"LIC\0\x01", 86)?;
            if input.identity()? != captured.record.id
                || input.number()? != captured.record.attempt
                || input.byte()? != crate::atomic::record::outcome_tag(captured.record.outcome)
                || input.identity()? != inbox.payload_digest
                || input.number()? != captured.record.completed_at
            {
                return Err(AtomicError::Corrupt);
            }
            input.finish()?;
            reclaimed = reclaimed
                .checked_add(delete(captured, usage, key, bytes)?)
                .ok_or(AtomicError::Limit)?;
            captured.namespace.pins.inbox_protection = captured
                .namespace
                .pins
                .inbox_protection
                .checked_sub(1)
                .ok_or(AtomicError::Corrupt)?;
        }
    }
    let floor = RetiredCommand::new(&captured.record, audit, clock.time.unix_millis)?.encode()?;
    let key = command_row_key(captured.record.id);
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(row_charge(&key, &captured.bytes)?)
        .and_then(|bytes| bytes.checked_add(row_charge(&key, &floor).ok()?))
        .ok_or(AtomicError::Corrupt)?;
    reclaimed = reclaimed
        .checked_add(
            captured
                .bytes
                .len()
                .checked_sub(floor.len())
                .ok_or(AtomicError::Corrupt)? as u64,
        )
        .ok_or(AtomicError::Limit)?;
    captured.plan.mutation(key, Some(floor))?;
    // The floor remains one bounded namespace result/identity pin. Only explicit
    // drained namespace release may remove it before the next incarnation.
    usage.results = usage.results.checked_add(1).ok_or(AtomicError::Limit)?;
    captured.namespace.pins.retained_results = captured
        .namespace
        .pins
        .retained_results
        .checked_add(1)
        .ok_or(AtomicError::Limit)?;
    Ok(reclaimed)
}

fn delete_attempt(
    view: &ReadView,
    captured: &mut Captured,
    usage: &mut Usage,
    generation: u64,
    current: bool,
) -> Result<u64, AtomicError> {
    let key = attempt_row_key(captured.record.id, generation);
    let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
    let record = CommandRecord::decode(&bytes)?;
    if !record.accounted
        || record.key != captured.record.key
        || record.id != captured.record.id
        || record.fingerprint != captured.record.fingerprint
        || record.source != captured.record.source
        || record.attempt != generation
        || (!current && (record.outcome != Outcome::Aborted || !record.effects.is_empty()))
    {
        return Err(AtomicError::Corrupt);
    }
    let result_key = result_row_key(record.id, generation);
    let result = view.get(&result_key)?.ok_or(AtomicError::Corrupt)?;
    if result.starts_with(b"LCE\0") {
        ExpiredResult::decode(&result)?.verify(&record)?;
    } else {
        DurableResult::decode(&result)?.verify(&record)?;
    }
    let mut reclaimed = delete(captured, usage, key, bytes)?
        .checked_add(delete(captured, usage, result_key, result)?)
        .ok_or(AtomicError::Limit)?;
    if generation >= 2 {
        let key = RetryIndex::row_key(record.id, generation);
        let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
        let index = RetryIndex::decode(&bytes)?;
        if index.command != record.id || index.attempt != generation {
            return Err(AtomicError::Corrupt);
        }
        let retry_key = index.retry_key();
        let retry = view.get(&retry_key)?.ok_or(AtomicError::Corrupt)?;
        let mut input = Decoder::new(&retry, b"LCT\0\x01", 77)?;
        if input.number()? != generation {
            return Err(AtomicError::Corrupt);
        }
        input.identity()?;
        if input.identity()? != record.fingerprint {
            return Err(AtomicError::Corrupt);
        }
        input.finish()?;
        let removed_index = delete(captured, usage, key, bytes)?;
        let removed_retry = delete(captured, usage, retry_key, retry)?;
        reclaimed = reclaimed
            .checked_add(removed_index)
            .and_then(|n| n.checked_add(removed_retry))
            .ok_or(AtomicError::Corrupt)?;
    }
    usage.results = usage.results.checked_sub(1).ok_or(AtomicError::Corrupt)?;
    captured.namespace.pins.retained_results = captured
        .namespace
        .pins
        .retained_results
        .checked_sub(1)
        .ok_or(AtomicError::Corrupt)?;
    Ok(reclaimed)
}

fn delete(
    captured: &mut Captured,
    usage: &mut Usage,
    key: RowKey,
    bytes: Vec<u8>,
) -> Result<u64, AtomicError> {
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(row_charge(&key, &bytes)?)
        .ok_or(AtomicError::Corrupt)?;
    let reclaimed = (key.key.len() + bytes.len() + 1) as u64;
    captured.plan.replace(key, Some(bytes), None)?;
    Ok(reclaimed)
}
