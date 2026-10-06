//! One bounded metadata-only engine-format transition, on the existing worker.
//! Application schema, command/effect identities and records-v1 stay unchanged.
use redb::{Database, Durability, ReadableDatabase, ReadableTable};

use super::{StoreError, META, ROWS};

pub(super) const V1: &[u8] = b"latent.transaction-store.v1";
pub(super) const V2: &[u8] = b"latent.transaction-store.v2";
pub(super) const LAYOUT: &[u8] = b"redb-4.3/immediate/records-v1/families-1-10/raw-key-value";
pub(super) const UPGRADE: &[u8] = b"latent.store-upgrade.v1/1-to-2/metadata";
const MAXIMUM_FIELDS: usize = 3;
const MAXIMUM_FIELD_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum State {
    Legacy,
    UpgradePending,
    Current,
}

/// Fixed test observation points. Production supplies a synchronous no-op;
/// there is no exported hook, async work, replacement owner or per-row progress.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Checkpoint {
    NewEngineOpened,
    InitialSchemaDurable,
    UpgradeIntentDurable,
    CurrentSchemaDurable,
}

pub(super) fn inspect(db: &Database) -> Result<State, StoreError> {
    let tx = db.begin_read().map_err(|_| StoreError::Unavailable)?;
    let meta = tx
        .open_table(META)
        .map_err(|_| StoreError::UnsupportedFormat)?;
    // Borrow engine bytes. Even a malformed persisted metadata value is never
    // copied into a Vec/string before its finite size and closed key are checked.
    for (index, row) in meta.iter().map_err(|_| StoreError::Corrupt)?.enumerate() {
        let (key, value) = row.map_err(|_| StoreError::Corrupt)?;
        if index >= MAXIMUM_FIELDS
            || !matches!(key.value(), "schema" | "record-layout" | "upgrade")
            || value.value().len() > MAXIMUM_FIELD_BYTES
        {
            return Err(StoreError::Corrupt);
        }
    }
    let schema = meta
        .get("schema")
        .map_err(|_| StoreError::Corrupt)?
        .ok_or(StoreError::UnsupportedFormat)?;
    let layout = meta.get("record-layout").map_err(|_| StoreError::Corrupt)?;
    let upgrade = meta.get("upgrade").map_err(|_| StoreError::Corrupt)?;
    match schema.value() {
        V1 if layout.is_none() => match upgrade {
            None => Ok(State::Legacy),
            Some(value) if value.value() == UPGRADE => Ok(State::UpgradePending),
            Some(_) => Err(StoreError::Corrupt),
        },
        V2 if upgrade.is_none() => match layout {
            Some(value) if value.value() == LAYOUT => Ok(State::Current),
            Some(_) => Err(StoreError::UnsupportedFormat),
            None => Err(StoreError::Corrupt),
        },
        V1 | V2 => Err(StoreError::Corrupt),
        _ => Err(StoreError::UnsupportedFormat),
    }
}

/// First create the same durable legacy schema/records transaction as v1.
/// A valid seed is resumable; an interrupted header without a seed is refused,
/// never mistaken for an empty database that may be reset automatically.
pub(super) fn initialize(db: &Database) -> Result<(), StoreError> {
    let mut tx = db.begin_write().map_err(|_| StoreError::Unavailable)?;
    tx.set_durability(Durability::Immediate)
        .map_err(|_| StoreError::Unavailable)?;
    {
        let mut meta = tx.open_table(META).map_err(|_| StoreError::Corrupt)?;
        meta.insert("schema", V1)
            .map_err(|_| StoreError::Unavailable)?;
        tx.open_table(ROWS).map_err(|_| StoreError::Corrupt)?;
    }
    tx.commit().map_err(|_| StoreError::CommitUncertain)
}

/// The exclusive database/root owner runs this finite transition before Ready.
/// First persist its exact intent with the original schema. Then atomically
/// publish the compatible record-layout contract and v2 and remove the intent.
/// An uncertain write gates startup; reopening can inspect either durable phase.
pub(super) fn upgrade(
    db: &Database,
    checkpoint: &mut impl FnMut(Checkpoint),
) -> Result<(), StoreError> {
    let state = inspect(db)?;
    if state == State::Current {
        return Ok(());
    }
    if state == State::Legacy {
        let mut tx = db.begin_write().map_err(|_| StoreError::Unavailable)?;
        tx.set_durability(Durability::Immediate)
            .map_err(|_| StoreError::Unavailable)?;
        {
            let mut meta = tx.open_table(META).map_err(|_| StoreError::Corrupt)?;
            meta.insert("upgrade", UPGRADE)
                .map_err(|_| StoreError::Unavailable)?;
        }
        tx.commit().map_err(|_| StoreError::CommitUncertain)?;
    }
    checkpoint(Checkpoint::UpgradeIntentDurable);
    let mut tx = db.begin_write().map_err(|_| StoreError::Unavailable)?;
    tx.set_durability(Durability::Immediate)
        .map_err(|_| StoreError::Unavailable)?;
    {
        let mut meta = tx.open_table(META).map_err(|_| StoreError::Corrupt)?;
        meta.insert("record-layout", LAYOUT)
            .map_err(|_| StoreError::Unavailable)?;
        meta.insert("schema", V2)
            .map_err(|_| StoreError::Unavailable)?;
        meta.remove("upgrade")
            .map_err(|_| StoreError::Unavailable)?;
    }
    tx.commit().map_err(|_| StoreError::CommitUncertain)?;
    checkpoint(Checkpoint::CurrentSchemaDurable);
    Ok(())
}
