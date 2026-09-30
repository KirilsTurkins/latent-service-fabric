use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, ReadView, RowKey, RowMutation, StoreError,
};

use crate::authority::{AuthorityError, EffectTime};
use crate::dispatch::{AttemptIdentity, Disposition, EffectRecord};
use crate::payload::PayloadRecord;

use super::{
    effect_payload_key, effect_row_key, storage_error, DispatchEpoch, DispatchStoreError,
    DueRecord, HistoryRecord, OwnerRecord,
};

pub(super) struct Loaded {
    key: RowKey,
    bytes: Vec<u8>,
    pub record: EffectRecord,
}

impl Loaded {
    pub fn read(view: &ReadView, effect: &str) -> Result<Self, DispatchStoreError> {
        let key = effect_row_key(effect)?;
        let bytes = view.get(&key)?.ok_or(AuthorityError::Stale)?;
        crate::dispatch_store::validate_row(&key, &bytes)?;
        let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
        Ok(Self { key, bytes, record })
    }
}

pub(super) struct WriteSet {
    batch: AtomicBatch,
}

impl WriteSet {
    pub fn new(
        view: &ReadView,
        epoch: DispatchEpoch,
        time: EffectTime,
    ) -> Result<Self, DispatchStoreError> {
        let key = OwnerRecord::key();
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        let mut owner = OwnerRecord::decode(&bytes)?;
        if owner.epoch != epoch.0 {
            return Err(DispatchStoreError::StaleEpoch);
        }
        owner.observe(time)?;
        Ok(Self {
            batch: AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: key.clone(),
                    value: Some(bytes),
                }],
                mutations: vec![RowMutation {
                    key,
                    value: Some(owner.encode()?),
                }],
            },
        })
    }

    pub fn expect(&mut self, key: RowKey, value: Option<Vec<u8>>) {
        self.batch.expectations.push(ExpectedRow { key, value });
    }

    pub fn expect_due(
        &mut self,
        view: &ReadView,
        due: &DueRecord,
        loaded: &Loaded,
    ) -> Result<(), DispatchStoreError> {
        let key = due.key()?;
        let bytes = view.get(&key)?.ok_or(AuthorityError::Stale)?;
        if DueRecord::decode(&key, &bytes)? != *due {
            return Err(AuthorityError::Stale.into());
        }
        let authority = loaded.record.authority().map_err(storage_error)?;
        if due.incarnation != authority.scope().incarnation
            || due.claim_generation != loaded.record.claim_generation()
            || due.due_millis
                != if loaded.record.disposition() == Disposition::Pending {
                    authority.committed_at_millis()
                } else {
                    loaded.record.retry_at_millis()
                }
        {
            return Err(StoreError::Corrupt.into());
        }
        self.expect(key.clone(), Some(bytes));
        self.batch.mutations.push(RowMutation { key, value: None });
        Ok(())
    }

    pub fn replace(&mut self, loaded: Loaded) -> Result<(), StoreError> {
        let value = Some(loaded.record.encode().map_err(storage_error)?);
        self.expect(loaded.key.clone(), Some(loaded.bytes));
        self.batch.mutations.push(RowMutation {
            key: loaded.key,
            value,
        });
        Ok(())
    }

    pub fn history(
        &mut self,
        record: &EffectRecord,
        attempt: Option<AttemptIdentity>,
    ) -> Result<(), StoreError> {
        let history = HistoryRecord {
            sequence: record.history_sequence(),
            effect: record
                .authority()
                .map_err(storage_error)?
                .link()
                .effect
                .clone(),
            attempt,
            receipt: record.latest().ok_or(StoreError::Corrupt)?.clone(),
        };
        let key = history.key()?;
        self.expect(key.clone(), None);
        self.batch.mutations.push(RowMutation {
            key,
            value: Some(history.encode()?),
        });
        Ok(())
    }

    pub fn schedule(&mut self, record: &EffectRecord) -> Result<(), StoreError> {
        let authority = record.authority().map_err(storage_error)?;
        let due = DueRecord {
            due_millis: record.retry_at_millis(),
            effect: authority.link().effect.clone(),
            incarnation: authority.scope().incarnation,
            claim_generation: record.claim_generation(),
        };
        let key = due.key()?;
        self.expect(key.clone(), None);
        self.batch.mutations.push(RowMutation {
            key,
            value: Some(due.encode()?),
        });
        Ok(())
    }

    pub fn apply(self, store: &EmbeddedStore) -> Result<(), DispatchStoreError> {
        store.apply(self.batch).map_err(Into::into)
    }
}

pub(super) fn recover_one(
    store: &EmbeddedStore,
    epoch: DispatchEpoch,
    key: &RowKey,
    old_process_retired: bool,
    time: EffectTime,
) -> Result<(), DispatchStoreError> {
    let view = store.snapshot()?;
    let effect = crate::dispatch_store::effect_from_key(key, crate::dispatch_store::EFFECT_PREFIX)?;
    let mut loaded = Loaded::read(&view, &effect)?;
    let authority = loaded.record.authority().map_err(storage_error)?;
    // Unresolved payload linkage survives ordinary command response expiry.
    if !loaded.record.disposition().terminal() {
        let payload_key = effect_payload_key(&effect)?;
        let bytes = view.get(&payload_key)?.ok_or(StoreError::Corrupt)?;
        PayloadRecord::decode(&bytes)
            .map_err(storage_error)?
            .verify(&authority)
            .map_err(storage_error)?;
        if matches!(
            loaded.record.disposition(),
            Disposition::Pending | Disposition::RetryScheduled
        ) {
            let due = DueRecord {
                due_millis: if loaded.record.disposition() == Disposition::Pending {
                    authority.committed_at_millis()
                } else {
                    loaded.record.retry_at_millis()
                },
                effect,
                incarnation: authority.scope().incarnation,
                claim_generation: loaded.record.claim_generation(),
            };
            let bytes = view.get(&due.key()?)?.ok_or(StoreError::Corrupt)?;
            if DueRecord::decode(&due.key()?, &bytes)? != due {
                return Err(StoreError::Corrupt.into());
            }
        }
    }
    if loaded.record.disposition() != Disposition::Dispatching {
        return Ok(());
    }
    let mut writer = WriteSet::new(&view, epoch, time)?;
    loaded
        .record
        .recover_interrupted(epoch.0, old_process_retired, time)?;
    writer.history(&loaded.record, None)?;
    writer.replace(loaded)?;
    drop(view);
    writer.apply(store)
}
