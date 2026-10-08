use super::*;
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, RowMutation},
    namespace::history::{history_key, HistoryEpochs, HistoryStatus, NamespaceHistory},
    recovery::RecoveryGuard,
};

impl Fixture {
    /// Controlled offline history replacement; it grants no execution authority.
    pub async fn change_history(&self, epochs: HistoryEpochs) {
        self.store
            .with_store(StoreIoKind::Write, 8192, move |store| {
                let view = store.snapshot()?;
                let namespace = NamespaceCatalog::read_in(
                    &view,
                    &latent_core::TenantId("a".into()),
                    &latent_core::StateNamespaceId("orders".into()),
                )
                .unwrap()
                .unwrap();
                let (mut history, previous) =
                    NamespaceHistory::capture(&view, namespace.record()).unwrap();
                history.epochs = epochs;
                history.status = HistoryStatus::Ready;
                let key =
                    history_key(&history.tenant, &history.namespace, history.incarnation).unwrap();
                drop(view);
                store.apply(AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: key.clone(),
                        value: previous,
                    }],
                    mutations: vec![RowMutation {
                        key,
                        value: Some(history.encode().unwrap()),
                    }],
                })
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    pub async fn restore_paused(&self) {
        self.store
            .with_store(StoreIoKind::Write, 8192, |store| {
                let original = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
                store.apply(original.prepare_staging().unwrap())?;
                store.apply(original.prepare_completed().unwrap())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }
}
