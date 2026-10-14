//! Actual protected views and original signed/native owners; no Java or full restore qualification.
use super::super::super::{catalog::LINKED, request::NativeRecoveryRequest};
use super::Fixture;
use latent_core::{native_capacity::NativeReservation, SystemActivationClock, TenantId};
use latent_effects::{authority::EffectTime, dispatch_store::DispatchCatalog};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, Family, RowKey, RowMutation, StoreError},
    namespace::{
        compatibility::{RetainedFormat, RetainedKind},
        history::{history_key, NamespaceHistory},
        namespace_record_key, NamespaceRecord,
    },
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartupMemory},
    store_identity::StoreIdentity,
    store_io::StoreIoKind,
    tenant::{TenantDelta, TenantQuota, TenantUsage},
};
use serde_json::json;
use std::{os::unix::fs::PermissionsExt, sync::Arc};

struct Target {
    store: Arc<ProtectedStoreOwner>,
    original: Arc<NativeReservation>,
    root: tempfile::TempDir,
}

struct TargetConfiguration {
    config: ProtectedStoreConfig,
    root: tempfile::TempDir,
}

impl TargetConfiguration {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().join("state"));
        config.create_if_missing = true;
        config.engine.cache_bytes = 1024 * 1024;
        Self { config, root }
    }
}

fn quota() -> TenantQuota {
    TenantQuota {
        tenant: TenantId("tests".into()),
        limits: TenantUsage {
            metadata_rows: 128,
            metadata_bytes: 2 * 1024 * 1024,
            ..TenantUsage::default()
        },
    }
}

fn seed(
    engine: &EmbeddedStore,
    namespace: &NamespaceRecord,
    quota: TenantQuota,
    time: EffectTime,
) -> Result<(), StoreError> {
    DispatchCatalog::begin_exclusive_epoch(engine, time, None)
        .map_err(|_| StoreError::Unavailable)?;
    let view = engine.snapshot()?;
    let installation = latent_state::tenant::prepare_install(&view, &[quota])?;
    drop(view);
    installation
        .publish(engine, || Ok::<_, ()>(()))
        .map_err(|_| StoreError::Unavailable)?;
    let history = NamespaceHistory::initial(namespace);
    let mutations = vec![
        RowMutation {
            key: RowKey {
                family: Family::Namespace,
                key: namespace_record_key(&namespace.tenant, &namespace.id)
                    .map_err(|_| StoreError::Invalid)?,
            },
            value: Some(namespace.encode().map_err(|_| StoreError::Invalid)?),
        },
        RowMutation {
            key: history_key(&history.tenant, &history.namespace, history.incarnation)
                .map_err(|_| StoreError::Invalid)?,
            value: Some(history.encode().map_err(|_| StoreError::Invalid)?),
        },
    ];
    let mut delta = TenantDelta::default();
    for row in &mutations {
        delta.added.metadata_rows += 1;
        delta.added.metadata_bytes +=
            latent_state::tenant::row_charge(&row.key, row.value.as_ref().unwrap())?;
    }
    let mut batch = AtomicBatch {
        expectations: mutations
            .iter()
            .map(|row| ExpectedRow {
                key: row.key.clone(),
                value: None,
            })
            .collect(),
        mutations,
    };
    let view = engine.snapshot()?;
    latent_state::tenant::prepare_update(&view, &namespace.tenant, delta)?.append_to(&mut batch)?;
    drop(view);
    engine.apply(batch)?;
    Ok(())
}

async fn configured(targets: &[&ProtectedStoreConfig]) -> Fixture {
    let mut fixture = Fixture::for_restore_targets(targets).await;
    let input = json!({"publication":fixture.sources[0].id.as_str(),"request":{
        "action":"restore","file":{"root":"/original","name":"snapshot"},
        "destinationRoot":"/distinct-target","destinationCheckpointRoot":"/distinct-checkpoint",
        "operationId":"restore","snapshotDigest":format!("sha256:{}", "1".repeat(64)),
        "manifestDigest":format!("sha256:{}", "2".repeat(64)),
        "windowAcknowledgement":format!("sha256:{}", "3".repeat(64)),
        "destinationStoreIdentity":"explicit-target"}});
    let decoded = NativeRecoveryRequest::decode(&serde_json::to_vec(&input).unwrap()).unwrap();
    let codecs = Arc::get_mut(&mut fixture.codecs).unwrap();
    codecs.action = decoded.request;
    codecs.quotas = vec![quota()];
    codecs.catalog.formats = vec![RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: LINKED.into(),
    }];
    let namespace = codecs.namespace.clone();
    let time = codecs.time().unwrap();
    fixture
        .store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            8 * 1024 * 1024,
            fixture.codecs.original.clone(),
            move |engine| seed(engine, &namespace, quota(), time),
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    fixture
}

