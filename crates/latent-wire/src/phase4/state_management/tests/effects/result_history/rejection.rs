use super::*;
use latent_commit::atomic::{result_row_key, Identity};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, RowMutation, StoreError},
    namespace::history::{history_key, NamespaceHistory},
    store_io::StoreIoKind,
};

pub(super) async fn transition_while_held(fixture: &HistoryFixture) {
    let namespaces = Arc::clone(&fixture.effect.fixture.backend.0.services.namespaces);
    fixture
        .effect
        .fixture
        .store
        .with_store(StoreIoKind::RecoveryWrite, 65_536, move |engine| {
            let view = engine.snapshot()?;
            let before = NamespaceCatalog::read_in(
                &view,
                &TenantId("a".into()),
                &StateNamespaceId("orders".into()),
            )
            .map_err(|_| StoreError::Corrupt)?
            .unwrap();
            let mut after = before.record().clone();
            after.state_schema = format!("sha256:{}", "5".repeat(64));
            after.version.generation = after.version.generation.checked_add(1).unwrap();
            let (mut history, old_history) = NamespaceHistory::capture(&view, before.record())?;
            history.state_schema = after.state_schema.clone();
            history.epochs.schema = history.epochs.schema.checked_add(1).unwrap();
            let history_key =
                history_key(&after.tenant, &after.id, after.version.incarnation).unwrap();
            let expected = before.expectation();
            let batch = AtomicBatch {
                expectations: vec![
                    expected.clone(),
                    ExpectedRow {
                        key: history_key.clone(),
                        value: old_history,
                    },
                ],
                mutations: vec![
                    RowMutation {
                        key: expected.key,
                        value: Some(after.encode().unwrap()),
                    },
                    RowMutation {
                        key: history_key,
                        value: Some(history.encode().unwrap()),
                    },
                ],
            };
            let mut completion = None;
            engine
                .apply_fenced(batch, || {
                    completion = Some(
                        namespaces
                            .lifecycle()
                            .begin_transition(&before, &after, false)
                            .map_err(|_| StoreError::Unavailable)?,
                    );
                    Ok::<_, StoreError>(())
                })
                .map_err(|_| StoreError::Unavailable)?;
            let current = NamespaceCatalog::read_in(&engine.snapshot()?, &after.tenant, &after.id)
                .map_err(|_| StoreError::Corrupt)?
                .unwrap();
            completion
                .unwrap()
                .resolve(&current)
                .map_err(|_| StoreError::Unavailable)?;
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

pub(super) async fn damage_result(fixture: &HistoryFixture) {
    let id = Identity::parse_hex(&fixture.original.command_id).unwrap();
    let attempt = fixture.original.attempt_id.parse().unwrap();
    fixture
        .effect
        .fixture
        .store
        .with_store(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES as u64,
            move |engine| {
                let view = engine.snapshot()?;
                let key = result_row_key(id, attempt);
                let original = view.get(&key)?.unwrap();
                let mut damaged = original.clone();
                *damaged.last_mut().unwrap() ^= 1;
                // Isolated corruption negative only. This is no migration, recovery or
                // usable store; the original tenant guard remains byte-exact.
                let guard = latent_state::tenant::guard_key();
                let old_guard = view.get(&guard)?;
                engine.apply(AtomicBatch {
                    expectations: vec![
                        ExpectedRow {
                            key: key.clone(),
                            value: Some(original),
                        },
                        ExpectedRow {
                            key: guard.clone(),
                            value: old_guard.clone(),
                        },
                    ],
                    mutations: vec![
                        RowMutation {
                            key,
                            value: Some(damaged),
                        },
                        RowMutation {
                            key: guard,
                            value: old_guard,
                        },
                    ],
                })
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

pub(super) async fn finish_damaged(mut fixture: HistoryFixture) {
    drop(fixture.backend);
    let effect = &mut fixture.effect;
    let report = effect.dispatcher.shutdown(deadline()).await.unwrap();
    assert!(report.physically_retired);
    effect.fixture.store.close();
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        effect
            .fixture
            .store
            .drain_async(deadline(), std::future::pending())
            .unwrap(),
    )
    .await
    .unwrap();
    assert!(report.snapshot.physically_retired());
    let (audit, worker) = effect.fixture.audit.as_mut().unwrap();
    audit.close();
    assert!(worker.join_until(deadline()).unwrap());
    assert_eq!(
        effect.fixture.admission.budget.outstanding_reservations(),
        0
    );
    assert!(effect
        .fixture
        .admission
        .native
        .snapshot()
        .unwrap()
        .physically_retired());
}
