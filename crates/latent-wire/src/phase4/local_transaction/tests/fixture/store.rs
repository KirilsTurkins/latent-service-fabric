//! The actual family owners validate one coherent protected startup view.
use latent_effects::dispatch_store::DispatchCatalog;
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    protected_store::{
        ProtectedStoreConfig, ProtectedStoreError, ProtectedStoreOwner, ProtectedStoreStartup,
    },
    recovery::RecoveryGuard,
    store_identity::StoreIdentity,
};

pub(super) fn start(
    config: ProtectedStoreConfig,
) -> Result<ProtectedStoreStartup, ProtectedStoreError> {
    // The installed callback retains no owned decoder inputs. Page/point reads
    // use the same finite protected initializer and codec bounds as production.
    ProtectedStoreOwner::start_validated_view(config, 0, |view| {
        latent_commit::atomic::validate_view(view, foreign)?;
        DispatchCatalog::validate_view(view)
    })
}

type Validator = fn(&ReadView, &RowKey, &[u8]) -> Result<(), StoreError>;

fn foreign(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    let validators: [Validator; 6] = [
        latent_state::tenant::validate_row,
        latent_state::session::validate_row,
        namespace,
        |_, key, bytes| RecoveryGuard::validate_row(key, bytes),
        |_, key, bytes| StoreIdentity::validate_row(key, bytes),
        |_, key, bytes| latent_effects::dispatch_store::validate_row(key, bytes),
    ];
    for validate in validators {
        match validate(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
    }
    Err(StoreError::UnsupportedFormat)
}

fn namespace(_: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    NamespaceCatalog::validate_row(key, bytes).map_err(|error| match error {
        NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Corrupt,
    })
}
