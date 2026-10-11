//! The fixed transformer uses the original state cell and namespace usage
//! codecs. Exclusive custody and current authorization belong to its caller.

use super::{codec, state_key, usage_key, Cell, StateError, StateMode, StateScope, Usage};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowMutation, StoreError},
    namespace::{NamespaceRecord, NamespaceStatus},
    recovery::migration::AggregateMigrationRecipe,
};
use latent_core::transaction_contract::Value;

pub(crate) fn aggregate_v1_to_v2(
    view: &ReadView,
    namespace: &NamespaceRecord,
    recipe: AggregateMigrationRecipe,
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
    // Inspect the whole namespace/incarnation, including entity-selected cells.
    prefix.pop().ok_or(StoreError::Invalid)?;
    let page = view.scan_after(Family::State, &prefix, None, 2, 4096)?;
    let key = state_key(&scope, recipe.key()).map_err(storage_error)?;
    if page.resume.is_some() || page.rows.len() != 1 || page.rows[0].0 != key {
        return Err(StoreError::UnsupportedFormat);
    }
    let original = &page.rows[0].1;
    let migrated = transform(original, namespace)?;
    let usage_key = usage_key(&scope).map_err(storage_error)?;
    let original_usage = view
        .get_bounded(&usage_key, 4096)?
        .ok_or(StoreError::Corrupt)?;
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

fn transform(original: &[u8], namespace: &NamespaceRecord) -> Result<Vec<u8>, StoreError> {
    let cell = Cell::decode(original, namespace.version.generation).map_err(storage_error)?;
    let value = cell.value.ok_or(StoreError::UnsupportedFormat)?;
    if value.bytes.len() != 8
        || value.media_type != "application/vnd.lsf.aggregate-v1"
        || !value.metadata.is_empty()
    {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut bytes = b"AG\x02\0".to_vec();
    bytes.extend_from_slice(&value.bytes);
    Cell {
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
    .map_err(storage_error)
}

fn storage_error(error: StateError) -> StoreError {
    match error {
        StateError::Limit => StoreError::Capacity,
        StateError::Invalid => StoreError::Invalid,
        StateError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Corrupt,
    }
}
