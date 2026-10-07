//! Settings-bound accounting over the original linked startup view.
use crate::config::state::StateSettings;
use latent_core::PlatformError;
use latent_effects::dispatch_store::DispatchCatalog;
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    tenant::{self, TenantCensus, TenantCensusContribution, TenantQuota},
};
use std::time::{Duration, Instant};

// Original linked pages/point reads plus 32 bounded quota originals/counters,
// the <=12 KiB guard, 32 <=256-byte tenant IDs and the previous <=1024-byte key.
// Fresh preparation's <=167936-byte plan is dropped before any full-walk page.
pub(in crate::standalone::state) const STARTUP_VALIDATION_BYTES: u64 = 4 * 1024 * 1024 + 128 * 1024;

/// Captured before protected initialization; all native reads remain on its
/// original accepted worker. These declarations confer no application authority.
pub(in crate::standalone::state) struct StartupValidation {
    quotas: Vec<TenantQuota>,
    deadline: Instant,
}

pub(in crate::standalone::state) fn startup(
    settings: &StateSettings,
    deadline: Instant,
) -> Result<StartupValidation, PlatformError> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero()
        || remaining > Duration::from_mins(1)
        || settings.operations.len() > 128
        || settings.tenant_quotas.len() > tenant::MAXIMUM_TENANTS
        || (settings.tenant_quotas.is_empty() && !settings.operations.is_empty())
        || settings.operations.iter().any(|operation| {
            !settings
                .tenant_quotas
                .iter()
                .any(|quota| quota.tenant == operation.tenant)
        })
    {
        return Err(super::super::denied());
    }
    if !settings.tenant_quotas.is_empty() {
        tenant::configuration_digest(&settings.tenant_quotas)
            .map_err(|_| super::super::denied())?;
    }
    Ok(StartupValidation {
        quotas: settings.tenant_quotas.clone(),
        deadline,
    })
}

impl StartupValidation {
    pub(in crate::standalone::state) fn validate(&self, view: &ReadView) -> Result<(), StoreError> {
        self.checkpoint()?;
        let installed = view
            .get_bounded(&tenant::guard_key(), tenant::GUARD_BYTES)?
            .is_some();
        if !installed && self.quotas.is_empty() {
            return self.bootstrap(view);
        }
        if installed {
            self.installed(view)?;
        } else {
            self.fresh(view)?;
        }
        // Preserve the original dispatcher/control cross-link validation and
        // bounded prefix walks. There is only one full accounting census.
        DispatchCatalog::validate_view(view)?;
        self.checkpoint()
    }
    fn installed(&self, view: &ReadView) -> Result<(), StoreError> {
        if self.quotas.is_empty() {
            return Err(StoreError::UnsupportedFormat);
        }
        let mut census = TenantCensus::capture(
            view,
            &self.quotas,
            tenant::INSTALLED_GLOBAL_ALLOWANCE,
            self.deadline,
        )?;
        latent_commit::atomic::validate_view_observed(view, super::foreign, |view, key, bytes| {
            census.observe(key, bytes, contribution(view, key, bytes)?)
        })?;
        census.finish().map(|_| ())
    }
    fn fresh(&self, view: &ReadView) -> Result<(), StoreError> {
        let mut rows = 0u64;
        let mut logical_bytes = 0u64;
        if !self.quotas.is_empty() {
            // This finite preparation reads only original guard/quota keys and
            // family presence. It never performs another whole-store scan or
            // publishes a plan. Reserve the actual pending global guard charge.
            let prepared = tenant::prepare_install(view, &self.quotas)?;
            for row in &prepared.batch().mutations {
                if row.key == tenant::guard_key() {
                    rows += 1;
                    logical_bytes = tenant::row_charge(
                        &row.key,
                        row.value.as_deref().ok_or(StoreError::Corrupt)?,
                    )?;
                }
            }
        }
        latent_commit::atomic::validate_view_observed(view, super::foreign, |view, key, bytes| {
            self.checkpoint()?;
            if !matches!(
                contribution(view, key, bytes)?,
                TenantCensusContribution::Global
            ) {
                // An absent installation is the explicit empty bootstrap,
                // never approval to upgrade existing legacy business rows.
                return Err(StoreError::UnsupportedFormat);
            }
            rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
            logical_bytes = logical_bytes
                .checked_add(tenant::row_charge(key, bytes)?)
                .ok_or(StoreError::Capacity)?;
            if rows > tenant::INSTALLED_GLOBAL_ALLOWANCE.rows
                || logical_bytes > tenant::INSTALLED_GLOBAL_ALLOWANCE.bytes
            {
                return Err(StoreError::Capacity);
            }
            Ok(())
        })
    }
    fn bootstrap(&self, view: &ReadView) -> Result<(), StoreError> {
        // The explicit no-operation profile uses the original generic linked
        // registry. Fixed presence checks refuse business/accounting ownership
        // without a second full scan or an inferred installation declaration.
        super::super::validate_view(view)?;
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
        ] {
            self.checkpoint()?;
            if view.contains_prefix(family, &[])? {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        for prefix in [
            tenant::QUOTA_PREFIX,
            latent_state::reservation::QUOTA_PREFIX,
            latent_state::reservation::KEY_PREFIX,
            b"state-usage-v1\0",
            latent_state::recovery::resume::RECEIPT_PREFIX,
            latent_state::recovery::migration::PROGRESS_PREFIX,
        ] {
            self.checkpoint()?;
            if view.contains_prefix(Family::Maintenance, prefix)? {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        self.checkpoint()
    }
    fn checkpoint(&self) -> Result<(), StoreError> {
        if Instant::now() >= self.deadline {
            Err(StoreError::Unavailable)
        } else {
            Ok(())
        }
    }
}

fn contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    match latent_commit::atomic::tenant_census_contribution(view, key, bytes) {
        Err(StoreError::UnsupportedFormat) => {}
        result => return result,
    }
    match tenant::census_contribution(view, key, bytes) {
        Err(StoreError::UnsupportedFormat) => {}
        result => return result,
    }
    match DispatchCatalog::tenant_census_contribution(view, key, bytes) {
        Err(StoreError::UnsupportedFormat) => {}
        result => return result,
    }
    latent_wire::phase4::StateManagementBackend::tenant_metadata_contribution(view, key, bytes)
}

#[cfg(test)]
pub(super) mod tests;
