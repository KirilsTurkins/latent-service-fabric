use latent_state::embedded::{ReadView, StoreError};

use super::{DispatchCatalog, OwnerRecord};

impl DispatchCatalog {
    /// Descriptive durable owner/time floor from this coherent view. A caller
    /// cannot turn this tuple into a live epoch, grant or restore approval.
    pub fn checkpoint(view: &ReadView) -> Result<Option<(u64, u64)>, StoreError> {
        view.get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()
            .map(|owner| owner.map(|owner| (owner.epoch, owner.clock_floor)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::authority::EffectTime;
    use latent_state::embedded::{AtomicBatch, EmbeddedStore, RowMutation, StoreLimits};

    fn store() -> (EmbeddedStore, tempfile::TempDir) {
        let directory = tempfile::tempdir().unwrap();
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(directory.path().join("checkpoint.redb"))
            .unwrap();
        (
            EmbeddedStore::open_file(file, StoreLimits::default()).unwrap(),
            directory,
        )
    }

    #[test]
    fn checkpoint_reports_actual_coherent_owner_floors_without_advancing_them() {
        let (store, _directory) = store();
        let old = store.snapshot().unwrap();
        assert_eq!(DispatchCatalog::checkpoint(&old).unwrap(), None);
        let epoch = DispatchCatalog::begin_exclusive_epoch(
            &store,
            EffectTime {
                unix_millis: 1000,
                continuity_proven: true,
            },
            None,
        )
        .unwrap();
        assert_eq!(DispatchCatalog::checkpoint(&old).unwrap(), None);
        let current = store.snapshot().unwrap();
        assert_eq!(
            DispatchCatalog::checkpoint(&current).unwrap(),
            Some((epoch.generation(), 1000))
        );
        assert_eq!(
            DispatchCatalog::checkpoint(&current).unwrap(),
            Some((epoch.generation(), 1000))
        );
    }

    #[test]
    fn checkpoint_never_treats_malformed_or_unknown_owner_rows_as_empty() {
        let (store, _directory) = store();
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: OwnerRecord::key(),
                    value: Some(b"LDO\0\x01".to_vec()),
                }],
            })
            .unwrap();
        assert_eq!(
            DispatchCatalog::checkpoint(&store.snapshot().unwrap()),
            Err(StoreError::Corrupt)
        );
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: OwnerRecord::key(),
                    value: Some(b"LDO\0\x02".to_vec()),
                }],
            })
            .unwrap();
        assert_eq!(
            DispatchCatalog::checkpoint(&store.snapshot().unwrap()),
            Err(StoreError::UnsupportedFormat)
        );
    }
}
