//! Closed startup validation over a single worker-owned view. Page and point
//! reads stay bounded; no collection of the complete store or native owner escapes.

use super::{
    codec::Decoder,
    record::{attempt_row_key, command_row_key, result_row_key},
    retention::{ExpiredResult, MaintenanceProgress, PROGRESS_KEY},
    AtomicError, CommandRecord, DurableResult, Identity, Outcome, ReplayPolicy,
};
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    reservation::{reservation_key, LogicalReservation, KEY_PREFIX},
};

const COMMAND: &[u8] = b"command-v1\0";
const ATTEMPT: &[u8] = b"command-attempt-v1\0";
const RESULT: &[u8] = b"command-result-v1\0";
const INBOX: &[u8] = b"inbox-v1\0";
const USAGE: &[u8] = b"command-usage-v1\0";
const RETRY: &[u8] = b"command-retry-v1\0";

/// Validate only this owner's declared families and prefixes. Unknown formats
/// fail closed and must be routed to their installed codec owner explicitly.
pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    validate_local(key, bytes).map_err(storage_error)
}

fn validate_local(key: &RowKey, bytes: &[u8]) -> Result<(), AtomicError> {
    match key.family {
        Family::Command if key.key.starts_with(COMMAND) => {
            let record = CommandRecord::decode(bytes)?;
            if *key != command_row_key(record.id) {
                return Err(AtomicError::Corrupt);
            }
        }
        Family::Attempt if key.key.starts_with(ATTEMPT) => {
            let record = CommandRecord::decode(bytes)?;
            if *key != attempt_row_key(record.id, record.attempt) {
                return Err(AtomicError::Corrupt);
            }
        }
        Family::Result if key.key.starts_with(RESULT) => {
            let (command, attempt) = identity_attempt(key, RESULT)?;
            if bytes.starts_with(b"LCP\0") {
                let (id, generation, _) = pending(bytes)?;
                if command != id || attempt != generation {
                    return Err(AtomicError::Corrupt);
                }
            } else if bytes.starts_with(b"LCE\0") {
                let result = ExpiredResult::decode(bytes)?;
                if command != result.command || attempt != result.attempt {
                    return Err(AtomicError::Corrupt);
                }
            } else {
                let result = DurableResult::decode(bytes)?;
                if command != result.command || attempt != result.attempt {
                    return Err(AtomicError::Corrupt);
                }
            }
        }
        Family::Inbox if key.key.starts_with(INBOX) => {
            identity(key, INBOX)?;
            inbox(bytes)?;
        }
        Family::Maintenance if key.key == PROGRESS_KEY => {
            MaintenanceProgress::decode(bytes)?;
        }
        Family::Maintenance if key.key.starts_with(USAGE) => {
            namespace_usage_key(&key.key[USAGE.len()..])?;
            let mut input = Decoder::new(bytes, b"LCU\0\x01", 61)?;
            let results = input.number()?;
            let result_bytes = input.number()?;
            let effects = input.number()?;
            let effect_bytes = input.number()?;
            let payload_bytes = input.number()?;
            let reserved = input.number()?;
            let recovery_reserved = input.number()?;
            input.finish()?;
            if results > 1_000_000
                || effects > 1_000_000
                || [
                    result_bytes,
                    effect_bytes,
                    payload_bytes,
                    reserved,
                    recovery_reserved,
                ]
                .iter()
                .any(|v| *v > 1024 * 1024 * 1024)
                || reserved > result_bytes
                || recovery_reserved > reserved
            {
                return Err(AtomicError::Corrupt);
            }
        }
        Family::Maintenance if key.key.starts_with(RETRY) => {
            identity(key, RETRY)?;
            let mut input = Decoder::new(bytes, b"LCT\0\x01", 77)?;
            if !(2..=16).contains(&input.number()?) {
                return Err(AtomicError::Corrupt);
            }
            input.identity()?;
            input.identity()?;
            input.finish()?;
        }
        Family::Maintenance
            if key.key.starts_with(KEY_PREFIX) && key.key.len() == KEY_PREFIX.len() + 32 =>
        {
            let reservation = LogicalReservation::decode(bytes)?;
            if reservation.generation > 16 || reservation.bytes > 2 * 1024 * 1024 {
                return Err(AtomicError::Corrupt);
            }
        }
        _ => return Err(AtomicError::UnsupportedFormat),
    }
    Ok(())
}

/// Check command/attempt/result/inbox/reservation linkage from this same view.
/// This does not infer a recovery grant or prior physical retirement from bytes.
pub fn validate_linked_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    validate_linked(view, key, bytes).map_err(storage_error)
}

