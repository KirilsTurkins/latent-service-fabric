//! The actual protected state owner and fixed dispatcher, not a second outbox.
use super::*;
use latent_effects::{
    dispatch_store::{effect_payload_key, effect_row_key, initial_due_mutation, DispatchCatalog},
    runtime::{DispatcherConfig, DispatcherOwner},
};
use latent_state::{
    embedded::{AtomicBatch, RowMutation},
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    store_io::StoreIoKind,
};
use std::{fs, os::unix::fs::PermissionsExt};

struct Store {
    _root: tempfile::TempDir,
    config: ProtectedStoreConfig,
    owner: Arc<ProtectedStoreOwner>,
}

impl Store {
    async fn new() -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, std::path::PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().into());
        config.create_if_missing = true;
        let owner = ProtectedStoreOwner::start_validated_view(
            config.clone(),
            0,
            DispatchCatalog::validate_view,
        )
        .unwrap()
        .await
        .unwrap();
        Self {
            _root: root,
            config,
            owner: Arc::new(owner),
        }
    }

    async fn seed(
        &self,
        authority: &DurableEffectAuthority,
        payload: &PayloadRecord,
        record: &EffectRecord,
    ) {
        self.owner
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![
                    namespace_mutation(authority.scope()),
                    RowMutation {
                        key: effect_row_key(payload.effect()).unwrap(),
                        value: Some(record.encode().unwrap()),
                    },
                    RowMutation {
                        key: effect_payload_key(payload.effect()).unwrap(),
                        value: Some(payload.encode().unwrap()),
                    },
                    initial_due_mutation(authority).unwrap(),
                ],
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    async fn record(&self, authority: &DurableEffectAuthority) -> EffectRecord {
        let key = effect_row_key(&authority.link().effect).unwrap();
        self.owner
            .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
                Ok(EffectRecord::decode(&store.snapshot()?.get(&key)?.unwrap()).unwrap())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }

    async fn finish(self) {
        self.close().await;
    }

    async fn close(&self) {
        let deadline = Instant::now() + Duration::from_secs(5);
        let report = self
            .owner
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean);
        assert!(report.snapshot.physically_retired());
        self.owner.reap_retired_threads().unwrap();
    }

    async fn reopen(&mut self) {
        self.close().await;
        self.owner = Arc::new(
            ProtectedStoreOwner::start_validated_view(
                self.config.clone(),
                0,
                DispatchCatalog::validate_view,
            )
            .unwrap()
            .await
            .unwrap(),
        );
    }
}

fn config(paused: bool) -> DispatcherConfig {
    DispatcherConfig {
        workers: 1,
        queued_jobs: 1,
        accepted_jobs: 2,
        per_tenant_jobs: 1,
        start_paused: paused,
        poll_interval: Duration::from_millis(2),
        ..DispatcherConfig::default()
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_dispatcher_writes_send_marker_then_recovers_actual_lost_tls_response() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let proxy = proxy::Proxy::new(&endpoint, proxy::Loss::AfterApply).await;
    let fixture = Fixture::new(proxy.port, proxy.root_certificate.clone(), 2000).await;
    let store = Store::new().await;
    let (authority, payload, record) = fixture.retained(50, b"one atomic committed intent");
    let mut dispatcher = DispatcherOwner::start(
        config(true),
        store.owner.clone(),
        fixture.authority.clone(),
        vec![Arc::new(fixture.adapter.clone())],
        fixture.clock.clone(),
        None,
    )
    .await
    .unwrap();
    // Description and adapter installation alone create no network attempt.
    assert_eq!(endpoint.attempts(), (0, 0));
    store.seed(&authority, &payload, &record).await;
    assert_eq!(endpoint.attempts(), (0, 0));
    dispatcher.resume().unwrap();
    watched(async {
        loop {
            let record = store.record(&authority).await;
            if record.disposition() == Disposition::ProviderAcknowledged {
                assert!(record.send_started());
                assert_eq!(record.attempts(), 1);
                assert_eq!(record.history_sequence(), 1);
                assert_eq!(record.latest().unwrap().reason, "qualified-remote-receipt");
                assert_eq!(
                    record
                        .latest()
                        .unwrap()
                        .provider_receipt
                        .as_ref()
                        .unwrap()
                        .len(),
                    64
                );
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    assert!(
        dispatcher
            .shutdown(Instant::now() + Duration::from_secs(5))
            .await
            .unwrap()
            .clean
    );
    drop(dispatcher);
    store.finish().await;
    fixture.finish().await;
    proxy.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn crash_before_send_marker_reopens_as_known_nonexecution_without_remote_mutation() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    let mut store = Store::new().await;
    let (authority, payload, record) =
        fixture.retained(51, b"committed but process lost before send");
    store.seed(&authority, &payload, &record).await;
    store
        .owner
        .with_store(StoreIoKind::Write, 8 * 1024 * 1024, |store| {
            let time = EffectTime {
                unix_millis: 100,
                continuity_proven: true,
            };
            let epoch = DispatchCatalog::begin_exclusive_epoch(store, time, None).unwrap();
            let due = DispatchCatalog::due_page(&store.snapshot()?, 100, None, 1, 4096)?
                .rows
                .remove(0);
            let claim = DispatchCatalog::claim(store, epoch, &due, time).unwrap();
            assert_eq!(claim.attempt.attempt(), 1);
            // Intentionally no adapter first poll and no durable begin_send marker.
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(endpoint.attempts(), (0, 0));
    store.reopen().await;
    let mut dispatcher = DispatcherOwner::start(
        config(true),
        store.owner.clone(),
        fixture.authority.clone(),
        vec![Arc::new(fixture.adapter.clone())],
        fixture.clock.clone(),
        Some((1, 100)),
    )
    .await
    .unwrap();
    let recovered = store.record(&authority).await;
    assert_eq!(recovered.disposition(), Disposition::KnownFailed);
    assert!(!recovered.send_started());
    assert_eq!(
        recovered.latest().unwrap().reason,
        "retired-process-before-send-boundary"
    );
    assert_eq!(endpoint.attempts(), (0, 0));
    assert!(
        dispatcher
            .shutdown(Instant::now() + Duration::from_secs(5))
            .await
            .unwrap()
            .clean
    );
    drop(dispatcher);
    store.finish().await;
    fixture.finish().await;
    endpoint.finish(0).await;
}

fn namespace_mutation(scope: &latent_effects::authority::EffectScope) -> RowMutation {
    use latent_state::namespace::{namespace_record_key, NamespaceQuota, NamespaceRecord};
    let tenant = latent_core::TenantId(scope.tenant.clone());
    let id = latent_core::StateNamespaceId(scope.namespace.clone());
    let mut record = NamespaceRecord::create(
        tenant.clone(),
        id.clone(),
        format!("sha256:{}", "1".repeat(64)),
        NamespaceQuota::default(),
    )
    .unwrap();
    record.version.incarnation = scope.incarnation;
    RowMutation {
        key: latent_state::embedded::RowKey {
            family: latent_state::embedded::Family::Namespace,
            key: namespace_record_key(&tenant, &id).unwrap(),
        },
        value: Some(record.encode().unwrap()),
    }
}
