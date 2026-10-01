//! Fixed offline recipe using the same state cell and quota codecs as commands.
//! The physical recovery facade proves exclusive ownership and quiescence.

use super::{codec, state_key, usage_key, Cell, StateError, StateMode, StateScope, Usage};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowMutation, StoreError},
    namespace::{NamespaceRecord, NamespaceStatus},
};
use latent_core::transaction_contract::Value;

pub(crate) fn aggregate_v1_to_v2(
    view: &ReadView,
    namespace: &NamespaceRecord,
    recipe: crate::recovery::migration::AggregateMigrationRecipe,
) -> Result<AtomicBatch, StoreError> {
    namespace.validate().map_err(|_| StoreError::Corrupt)?;
    if namespace.status != NamespaceStatus::Quiescing {
        return Err(StoreError::Conflict);
    }
    let scope = StateScope {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        incarnation: namespace.version.incarnation,
        state_schema: namespace.state_schema.clone(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut prefix = codec::key_prefix(&scope).map_err(storage_error)?;
    // Inspect the whole namespace/incarnation, including entity-selected keys.
    prefix.pop().ok_or(StoreError::Invalid)?;
    // The fixed recipe handles one tiny cell. Refuse oversized physical rows
    // in the engine's borrowed scan, before lifting or decoding their value.
    let page = view.scan_after(Family::State, &prefix, None, 2, 4096)?;
    let key = state_key(&scope, recipe.key()).map_err(storage_error)?;
    if page.resume.is_some() || page.rows.len() != 1 || page.rows[0].0 != key {
        return Err(StoreError::UnsupportedFormat);
    }
    let original = &page.rows[0].1;
    let cell = Cell::decode(original, namespace.version.generation).map_err(storage_error)?;
    let value = cell.value.ok_or(StoreError::UnsupportedFormat)?;
    if value.bytes.len() != 8
        || value.media_type != "application/vnd.lsf.aggregate-v1"
        || !value.metadata.is_empty()
    {
        return Err(StoreError::UnsupportedFormat);
    }
    let usage_key = usage_key(&scope).map_err(storage_error)?;
    let usage_page = view.scan_after(usage_key.family, &usage_key.key, None, 1, 4096)?;
    let (observed_usage_key, original_usage) = usage_page
        .rows
        .into_iter()
        .next()
        .ok_or(StoreError::Corrupt)?;
    if observed_usage_key != usage_key {
        return Err(StoreError::Corrupt);
    }
    let mut usage = Usage::decode(&original_usage).map_err(storage_error)?;
    let old_bytes =
        u64::try_from(recipe.key().len() + original.len()).map_err(|_| StoreError::Capacity)?;
    if usage.keys != 1
        || usage.bytes != old_bytes
        || usage.tombstones != 0
        || usage.tombstone_bytes != 0
    {
        return Err(StoreError::Corrupt);
    }
    let mut bytes = b"AG\x02\0".to_vec();
    bytes.extend_from_slice(&value.bytes);
    let migrated = Cell {
        generation: namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?,
        value: Some(Value {
            bytes,
            media_type: "application/vnd.lsf.aggregate-v2".into(),
            metadata: vec![],
        }),
    }
    .encode()
    .map_err(storage_error)?;
    usage.bytes =
        u64::try_from(recipe.key().len() + migrated.len()).map_err(|_| StoreError::Capacity)?;
    if usage.bytes > namespace.quota.state_bytes {
        return Err(StoreError::Capacity);
    }
    Ok(AtomicBatch {
        expectations: vec![
            ExpectedRow {
                key: key.clone(),
                value: Some(original.clone()),
            },
            ExpectedRow {
                key: usage_key.clone(),
                value: Some(original_usage),
            },
        ],
        mutations: vec![
            RowMutation {
                key,
                value: Some(migrated),
            },
            RowMutation {
                key: usage_key,
                value: Some(usage.encode()),
            },
        ],
    })
}

fn storage_error(error: StateError) -> StoreError {
    match error {
        StateError::Limit => StoreError::Capacity,
        StateError::Invalid => StoreError::Invalid,
        StateError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Corrupt,
    }
}