fn validate_linked(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), AtomicError> {
    validate_local(key, bytes)?;
    match key.family {
        Family::Command => {
            let command = CommandRecord::decode(bytes)?;
            let current_attempt = required(view, &attempt_row_key(command.id, command.attempt))?;
            if current_attempt != bytes {
                return Err(AtomicError::Corrupt);
            }
            for generation in 1..command.attempt {
                let prior = CommandRecord::decode(&required(
                    view,
                    &attempt_row_key(command.id, generation),
                )?)?;
                if prior.outcome != Outcome::Aborted || !same_original(&prior, &command) {
                    return Err(AtomicError::Corrupt);
                }
            }
            validate_disposition(view, &command)?;
        }
        Family::Attempt => {
            let attempt = CommandRecord::decode(bytes)?;
            let current = CommandRecord::decode(&required(view, &command_row_key(attempt.id))?)?;
            if current.attempt < attempt.attempt
                || !same_original(&attempt, &current)
                || (current.attempt == attempt.attempt && current != attempt)
                || (current.attempt > attempt.attempt && attempt.outcome != Outcome::Aborted)
            {
                return Err(AtomicError::Corrupt);
            }
            validate_disposition(view, &attempt)?;
        }
        Family::Result => {
            let (id, generation) = identity_attempt(key, RESULT)?;
            let record = CommandRecord::decode(&required(view, &attempt_row_key(id, generation))?)?;
            verify_result(bytes, &record)?;
        }
        Family::Inbox => {
            let marker = inbox(bytes)?;
            let record = CommandRecord::decode(&required(
                view,
                &attempt_row_key(marker.command, marker.attempt),
            )?)?;
            let approved = record.inbox.as_ref().ok_or(AtomicError::Corrupt)?;
            if approved.row_key(&record.key)? != *key
                || record.outcome != marker.outcome
                || approved.payload_digest != marker.payload
                || record.completed_at != marker.completed_at
            {
                return Err(AtomicError::Corrupt);
            }
        }
        Family::Maintenance if key.key.starts_with(KEY_PREFIX) => {
            let id = identity(key, KEY_PREFIX)?;
            let record = CommandRecord::decode(&required(view, &command_row_key(id))?)?;
            let reservation = LogicalReservation::decode(bytes)?;
            if record.outcome != Outcome::Pending
                || record.attempt != reservation.generation
                || reservation.bytes != record.result_policy.reservation()?
            {
                return Err(AtomicError::Corrupt);
            }
        }
        _ => {}
    }
    Ok(())
}

fn same_original(one: &CommandRecord, two: &CommandRecord) -> bool {
    one.id == two.id
        && one.key == two.key
        && one.fingerprint == two.fingerprint
        && one.source == two.source
        && one.result_read_policy == two.result_read_policy
        && one.result_policy == two.result_policy
        && one.admitted_at == two.admitted_at
        && one.result_expires == two.result_expires
        && one.identity_expires == two.identity_expires
        && one.inbox == two.inbox
}

fn validate_disposition(view: &ReadView, record: &CommandRecord) -> Result<(), AtomicError> {
    verify_result(
        &required(view, &result_row_key(record.id, record.attempt))?,
        record,
    )?;
    let reservation = view.get(&reservation_key(&record.id.0)?)?;
    if record.outcome == Outcome::Pending {
        let reservation =
            LogicalReservation::decode(reservation.as_deref().ok_or(AtomicError::Corrupt)?)?;
        if reservation.generation != record.attempt
            || reservation.bytes != record.result_policy.reservation()?
        {
            return Err(AtomicError::Corrupt);
        }
    }
    for effect in &record.effects {
        let bytes = required(
            view,
            &latent_effects::dispatch_store::effect_row_key(&effect.hex())?,
        )?;
        let effect_record = latent_effects::dispatch::EffectRecord::decode(&bytes)?;
        let authority = effect_record.authority()?;
        if authority.link().command != record.id.hex()
            || authority.link().attempt != record.attempt
            || authority.link().commit != record.disposition_id().hex()
            || authority.link().effect != effect.hex()
            || authority.scope().tenant != record.key.tenant
            || authority.scope().namespace != record.key.namespace
            || authority.scope().incarnation != super::incarnation(&record.key)?
            || authority.link().caller_scope != record.key.recovery_scope
        {
            return Err(AtomicError::Corrupt);
        }
        let payload = latent_effects::payload::PayloadRecord::decode(&required(
            view,
            &latent_effects::dispatch_store::effect_payload_key(&effect.hex())?,
        )?)?;
        payload.verify(&authority)?;
    }
    if matches!(record.outcome, Outcome::Committed | Outcome::Rejected) {
        if let Some(identity) = &record.inbox {
            let marker = inbox(&required(view, &identity.row_key(&record.key)?)?)?;
            if marker.command != record.id
                || marker.attempt != record.attempt
                || marker.outcome != record.outcome
                || marker.payload != identity.payload_digest
                || marker.completed_at != record.completed_at
            {
                return Err(AtomicError::Corrupt);
            }
        }
    }
    Ok(())
}

