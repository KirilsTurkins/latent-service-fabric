//! Lower codecs retain ownership of their actual row/tenant association.
use super::{row_charge, TenantCensusContribution, TenantRecord, TenantUsage};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::catalog::NamespaceCatalog,
};
use latent_core::TenantId;

pub fn census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    if *key == super::guard_key() {
        super::validate_row(view, key, bytes)?;
        return Ok(TenantCensusContribution::Global);
    }
    if *key == crate::recovery::guard_key() {
        crate::recovery::RecoveryGuard::validate_row(key, bytes)?;
        return Ok(TenantCensusContribution::Global);
    }
    if *key == crate::store_identity::StoreIdentity::row_key() {
        crate::store_identity::StoreIdentity::validate_row(key, bytes)?;
        return Ok(TenantCensusContribution::Global);
    }
    if key.family == Family::Maintenance && key.key.starts_with(super::QUOTA_PREFIX) {
        super::validate_row(view, key, bytes)?;
        return metadata(TenantRecord::decode(bytes)?.quota.tenant, key, bytes);
    }
    if key.family == Family::Namespace {
        let tenant = NamespaceCatalog::tenant_for_row(key, bytes).map_err(|error| match error {
            crate::namespace::NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
            _ => StoreError::Corrupt,
        })?;
        return metadata(tenant, key, bytes);
    }
    if key.family == Family::Maintenance
        && key
            .key
            .starts_with(crate::recovery::migration::PROGRESS_PREFIX)
    {
        return crate::recovery::migration::census_contribution(view, key, bytes);
    }
    // Unsupported recovery producers remain outside this closed profile. A
    // prefix or historical label cannot supply a tenant or fabricate counters.
    let tenant = crate::session::tenant_for_row(view, key, bytes)?;
    if key.family == Family::State {
        return Ok(TenantCensusContribution::Usage {
            usage: crate::session::tenant_row_usage(&tenant, key, bytes)?,
            tenant,
        });
    }
    metadata(tenant, key, bytes)
}
fn metadata(
    tenant: TenantId,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    Ok(TenantCensusContribution::Usage {
        tenant,
        usage: TenantUsage {
            metadata_rows: 1,
            metadata_bytes: row_charge(key, bytes)?,
            ..TenantUsage::default()
        },
    })
}
