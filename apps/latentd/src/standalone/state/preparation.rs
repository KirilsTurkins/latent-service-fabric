//! Exact tenant setup happens after private checkpoint admission, before the
//! singleton dispatcher or transaction manager receives the store.
use latent_core::PlatformError;
use latent_state::{embedded::FencedStoreError, store_identity::StoreIdentity, tenant};

use super::{super::effects::ProtectedStatePreparation, validation};
use crate::config::state::StateSettings;

pub(super) fn tenant_installation(
    settings: &StateSettings,
) -> Result<Option<ProtectedStatePreparation>, PlatformError> {
    let quotas = validation::quotas(settings);
    if quotas.is_empty() {
        return if settings.operations.is_empty() {
            Ok(None)
        } else {
            Err(super::unavailable())
        };
    }
    let identity = settings.store_identity.clone();
    // Fixed upper bound from the installed tenant producer, including the
    // guard, all 32 quota originals, prepared mutations and result comparisons.
    let retained_bytes = tenant::GUARD_BYTES * 3
        + tenant::RECORD_BYTES * tenant::MAXIMUM_TENANTS * 4
        + latent_state::store_identity::MAXIMUM_ENCODED_BYTES * 4;
    ProtectedStatePreparation::new(retained_bytes as u64, move |engine, original| {
        validation::live(original)?;
        let view = engine.snapshot()?;
        if StoreIdentity::inspect(&view)?.as_ref() != Some(&identity) {
            return Err(latent_state::embedded::StoreError::Corrupt);
        }
        let prepared = tenant::prepare_install(&view, &quotas)?;
        drop(view);
        prepared
            .publish(engine, || validation::live(original))
            .map_err(|error| match error {
                FencedStoreError::Store(error) | FencedStoreError::Fence(error) => error,
            })?;
        let view = engine.snapshot()?;
        tenant::require_installation(&view, &quotas)?;
        drop(view);
        validation::live(original)
    })
    .map(Some)
}