fn verify_result(bytes: &[u8], record: &CommandRecord) -> Result<(), AtomicError> {
    if record.outcome == Outcome::Pending {
        let (id, generation, replay) = pending(bytes)?;
        if id != record.id || generation != record.attempt || replay != record.result_policy.replay
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    } else if bytes.starts_with(b"LCE\0") {
        ExpiredResult::decode(bytes)?.verify(record)
    } else {
        DurableResult::decode(bytes)?.verify(record)
    }
}

/// Run all ten logical families in bounded coherent pages. A foreign codec
/// callback is mandatory for namespaces, state, dispatcher history and indexes;
/// it must reject uninstalled formats rather than accepting opaque records.
pub fn validate_view(
    view: &ReadView,
    mut foreign: impl FnMut(&ReadView, &RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    let mut total = 0usize;
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        let mut resume = None;
        loop {
            let page = view.scan_after(family, b"", resume.as_deref(), 128, 2 * 1024 * 1024)?;
            total = total
                .checked_add(page.rows.len())
                .ok_or(StoreError::Capacity)?;
            if total > 65_536 {
                return Err(StoreError::Capacity);
            }
            for (key, bytes) in &page.rows {
                match validate_linked_row(view, key, bytes) {
                    Err(StoreError::UnsupportedFormat) => foreign(view, key, bytes)?,
                    other => other?,
                }
                if (key.family == Family::Outbox
                    && key
                        .key
                        .starts_with(latent_effects::dispatch_store::EFFECT_PREFIX))
                    || (key.family == Family::PayloadReference
                        && key
                            .key
                            .starts_with(latent_effects::dispatch_store::PAYLOAD_PREFIX))
                {
                    validate_effect_link(view, key, bytes).map_err(storage_error)?;
                }
            }
            match page.resume {
                Some(next) => resume = Some(next),
                None => break,
            }
        }
    }
    Ok(())
}

fn validate_effect_link(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), AtomicError> {
    let effect = if key.family == Family::Outbox {
        latent_effects::dispatch::EffectRecord::decode(bytes)?
            .authority()?
            .link()
            .effect
            .clone()
    } else {
        latent_effects::payload::PayloadRecord::decode(bytes)?
            .effect()
            .to_owned()
    };
    let record = latent_effects::dispatch::EffectRecord::decode(&required(
        view,
        &latent_effects::dispatch_store::effect_row_key(&effect)?,
    )?)?;
    let authority = record.authority()?;
    let command_id = parse_identity(&authority.link().command)?;
    let command = CommandRecord::decode(&required(
        view,
        &attempt_row_key(command_id, authority.link().attempt),
    )?)?;
    if command.outcome != Outcome::Committed
        || command
            .effect_ids()
            .get(authority.link().sequence as usize)
            .map(|i| i.hex())
            .as_deref()
            != Some(effect.as_str())
        || authority.link().commit != command.disposition_id().hex()
        || authority.link().caller_scope != command.key.recovery_scope
        || authority.scope().tenant != command.key.tenant
        || authority.scope().namespace != command.key.namespace
        || authority.scope().incarnation != super::incarnation(&command.key)?
        || authority.scope().publication != command.source.publication
    {
        return Err(AtomicError::Corrupt);
    }
    let payload = latent_effects::payload::PayloadRecord::decode(&required(
        view,
        &latent_effects::dispatch_store::effect_payload_key(&effect)?,
    )?)?;
    payload.verify(&authority)?;
    Ok(())
}

fn parse_identity(text: &str) -> Result<Identity, AtomicError> {
    if text.len() != 64 {
        return Err(AtomicError::Corrupt);
    }
    let mut bytes = [0u8; 32];
    for (slot, pair) in bytes.iter_mut().zip(text.as_bytes().chunks_exact(2)) {
        let digit = |byte| match byte {
            b'0'..=b'9' => Ok(byte - b'0'),
            b'a'..=b'f' => Ok(byte - b'a' + 10),
            _ => Err(AtomicError::Corrupt),
        };
        *slot = (digit(pair[0])? << 4) | digit(pair[1])?;
    }
    Ok(Identity(bytes))
}

