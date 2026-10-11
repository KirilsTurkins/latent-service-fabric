//! Bounded original upper ledger/linked-row descriptions for the shared scan.
//! No counter is inferred from new grants, results or current namespace tokens.
use super::{writer::Usage, AtomicError};
use latent_core::TenantId;
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    tenant::{TenantCensusContribution, TenantUsage},
};

pub fn tenant_census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    super::validate_linked_row(view, key, bytes)?;
    if key.family == Family::Maintenance && key.key.as_slice() == super::retention::PROGRESS_KEY {
        return Ok(TenantCensusContribution::Global);
    }
    if key.family == Family::Maintenance
        && key.key.starts_with(latent_state::reservation::QUOTA_PREFIX)
    {
        return usage(view, key, bytes).map_err(storage_error);
    }
    let tenant =
        super::validation::tenant_for_linked_row(view, key, bytes).map_err(storage_error)?;
    Ok(TenantCensusContribution::Covered { tenant })
}

fn usage(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, AtomicError> {
    let ledger = Usage::decode(bytes)?;
    if !ledger.accounted {
        return Err(AtomicError::UnsupportedFormat);
    }
    let namespace_key = key
        .key
        .strip_prefix(latent_state::reservation::QUOTA_PREFIX)
        .ok_or(AtomicError::Corrupt)?;
    let incarnation_offset = namespace_key
        .len()
        .checked_sub(8)
        .ok_or(AtomicError::Corrupt)?;
    let incarnation = u64::from_le_bytes(
        namespace_key[incarnation_offset..]
            .try_into()
            .map_err(|_| AtomicError::Corrupt)?,
    );
    let row = RowKey {
        family: Family::Namespace,
        key: namespace_key[..incarnation_offset].to_vec(),
    };
    let namespace = latent_state::namespace::NamespaceRecord::decode(
        &view.get_bounded(&row, 4096)?.ok_or(AtomicError::Corrupt)?,
    )
    .map_err(|_| AtomicError::Corrupt)?;
    latent_state::namespace::catalog::NamespaceCatalog::validate_row(
        &row,
        &namespace.encode().map_err(|_| AtomicError::Corrupt)?,
    )
    .map_err(|_| AtomicError::Corrupt)?;
    if namespace.version.incarnation != incarnation {
        return Err(AtomicError::Corrupt);
    }
    ledger.check(&namespace)?;
    Ok(TenantCensusContribution::Usage {
        tenant: TenantId(namespace.tenant.0),
        usage: TenantUsage {
            result_rows: ledger.results,
            result_bytes: ledger.result_bytes,
            effect_rows: ledger.effects,
            effect_bytes: ledger.effect_bytes,
            payload_bytes: ledger.payload_bytes,
            recovery_bytes: ledger.recovery_reserved,
            ..TenantUsage::default()
        },
    })
}
fn storage_error(error: AtomicError) -> StoreError {
    match error {
        AtomicError::UnsupportedFormat => StoreError::UnsupportedFormat,
        AtomicError::Limit => StoreError::Capacity,
        _ => StoreError::Corrupt,
    }
}
