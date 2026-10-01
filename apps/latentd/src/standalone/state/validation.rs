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

#[cfg(test)]
mod tests {
    use super::*;
    use latent_effects::{authority::EffectTime, dispatch_store::DispatchCatalog};
    use latent_state::embedded::{AtomicBatch, EmbeddedStore, Family, RowMutation, StoreLimits};
    use std::{fs::OpenOptions, path::Path};

    fn open(path: &Path, create: bool) -> EmbeddedStore {
        EmbeddedStore::open_file(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(create)
                .open(path)
                .unwrap(),
            StoreLimits {
                cache_bytes: 1024 * 1024,
                ..StoreLimits::default()
            },
        )
        .unwrap()
    }

    #[test]
    fn linked_registry_reopens_real_dispatch_owner_and_rejects_malformed_migration() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("linked.redb");
        let store = open(&path, true);
        validate_view(&store.snapshot().unwrap()).unwrap();
        DispatchCatalog::begin_exclusive_epoch(
            &store,
            EffectTime {
                unix_millis: 1_000,
                continuity_proven: true,
            },
            None,
        )
        .unwrap();
        let owner = RowKey {
            family: Family::Maintenance,
            key: b"dispatch-owner-v1\0".to_vec(),
        };
        let original = store.snapshot().unwrap().get(&owner).unwrap().unwrap();
        validate_view(&store.snapshot().unwrap()).unwrap();
        drop(store);

        let reopened = open(&path, false);
        validate_view(&reopened.snapshot().unwrap()).unwrap();
        assert_eq!(
            reopened.snapshot().unwrap().get(&owner).unwrap(),
            Some(original)
        );
        for key in [
            b"foreign-maintenance-v1\0".as_slice(),
            latent_state::recovery::migration::PROGRESS_PREFIX,
        ] {
            let view = reopened.snapshot().unwrap();
            let row = RowKey {
                family: Family::Maintenance,
                key: key.to_vec(),
            };
            let expected = if key == latent_state::recovery::migration::PROGRESS_PREFIX {
                StoreError::Corrupt
            } else {
                StoreError::UnsupportedFormat
            };
            assert_eq!(foreign(&view, &row, b"{}"), Err(expected));
        }
        reopened
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: RowKey {
                        family: Family::Maintenance,
                        key: latent_state::recovery::migration::PROGRESS_PREFIX.to_vec(),
                    },
                    value: Some(b"{}".to_vec()),
                }],
            })
            .unwrap();
        assert_eq!(
            validate_view(&reopened.snapshot().unwrap()),
            Err(StoreError::Corrupt)
        );
    }
}