fn identity(key: &RowKey, prefix: &[u8]) -> Result<Identity, AtomicError> {
    if !key.key.starts_with(prefix) || key.key.len() != prefix.len() + 32 {
        return Err(AtomicError::Corrupt);
    }
    Ok(Identity(
        key.key[prefix.len()..]
            .try_into()
            .map_err(|_| AtomicError::Corrupt)?,
    ))
}
fn identity_attempt(key: &RowKey, prefix: &[u8]) -> Result<(Identity, u64), AtomicError> {
    if !key.key.starts_with(prefix) || key.key.len() != prefix.len() + 40 {
        return Err(AtomicError::Corrupt);
    }
    let id = Identity(
        key.key[prefix.len()..prefix.len() + 32]
            .try_into()
            .map_err(|_| AtomicError::Corrupt)?,
    );
    let generation = u64::from_be_bytes(
        key.key[prefix.len() + 32..]
            .try_into()
            .map_err(|_| AtomicError::Corrupt)?,
    );
    if generation == 0 || generation > 16 {
        return Err(AtomicError::Corrupt);
    }
    Ok((id, generation))
}
fn pending(bytes: &[u8]) -> Result<(Identity, u64, ReplayPolicy), AtomicError> {
    let mut input = Decoder::new(bytes, b"LCP\0\x01", 46)?;
    let id = input.identity()?;
    let generation = input.number()?;
    let replay = match input.byte()? {
        1 => ReplayPolicy::Full,
        2 => ReplayPolicy::ReceiptOnly,
        _ => return Err(AtomicError::Corrupt),
    };
    input.finish()?;
    if generation == 0 || generation > 16 {
        return Err(AtomicError::Corrupt);
    }
    Ok((id, generation, replay))
}
struct InboxMarker {
    command: Identity,
    attempt: u64,
    outcome: Outcome,
    payload: Identity,
    completed_at: u64,
}
fn inbox(bytes: &[u8]) -> Result<InboxMarker, AtomicError> {
    let mut input = Decoder::new(bytes, b"LIC\0\x01", 86)?;
    let command = input.identity()?;
    let attempt = input.number()?;
    let outcome = match input.byte()? {
        1 => Outcome::Committed,
        2 => Outcome::Rejected,
        _ => return Err(AtomicError::Corrupt),
    };
    let payload = input.identity()?;
    let completed_at = input.number()?;
    input.finish()?;
    if attempt == 0 || attempt > 16 {
        return Err(AtomicError::Corrupt);
    }
    Ok(InboxMarker {
        command,
        attempt,
        outcome,
        payload,
        completed_at,
    })
}
fn required(view: &ReadView, key: &RowKey) -> Result<Vec<u8>, AtomicError> {
    view.get(key)?.ok_or(AtomicError::Corrupt)
}
fn namespace_usage_key(bytes: &[u8]) -> Result<(), AtomicError> {
    let mut rest = bytes.strip_prefix(b"ns-v1\0").ok_or(AtomicError::Corrupt)?;
    for _ in 0..2 {
        let header = rest.get(..2).ok_or(AtomicError::Corrupt)?;
        let length = usize::from(u16::from_le_bytes(
            header.try_into().map_err(|_| AtomicError::Corrupt)?,
        ));
        if !(1..=256).contains(&length) {
            return Err(AtomicError::Corrupt);
        }
        let text = std::str::from_utf8(rest.get(2..2 + length).ok_or(AtomicError::Corrupt)?)
            .map_err(|_| AtomicError::Corrupt)?;
        super::id(text).map_err(|_| AtomicError::Corrupt)?;
        rest = &rest[2 + length..];
    }
    if rest.len() != 8
        || u64::from_le_bytes(rest.try_into().map_err(|_| AtomicError::Corrupt)?) == 0
    {
        return Err(AtomicError::Corrupt);
    }
    Ok(())
}
fn storage_error(error: AtomicError) -> StoreError {
    match error {
        AtomicError::UnsupportedFormat => StoreError::UnsupportedFormat,
        AtomicError::Limit => StoreError::Capacity,
        AtomicError::Expired => StoreError::SnapshotExpired,
        AtomicError::Unavailable | AtomicError::RecoveryRequired => StoreError::Unavailable,
        _ => StoreError::Corrupt,
    }
}
