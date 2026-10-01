//! Explicit destructive maintenance may operate on an already quiesced scope.
//! It never resumes that scope or bypasses a pending history/restore review.

use crate::{
    embedded::{ExpectedRow, Family, ReadView, RowKey, StoreError},
    namespace::{
        history::{history_key, HistoryStatus, NamespaceHistory},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
};
use latent_core::{StateNamespaceId, TenantId};

/// Closed observations for the existing authorized maintenance worker. The
/// caller still supplies its current destructive policy and retirement proof.
/// Global restore guards and namespace history remain mandatory in every state.
pub fn namespace_expectations(
    view: &ReadView,
    tenant: &TenantId,
    namespace: &StateNamespaceId,
    incarnation: u64,
) -> Result<[ExpectedRow; 3], StoreError> {
    super::require_ready(view)?;
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
    };
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    let record = NamespaceRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
    if record.tenant != *tenant
        || record.id != *namespace
        || record.version.incarnation != incarnation
    {
        return Err(StoreError::Conflict);
    }
    if !matches!(
        record.status,
        NamespaceStatus::Active | NamespaceStatus::Quiescing | NamespaceStatus::Retired
    ) {
        return Err(StoreError::Unavailable);
    }
    let (history, _) = NamespaceHistory::capture(view, &record)?;
    if history.status != HistoryStatus::Ready {
        return Err(StoreError::Unavailable);
    }
    Ok([
        ExpectedRow {
            key: super::guard_key(),
            value: view.get(&super::guard_key())?,
        },
        ExpectedRow {
            key,
            value: Some(bytes),
        },
        ExpectedRow {
            key: history_key(tenant, namespace, incarnation).map_err(|_| StoreError::Invalid)?,
            value: view.get(
                &history_key(tenant, namespace, incarnation).map_err(|_| StoreError::Invalid)?,
            )?,
        },
    ])
}
