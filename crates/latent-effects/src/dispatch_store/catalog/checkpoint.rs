use latent_state::embedded::{ReadView, StoreError};

use super::{DispatchCatalog, OwnerRecord};

impl DispatchCatalog {
    /// Same exclusive offline owner advances only its observed clock floor.
    /// This plan is descriptive; the current operator/native writer must still
    /// accept it at the physical fence and seal the external checkpoint.
    pub fn prepare_offline_clock(
        view: &ReadView,
        time: crate::authority::EffectTime,
    ) -> Result<latent_state::embedded::AtomicBatch, StoreError> {
        use latent_state::embedded::{AtomicBatch, ExpectedRow, RowMutation};
        let key = OwnerRecord::key();
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        let mut owner = OwnerRecord::decode(&bytes)?;
        owner.observe(time).map_err(|_| StoreError::Unavailable)?;
        Ok(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(bytes),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(owner.encode()?),
            }],
        })
    }

    /// Fresh paused restoration replaces the archived local owner with a
    /// strictly later fence from the actual current source/checkpoint. Retained
    /// effect/attempt bytes remain unchanged and cannot inherit a send grant.
    pub fn prepare_restored_owner(
        staged: &ReadView,
        current: &ReadView,
        time: crate::authority::EffectTime,
    ) -> Result<latent_state::embedded::AtomicBatch, StoreError> {
        use latent_state::embedded::{AtomicBatch, ExpectedRow, RowMutation};
        let source = Self::checkpoint(current)?.ok_or(StoreError::Corrupt)?;
        let key = OwnerRecord::key();
        if staged.get(&key)?.is_some() || !time.continuity_proven || time.unix_millis < source.1 {
            return Err(StoreError::Conflict);
        }
        let owner = OwnerRecord {
            epoch: source.0.checked_add(1).ok_or(StoreError::Capacity)?,
            clock_floor: time.unix_millis,
        };
        Ok(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: None,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(owner.encode()?),
            }],
        })
    }
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
