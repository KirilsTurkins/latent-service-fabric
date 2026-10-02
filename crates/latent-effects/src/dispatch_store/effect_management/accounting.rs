//! Original optional management metadata joins the SAME namespace and tenant
//! ledgers. No extra quota owner, automatic migration or refreshed clock exists.

use super::{EffectManagementCatalog, EffectManagementError, RESERVATION_OWNER_PREFIX};
use crate::authority::EffectScope;
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{namespace_record_key, NamespaceRecord, RECORD_BYTES},
    reservation::{namespace_ledger_key, LogicalReservation, NamespaceLedger, QUOTA_BYTES},
    tenant::{self, TenantDelta, TenantUsage},
};

/// Includes exact metadata row storage and the original future disposition
/// reservation. Successful completion removes only its own promised bytes.
pub(super) fn charge(key: &RowKey, bytes: &[u8]) -> Result<u64, StoreError> {
    EffectManagementCatalog::validate_row(key, bytes)?;
    let mut reserved_prefix = latent_state::reservation::KEY_PREFIX.to_vec();
    reserved_prefix.extend_from_slice(RESERVATION_OWNER_PREFIX);
    let promised = if key.key.starts_with(&reserved_prefix) {
        LogicalReservation::decode(bytes)?.bytes
    } else {
        0
    };
    tenant::row_charge(key, bytes)?
        .checked_add(promised)
        .ok_or(StoreError::Capacity)
}

pub(super) fn append(
    view: &ReadView,
    scope: &EffectScope,
    batch: &mut AtomicBatch,
) -> Result<(), EffectManagementError> {
    let tenant = TenantId(scope.tenant.clone());
    let namespace = StateNamespaceId(scope.namespace.clone());
    let accounting = tenant::prepare_update(view, &tenant, TenantDelta::default())?;
    let ledger_key = namespace_ledger_key(&tenant, &namespace, scope.incarnation)?;
    let original = view.get_bounded(&ledger_key, QUOTA_BYTES)?;
    let Some(original) = original else {
        if !accounting.is_legacy() {
            return Err(StoreError::UnsupportedFormat.into());
        }
        accounting.append_read_expectations(batch)?;
        return Ok(());
    };
    let mut ledger = NamespaceLedger::decode(&original)?;
    if !ledger.is_accounted() {
        if !accounting.is_legacy() {
            return Err(StoreError::UnsupportedFormat.into());
        }
        // Exact LCU1 readers remain supported. A current host must select an
        // explicit accounting migration before installing tenant declarations.
        accounting.append_read_expectations(batch)?;
        return Ok(());
    }
    if batch.mutations.is_empty() {
        accounting.append_read_expectations(batch)?;
        return Ok(());
    }
    let namespace_key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&tenant, &namespace).map_err(|_| StoreError::Invalid)?,
    };
    let namespace_bytes = view
        .get_bounded(&namespace_key, RECORD_BYTES)?
        .ok_or(StoreError::Corrupt)?;
    let record = NamespaceRecord::decode(&namespace_bytes).map_err(|_| StoreError::Corrupt)?;
    latent_state::namespace::catalog::NamespaceCatalog::validate_row(
        &namespace_key,
        &namespace_bytes,
    )
    .map_err(|_| StoreError::Corrupt)?;
    if record.tenant != tenant
        || record.id != namespace
        || record.version.incarnation != scope.incarnation
    {
        return Err(EffectManagementError::Conflict);
    }
    let (removed, added) = delta(view, batch)?;
    ledger.adjust_effect_bytes(removed, added)?;
    ledger.check(&record)?;
    expect(
        batch,
        ExpectedRow {
            key: namespace_key,
            value: Some(namespace_bytes),
        },
    )?;
    expect(
        batch,
        ExpectedRow {
            key: ledger_key.clone(),
            value: Some(original),
        },
    )?;
    if batch.mutations.iter().any(|row| row.key == ledger_key) {
        return Err(StoreError::Corrupt.into());
    }
    batch.mutations.push(RowMutation {
        key: ledger_key,
        value: Some(ledger.encode()),
    });
    tenant::prepare_update(
        view,
        &tenant,
        TenantDelta {
            removed: TenantUsage {
                effect_bytes: removed,
                ..TenantUsage::default()
            },
            added: TenantUsage {
                effect_bytes: added,
                ..TenantUsage::default()
            },
        },
    )?
    .append_to(batch)?;
    Ok(())
}

fn delta(view: &ReadView, batch: &AtomicBatch) -> Result<(u64, u64), StoreError> {
    if batch.expectations.len() > 1024 || batch.mutations.len() > 1024 {
        return Err(StoreError::Capacity);
    }
    let mut removed = 0u64;
    let mut added = 0u64;
    for (index, row) in batch
        .mutations
        .iter()
        .enumerate()
        .filter(|(_, row)| EffectManagementCatalog::owns_row(&row.key))
    {
        if batch.mutations[..index]
            .iter()
            .any(|old| old.key == row.key)
        {
            return Err(StoreError::Corrupt);
        }
        let mut originals = batch.expectations.iter().filter(|old| old.key == row.key);
        let original = originals.next().ok_or(StoreError::Corrupt)?;
        if originals.next().is_some() {
            return Err(StoreError::Corrupt);
        }
        let actual = view.get_bounded(&row.key, super::MAXIMUM_RECEIPT_BYTES)?;
        if original.value != actual {
            return Err(StoreError::Conflict);
        }
        if let Some(bytes) = original.value.as_deref() {
            removed = removed
                .checked_add(charge(&row.key, bytes)?)
                .ok_or(StoreError::Capacity)?;
        }
        if let Some(bytes) = row.value.as_deref() {
            added = added
                .checked_add(charge(&row.key, bytes)?)
                .ok_or(StoreError::Capacity)?;
        }
    }
    Ok((removed, added))
}

fn expect(batch: &mut AtomicBatch, expected: ExpectedRow) -> Result<(), StoreError> {
    let mut matching = batch
        .expectations
        .iter()
        .filter(|row| row.key == expected.key);
    if let Some(old) = matching.next() {
        if old.value != expected.value || matching.next().is_some() {
            return Err(StoreError::Conflict);
        }
    } else {
        batch.expectations.push(expected);
    }
    Ok(())
}
