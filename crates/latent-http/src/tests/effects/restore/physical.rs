use super::*;
use latent_commit::atomic::{self, AtomicError};
use latent_state::{
    namespace::compatibility::RetainedKind,
    recovery::{offline::OfflineRestoreReceipt, snapshot::SnapshotReceipt},
    session::{version::ViewIdentity, SessionLimits, StateError, StateSession},
};
use std::path::Path;

pub(super) fn root() -> tempfile::TempDir {
    let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
        .map_or_else(std::env::temp_dir, std::path::PathBuf::from);
    let root = tempfile::tempdir_in(base).unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    root
}

pub(super) async fn offline(
    config: &ProtectedStoreConfig,
    codecs: Arc<codecs::Codecs>,
    review: bool,
) -> OfflineRecoverySource {
    let mut config = config.clone();
    config.create_if_missing = false;
    let startup = if review {
        OfflineRecoverySource::start_review(config, "a".into(), codecs)
    } else {
        OfflineRecoverySource::start(config, "a".into(), codecs)
    };
    watched(startup.unwrap()).await.unwrap()
}

pub(super) async fn close_offline(source: &OfflineRecoverySource) {
    let deadline = Instant::now() + Duration::from_secs(5);
    let report = source
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    source.reap_retired_threads().unwrap();
}

pub(super) async fn reopen(store: &mut Store) {
    store.close().await;
    store.owner = Arc::new(
        watched(
            ProtectedStoreOwner::start_validated_view(
                store.config.clone(),
                4 * 1024 * 1024,
                codecs::Codecs::validate,
            )
            .unwrap(),
        )
        .await
        .unwrap(),
    );
}

pub(super) async fn open_restored(root: tempfile::TempDir) -> Store {
    let config = ProtectedStoreConfig::bounded_linux(root.path().into());
    let owner = watched(
        ProtectedStoreOwner::start_validated_view(
            config.clone(),
            4 * 1024 * 1024,
            codecs::Codecs::validate,
        )
        .unwrap(),
    )
    .await
    .unwrap();
    Store {
        _root: root,
        config,
        owner: Arc::new(owner),
    }
}

pub(super) async fn backup(
    source: &OfflineRecoverySource,
    codecs: &codecs::Codecs,
    input: &SnapshotFile,
) -> SnapshotReceipt {
    let mut missing = codecs.metadata();
    missing
        .required_artifacts
        .retain(|artifact| artifact != &codecs::contract_artifact());
    let refused = source
        .backup_to(input.clone(), missing, deadline())
        .unwrap()
        .await;
    assert_eq!(
        refused.err(),
        Some(OfflineRecoveryError::Review(StoreError::Corrupt))
    );
    assert!(!input.root.join(&input.file_name).exists());
    let snapshot = source
        .backup_to(input.clone(), codecs.metadata(), deadline())
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        fs::metadata(input.root.join(&input.file_name))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    let inventory = snapshot.manifest.inventory().unwrap();
    for kind in [
        RetainedKind::CommandFingerprint,
        RetainedKind::CommandAttempt,
        RetainedKind::SuccessResult,
        RetainedKind::InboxIdentity,
        RetainedKind::EffectEnvelope,
        RetainedKind::EffectPayload,
        RetainedKind::AdapterProfile,
    ] {
        assert!(inventory
            .entries()
            .iter()
            .any(|(format, count)| format.kind == kind && count.rows > 0));
    }
    assert!(inventory.total().unresolved > 0);
    snapshot
}

pub(super) async fn restore(
    source: &OfflineRecoverySource,
    codecs: &codecs::Codecs,
    input: SnapshotFile,
    snapshot: &SnapshotReceipt,
    destination: &Path,
) -> OfflineRestoreReceipt {
    let mut request = OfflineRestoreRequest {
        input,
        destination: ProtectedStoreConfig::bounded_linux(destination.into()),
        review: RestoreRequest {
            operation_id: "restore-older-history".into(),
            operator_id: "operator".into(),
            snapshot_digest: snapshot.snapshot_digest,
            runtime_digest: codecs.runtime_digest(),
            window_acknowledgement: [1; 32],
        },
    };
    let inspected = source
        .inspect_restore(request.clone(), deadline())
        .unwrap()
        .await
        .unwrap();
    assert!(!destination.join("transaction-state.redb").exists());
    // A different runtime cannot decode this snapshot or stage a root.
    let mut incompatible = request.clone();
    incompatible.review.runtime_digest = [1; 32];
    assert_eq!(
        source
            .restore_to(incompatible, deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Input(StoreError::UnsupportedFormat))
    );
    assert!(!destination.join("transaction-state.redb").exists());
    request.review.window_acknowledgement = inspected.window.digest().unwrap();
    source
        .restore_to(request, deadline())
        .unwrap()
        .await
        .unwrap()
}

