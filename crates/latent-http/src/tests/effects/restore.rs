//! Essential older-backup case with the real common envelope, protected ext4
//! offline ports, fixed dispatcher and maintained put-once TLS endpoint.
use super::*;
use dispatcher::Store;
use latent_effects::{dispatch_store::DispatchCatalog, runtime::DispatcherOwner};
use latent_state::{
    embedded::StoreError,
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    recovery::{
        offline::{
            OfflineRecoveryError, OfflineRecoverySource, OfflineRestoreRequest, RecoveryCodecs,
            RecoveryReviewRequest, SnapshotFile,
        },
        restore::RestoreRequest,
        resume::{NamespaceRecoveryView, NamespaceResumeRequest},
        RecoveryStatus,
    },
    store_io::StoreIoKind,
};
use std::{fs, os::unix::fs::PermissionsExt};

mod codecs;
mod command;
mod physical;
mod review;

const BODY: &[u8] = b"synthetic committed effect\0";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn older_protected_backup_keeps_applied_http_effect_paused_until_explicit_review_and_resume()
{
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let proxy = proxy::Proxy::new(&endpoint, proxy::Loss::AfterApply).await;
    let fixture = Fixture::new(proxy.port, proxy.root_certificate.clone(), 2000).await;
    let mut original = Store::new().await;
    let workload = command::commit(&original, &fixture).await;
    let codecs = codecs::Codecs::new(&fixture, &workload);
    assert_eq!(endpoint.attempts(), (0, 0));
    physical::assert_workload(&original, &workload, false).await;
    assert_eq!(
        original.record(&workload.authority).await.disposition(),
        Disposition::Pending
    );

    // Retire actual normal owners before one protected logical engine snapshot.
    command::quiesce(&original).await;
    original.close().await;
    let source = physical::offline(&original.config, codecs.clone(), false).await;
    let backup_root = physical::root();
    let input = SnapshotFile {
        root: backup_root.path().into(),
        file_name: "private-backup".into(),
    };
    let snapshot = physical::backup(&source, &codecs, &input).await;
    review::resume(&source, "original-after-backup").await;
    physical::close_offline(&source).await;
    drop(source);

    // Work AFTER the backup is really sent, durably applied, then reconciled
    // from the lost response by the existing qualified bounded TLS lookup.
    physical::reopen(&mut original).await;
    let first = physical::deliver(&original, &fixture, &workload.authority).await;
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    endpoint.assert_applied_id(&workload.authority.link().effect, BODY, &first, 10_100);
    command::quiesce(&original).await;
    original.close().await;
    let source = physical::offline(&original.config, codecs.clone(), false).await;
    let destination = physical::root();
    let restored = physical::restore(&source, &codecs, input, &snapshot, destination.path()).await;
    assert_eq!(
        restored.guard.status(),
        RecoveryStatus::ReconciliationRequired
    );
    physical::close_offline(&source).await;
    drop(source);

    let config = ProtectedStoreConfig::bounded_linux(destination.path().into());
    let review_source = physical::offline(&config, codecs.clone(), true).await;
    let observed =
        review::reconcile(&review_source, &codecs, &restored.guard, &endpoint, &first).await;
    assert_eq!(observed.namespace.version.incarnation, 7);
    assert_eq!(observed.history.epochs.recovery, 2);
    physical::close_offline(&review_source).await;
    drop(review_source);

    // Global reconciliation alone leaves the actual namespace/history paused.
    // Install the real dispatcher unpaused: its durable candidate selection
    // must still refuse the pending effect, with no guest or private pause flag.
    let mut recovered = physical::open_restored(destination).await;
    physical::assert_workload(&recovered, &workload, true).await;
    physical::assert_dispatch_refused(&recovered, &fixture, &workload, &endpoint).await;
    recovered.close().await;
    let review_source = physical::offline(&recovered.config, codecs.clone(), true).await;
    review::resume_with_current_authority(&review_source, &fixture, &endpoint).await;
    physical::close_offline(&review_source).await;
    drop(review_source);
    physical::reopen(&mut recovered).await;
    physical::assert_workload(&recovered, &workload, true).await;
    let replay = physical::deliver(&recovered, &fixture, &workload.authority).await;
    assert_eq!(replay, first);
    assert_eq!(endpoint.attempts(), (2, 1));
    assert_eq!(endpoint.counter(), 1);
    endpoint.assert_applied_id(&workload.authority.link().effect, BODY, &replay, 10_100);
    recovered.finish().await;
    original.finish().await;
    fixture.finish().await;
    proxy.finish().await;
    endpoint.finish(1).await;
}
