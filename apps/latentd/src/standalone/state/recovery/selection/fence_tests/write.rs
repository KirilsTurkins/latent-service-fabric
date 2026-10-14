use super::*;
use latent_state::{
    embedded::{
        AtomicBatch, ExpectedRow, Family, FencedStoreError, RowKey, RowMutation, StoreError,
    },
    store_io::StoreIoKind,
};
use std::sync::atomic::AtomicBool;

pub(in super::super) struct Outcome {
    pub result: Result<(), StoreError>,
    pub action_entered: bool,
    pub metadata_changed: bool,
}

impl Fixture {
    pub async fn write(&self, purpose: &'static str, close_native: bool) -> Outcome {
        let codecs = self.codecs.clone();
        let native = self.native.clone();
        let entered = Arc::new(AtomicBool::new(false));
        let action = entered.clone();
        let memory = codecs
            .original
            .reserve_buffer(NativeBufferClass::Work, 8 * 1024 * 1024)
            .unwrap();
        let keeper = codecs.clone() as Arc<dyn std::any::Any + Send + Sync>;
        let outcome = self
            .store
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                8 * 1024 * 1024,
                keeper,
                move |engine| {
                    let _memory = memory;
                    let key = RowKey {
                        family: Family::Maintenance,
                        key: b"test-native-recovery-fence\0".to_vec(),
                    };
                    let before = engine.snapshot()?.get(&key)?;
                    assert!(before.is_none());
                    let batch = AtomicBatch {
                        expectations: vec![ExpectedRow {
                            key: key.clone(),
                            value: before.clone(),
                        }],
                        mutations: vec![RowMutation {
                            key: key.clone(),
                            value: Some(b"accepted".to_vec()),
                        }],
                    };
                    if close_native {
                        native.close();
                    }
                    let result = engine
                        .apply_fenced(batch, || {
                            codecs.fence(purpose, || {
                                assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
                                codecs
                                    .original
                                    .with_live(|| ())
                                    .map_err(|_| StoreError::SnapshotExpired)?;
                                action.store(true, Ordering::SeqCst);
                                Ok(())
                            })
                        })
                        .map_err(|error| match error {
                            FencedStoreError::Store(e) | FencedStoreError::Fence(e) => e,
                        });
                    let after = engine.snapshot()?.get(&key)?;
                    // A logical refusal remains nested output from the actual native job;
                    // it must neither poison storage nor disclose an accepted mutation.
                    Ok((result, before != after))
                },
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        assert_eq!(self.native.snapshot().unwrap().recovery.slots, 1);
        Outcome {
            result: outcome.0,
            action_entered: entered.load(Ordering::SeqCst),
            metadata_changed: outcome.1,
        }
    }
}