pub(super) async fn deliver(
    store: &Store,
    fixture: &Fixture,
    authority: &DurableEffectAuthority,
) -> String {
    let checkpoint = store
        .owner
        .with_store(StoreIoKind::Read, 1024 * 1024, |store| {
            Ok(DispatchCatalog::has_owner_history(&store.snapshot()?)?)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .then_some((1, 100));
    let mut dispatcher = DispatcherOwner::start(
        dispatcher::config(false),
        store.owner.clone(),
        fixture.authority.clone(),
        vec![Arc::new(fixture.adapter.clone())],
        fixture.clock.clone(),
        checkpoint,
    )
    .await
    .unwrap();
    let receipt = watched(async {
        loop {
            let record = store.record(authority).await;
            if record.disposition() == Disposition::ProviderAcknowledged {
                assert_eq!(record.attempts(), 1);
                assert!(record.send_started());
                break record.latest().unwrap().provider_receipt.clone().unwrap();
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    let retired = dispatcher.shutdown(deadline()).await.unwrap();
    assert!(retired.clean && retired.physically_retired && retired.scheduling_owner_retired);
    receipt
}

pub(super) async fn assert_dispatch_refused(
    store: &Store,
    fixture: &Fixture,
    workload: &command::Workload,
    endpoint: &Endpoint,
) {
    let mut dispatcher = DispatcherOwner::start(
        dispatcher::config(false),
        store.owner.clone(),
        fixture.authority.clone(),
        vec![Arc::new(fixture.adapter.clone())],
        fixture.clock.clone(),
        None,
    )
    .await
    .unwrap();
    let snapshot = dispatcher.refresh_counts().await.unwrap();
    assert_eq!(snapshot.durable.pending, 1);
    assert_eq!(snapshot.claims, 0);
    assert!(!snapshot.paused);
    store
        .owner
        .with_store(StoreIoKind::Read, 1024 * 1024, |store| {
            let view = store.snapshot()?;
            assert!(latent_state::recovery::require_ready(&view).is_ok());
            assert_eq!(
                latent_state::recovery::require_namespace_ready(
                    &view,
                    &command::scope().tenant,
                    &command::scope().namespace,
                    7
                ),
                Err(StoreError::Unavailable)
            );
            assert!(DispatchCatalog::due_page(&view, 100, None, 1, 4096)?
                .rows
                .is_empty());
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        store.record(&workload.authority).await.disposition(),
        Disposition::Pending
    );
    let retired = dispatcher.shutdown(deadline()).await.unwrap();
    assert!(retired.clean && retired.physically_retired && retired.scheduling_owner_retired);
    assert_eq!(retired.snapshot.claims, 0);
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
}

pub(super) async fn assert_workload(store: &Store, workload: &command::Workload, restored: bool) {
    let key = workload.key.clone();
    let command_bytes = workload.command.clone();
    let result_bytes = workload.result.clone();
    let original_view = workload.original_view.clone();
    store
        .owner
        .with_store(StoreIoKind::Read, 8 * 1024 * 1024, move |store| {
            let view = store.snapshot()?;
            codecs::Codecs::validate(&view)?;
            // Historical caller/read policy in the backup cannot grant current read.
            assert_eq!(
                atomic::inspect(&view, &key, command::time(), |_, _| Err(
                    AtomicError::PermissionDenied
                ))
                .err(),
                Some(AtomicError::PermissionDenied)
            );
            let (command, result) =
                atomic::inspect(&view, &key, command::time(), |_, _| Ok(())).unwrap();
            assert_eq!(command.encode().unwrap(), command_bytes);
            assert_eq!(result.unwrap().encode().unwrap(), result_bytes);
            let observed = NamespaceRecoveryView::capture(
                &view,
                &command::scope().tenant,
                &command::scope().namespace,
            )?;
            if restored {
                assert_eq!(observed.history.epochs.recovery, 2);
                let identity =
                    ViewIdentity::from_token(&observed.scope(), &observed.view_token()?).unwrap();
                assert_eq!(
                    identity.require_minimum(&observed.scope(), &original_view),
                    Err(StateError::RecoveryRequired)
                );
            } else {
                let mut session = StateSession::open(
                    &view,
                    command::scope(),
                    SessionLimits::default(),
                    |_, _| Ok(()),
                )
                .unwrap();
                assert_eq!(
                    session
                        .get(&view, b"aggregate/count", |_, _| Ok(()))
                        .unwrap()
                        .unwrap()
                        .value
                        .bytes,
                    7_u64.to_le_bytes()
                );
            }
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

pub(super) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
