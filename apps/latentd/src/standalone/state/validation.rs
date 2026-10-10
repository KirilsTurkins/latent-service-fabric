//! Coherent closed startup validation on the original fixed storage worker.
//! Configured quotas are exact installation constraints, never inferred grants.
use latent_core::{native_capacity::NativeReservation, TenantId};
use latent_effects::dispatch_store::DispatchCatalog;
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    recovery::RecoveryGuard,
    store_identity::StoreIdentity,
    tenant::{self, TenantCensus, TenantCensusContribution, TenantQuota, TenantUsage},
};

use crate::config::state::StateSettings;

const FAMILIES: [Family; 10] = [
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
];

pub(super) fn quotas(settings: &StateSettings) -> Vec<TenantQuota> {
    settings
        .tenant_quotas
        .iter()
        .map(|input| TenantQuota {
            tenant: TenantId(input.tenant.clone()),
            limits: TenantUsage {
                state_keys: input.limits.state_keys,
                state_bytes: input.limits.state_bytes,
                tombstone_keys: input.limits.tombstone_keys,
                tombstone_bytes: input.limits.tombstone_bytes,
                result_rows: input.limits.result_rows,
                result_bytes: input.limits.result_bytes,
                effect_rows: input.limits.effect_rows,
                effect_bytes: input.limits.effect_bytes,
                payload_bytes: input.limits.payload_bytes,
                recovery_bytes: input.limits.recovery_bytes,
                metadata_rows: input.limits.metadata_rows,
                metadata_bytes: input.limits.metadata_bytes,
            },
        })
        .collect()
}

/// Called before any store consumer is published. The physical initializer
/// retains the original prepaid validator buffers through this callback.
/// Empty/identity-only validation supplies no Fresh witness: only the actual
/// successful identity initialization can permit external checkpoint creation.
pub(super) fn validate(
    view: &ReadView,
    identity: &StoreIdentity,
    quotas: &[TenantQuota],
    original: &NativeReservation,
) -> Result<(), StoreError> {
    live(original)?;
    if !quotas.is_empty() {
        tenant::configuration_digest(quotas)?;
    }
    let current = StoreIdentity::inspect(view)?;
    if current.as_ref().is_some_and(|current| current != identity) {
        return Err(StoreError::Corrupt);
    }
    if only_initial_identity(view, original)? {
        // An existing matching identity still cannot recreate a lost external
        // checkpoint. That later decision consumes the affine kernel witness.
        return live(original);
    }
    if current.is_none() {
        return Err(StoreError::UnsupportedFormat);
    }
    if quotas.is_empty() {
        return validate_global_bootstrap(view, original);
    }
    let mut census = TenantCensus::capture(
        view,
        quotas,
        tenant::INSTALLED_GLOBAL_ALLOWANCE,
        original.original_deadline(),
    )?;
    latent_commit::atomic::validate_view_observed(view, foreign_row, |view, key, bytes| {
        live(original)?;
        census.observe(key, bytes, contribution(view, key, bytes)?)
    })?;
    census.finish()?;
    live(original)?;
    DispatchCatalog::validate_view(view)?;
    live(original)
}

fn validate_global_bootstrap(
    view: &ReadView,
    original: &NativeReservation,
) -> Result<(), StoreError> {
    // Empty target bootstrap never installs a tenant profile. It cannot omit
    // an already installed manifest or accept any tenant-owned business data.
    if view
        .get_bounded(&tenant::guard_key(), tenant::GUARD_BYTES)?
        .is_some()
    {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut rows = 0_u64;
    let mut bytes = 0_u64;
    latent_commit::atomic::validate_view_observed(view, foreign_row, |view, key, value| {
        live(original)?;
        if !matches!(
            contribution(view, key, value)?,
            TenantCensusContribution::Global
        ) {
            return Err(StoreError::UnsupportedFormat);
        }
        rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
        bytes = bytes
            .checked_add(tenant::row_charge(key, value)?)
            .ok_or(StoreError::Capacity)?;
        if rows > tenant::INSTALLED_GLOBAL_ALLOWANCE.rows
            || bytes > tenant::INSTALLED_GLOBAL_ALLOWANCE.bytes
        {
            return Err(StoreError::Capacity);
        }
        Ok(())
    })?;
    live(original)?;
    DispatchCatalog::validate_view(view)?;
    live(original)
}

fn only_initial_identity(
    view: &ReadView,
    original: &NativeReservation,
) -> Result<bool, StoreError> {
    for family in FAMILIES {
        live(original)?;
        let page = view.scan_after(family, b"", None, 2, 2 * 1024 * 1024)?;
        if page.resume.is_some()
            || page
                .rows
                .iter()
                .any(|(key, _)| *key != StoreIdentity::row_key())
        {
            return Ok(false);
        }
    }
    Ok(true)
}

type Validator = fn(&ReadView, &RowKey, &[u8]) -> Result<(), StoreError>;

fn foreign_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    // Only UnsupportedFormat delegates. A malformed owned row cannot be
    // rescued by another codec, a prefix label, or permissive opaque storage.
    let validators: [Validator; 6] = [
        tenant::validate_row,
        latent_state::session::validate_row,
        namespace_row,
        |_, key, bytes| RecoveryGuard::validate_row(key, bytes),
        |_, key, bytes| StoreIdentity::validate_row(key, bytes),
        |_, key, bytes| latent_effects::dispatch_store::validate_row(key, bytes),
    ];
    for validator in validators {
        match validator(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
    }
    Err(StoreError::UnsupportedFormat)
}

fn namespace_row(_: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    NamespaceCatalog::validate_row(key, bytes).map_err(|error| match error {
        NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Corrupt,
    })
}

fn contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    type Contributor =
        fn(&ReadView, &RowKey, &[u8]) -> Result<TenantCensusContribution, StoreError>;
    let contributors: [Contributor; 3] = [
        latent_commit::atomic::tenant_census_contribution,
        DispatchCatalog::tenant_census_contribution,
        tenant::census_contribution,
    ];
    for contribution in contributors {
        match contribution(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
    }
    Err(StoreError::UnsupportedFormat)
}

pub(super) fn live(original: &NativeReservation) -> Result<(), StoreError> {
    original
        .with_live(|| ())
        .map_err(|_| StoreError::Unavailable)
}

#[cfg(test)]
mod tests;
