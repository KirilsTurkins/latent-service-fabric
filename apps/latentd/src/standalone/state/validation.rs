use latent_state::embedded::{ReadView, RowKey, StoreError};
use latent_state::namespace::{catalog::NamespaceCatalog, NamespaceError};

/// Every family and linked command/result/effect is checked in the SAME view.
pub(crate) fn validate_view(view: &ReadView) -> Result<(), StoreError> {
    latent_commit::atomic::validate_view(view, foreign)?;
    latent_effects::dispatch_store::DispatchCatalog::validate_view(view)
}

fn foreign(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    let row = latent_state::session::validate_row(view, key, bytes);
    if row != Err(StoreError::UnsupportedFormat) {
        return row;
    }
    let row = latent_state::recovery::resume::NamespaceResumeReceipt::validate_row(key, bytes);
    if row != Err(StoreError::UnsupportedFormat) {
        return row;
    }
    let row =
        latent_state::recovery::migration::AggregateMigrationProgress::validate_row(key, bytes);
    if row != Err(StoreError::UnsupportedFormat) {
        return row;
    }
    let row = NamespaceCatalog::validate_row(key, bytes).map_err(namespace_error);
    if row != Err(StoreError::UnsupportedFormat) {
        return row;
    }
    let row = latent_state::recovery::RecoveryGuard::validate_row(key, bytes);
    if row != Err(StoreError::UnsupportedFormat) {
        return row;
    }
    latent_effects::dispatch_store::validate_row(key, bytes)
}
fn namespace_error(error: NamespaceError) -> StoreError {
    match error {
        NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
        NamespaceError::Corrupt => StoreError::Corrupt,
        _ => StoreError::Invalid,
    }
}