impl Target {
    async fn new(
        fixture: &Fixture,
        configured: TargetConfiguration,
        identity: StoreIdentity,
    ) -> Self {
        let TargetConfiguration { config, root } = configured;
        let original = fixture.codecs.original.clone();
        assert!(original.is_from_owner(&fixture.native));
        std::fs::create_dir(&config.root).unwrap();
        std::fs::set_permissions(&config.root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let store = Arc::new(
            ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
                config,
                identity,
                ProtectedStoreStartupMemory::new(&fixture.native, original.clone()).unwrap(),
                0,
                |_| Ok(()),
                Arc::new(SystemActivationClock),
            )
            .unwrap()
            .await
            .unwrap(),
        );
        assert!(store.uses_native_capacity(&fixture.native));
        let namespace = fixture.codecs.namespace.clone();
        let time = fixture.codecs.time().unwrap();
        store
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                8 * 1024 * 1024,
                original.clone(),
                move |engine| seed(engine, &namespace, quota(), time),
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        Self {
            store,
            original,
            root,
        }
    }

    async fn finish(self) {
        self.store.close();
        let until = self.original.original_deadline();
        let retired = self
            .store
            .drain_async(until, tokio::time::sleep_until(until.into()))
            .unwrap()
            .await;
        assert!(retired.clean && retired.snapshot.physically_retired());
        assert!(self.store.reap_retired_threads().unwrap() > 0);
        drop(self.store);
        drop(self.original);
        drop(self.root);
    }
}

async fn inspect(
    fixture: &Fixture,
    store: &ProtectedStoreOwner,
    original: &Arc<NativeReservation>,
    restored: bool,
) -> Result<(), StoreError> {
    inspect_with_native_close(fixture, store, original, restored, false).await
}

async fn inspect_with_native_close(
    fixture: &Fixture,
    store: &ProtectedStoreOwner,
    original: &Arc<NativeReservation>,
    restored: bool,
    close_native: bool,
) -> Result<(), StoreError> {
    let codecs = fixture.codecs.clone();
    let native = fixture.native.clone();
    store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
            original.clone(),
            move |engine| {
                let view = engine.snapshot()?;
                if close_native {
                    native.close();
                }
                Ok(if restored {
                    codecs.restored_closure(&view)
                } else {
                    codecs.closure(&view)
                }
                .map(|_| ()))
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

#[tokio::test]
async fn actual_explicit_target_view_is_validated_without_changing_original_source_identity() {
    let prepared = TargetConfiguration::new();
    let fixture = configured(&[&prepared.config]).await;
    let source = fixture.codecs.identity.clone();
    let target = fixture
        .codecs
        .action
        .restore_destination_identity(&source)
        .unwrap();
    assert_ne!(target, source);
    let target = Target::new(&fixture, prepared, target).await;
    let source_result = inspect(&fixture, &fixture.store, &fixture.codecs.original, false).await;
    let target_result = inspect(&fixture, &target.store, &target.original, true).await;
    let source_override = inspect(&fixture, &target.store, &target.original, false).await;
    target.finish().await;
    assert_eq!(fixture.codecs.identity, source);
    fixture.finish().await;
    assert_eq!(source_result, Ok(()));
    assert_eq!(target_result, Ok(()));
    assert_eq!(source_override, Err(StoreError::Corrupt));
}

#[tokio::test]
async fn actual_foreign_or_source_identity_cannot_replace_the_explicit_target() {
    let source = TargetConfiguration::new();
    let foreign = TargetConfiguration::new();
    let fixture = configured(&[&source.config, &foreign.config]).await;
    for (configured, identity) in [
        (source, fixture.codecs.identity.clone()),
        (
            foreign,
            StoreIdentity::new("foreign-target".into()).unwrap(),
        ),
    ] {
        let target = Target::new(&fixture, configured, identity).await;
        let rejected = inspect(&fixture, &target.store, &target.original, true).await;
        target.finish().await;
        assert_eq!(rejected, Err(StoreError::Corrupt));
    }
    assert_eq!(
        inspect(&fixture, &fixture.store, &fixture.codecs.original, false).await,
        Ok(())
    );
    fixture.finish().await;
}

#[tokio::test]
async fn actual_target_read_preserves_original_publication_clock_and_native_refusals() {
    for refusal in 0..3 {
        let prepared = TargetConfiguration::new();
        let fixture = configured(&[&prepared.config]).await;
        let identity = fixture
            .codecs
            .action
            .restore_destination_identity(&fixture.codecs.identity)
            .unwrap();
        let target = Target::new(&fixture, prepared, identity).await;
        assert_eq!(
            inspect(&fixture, &target.store, &target.original, true).await,
            Ok(())
        );
        match refusal {
            0 => fixture.revoke_publication(false),
            1 => fixture.clock.regress(),
            _ => {}
        }
        let rejected = inspect_with_native_close(
            &fixture,
            &target.store,
            &target.original,
            true,
            refusal == 2,
        )
        .await;
        target.finish().await;
        fixture.finish().await;
        assert!(rejected.is_err());
    }
}
