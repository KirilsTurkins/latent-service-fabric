use super::*;
use latent_core::SystemActivationClock;
use latent_state::{embedded::StoreError, store_identity::StoreIdentity, store_io::StoreIoKind};
use std::{
    os::unix::fs::PermissionsExt,
    sync::{Condvar, Mutex},
};

mod trace;

thread_local! {
    static EXIT_GATE: std::cell::RefCell<Option<ExitGate>> = const { std::cell::RefCell::new(None) };
}

struct ExitGate {
    entered: std::sync::mpsc::Sender<()>,
    gate: Arc<Gate>,
}

impl Drop for ExitGate {
    fn drop(&mut self) {
        let _ = self.entered.send(());
        let held = self.gate.release.lock().unwrap();
        let _ = self.gate.wake.wait_timeout_while(
            held,
            std::time::Duration::from_secs(10),
            |released| !*released,
        );
    }
}

struct ReleaseExit(Arc<Gate>);

impl Drop for ReleaseExit {
    fn drop(&mut self) {
        *self.0.release.lock().unwrap() = true;
        self.0.wake.notify_all();
    }
}

#[tokio::test]
async fn actual_worker_exit_must_be_joined_before_clean_retirement() {
    let (_root, settings, mut bootstrap) = fixture();
    let store = bootstrap.open_store(&settings).await.unwrap();
    let gate = Arc::new(Gate {
        release: Mutex::new(false),
        wake: Condvar::new(),
    });
    let release = ReleaseExit(Arc::clone(&gate));
    let (entered, observed) = std::sync::mpsc::channel();
    store
        .with_store_retaining(StoreIoKind::Read, 0, bootstrap.original(), move |_| {
            EXIT_GATE.with(|slot| *slot.borrow_mut() = Some(ExitGate { entered, gate }));
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    store.close();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    let retired = store
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(retired.snapshot.physically_retired());
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while observed.try_recv().is_err() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let cutoff = std::time::Instant::now() + std::time::Duration::from_millis(20);
    assert!(join_retired_workers(&store, cutoff)
        .await
        .unwrap()
        .is_none());
    assert!(store.pending_thread_joins().unwrap() > 0);
    drop(release);
    assert!(join_retired_workers(&store, deadline)
        .await
        .unwrap()
        .is_some());
    assert_eq!(store.pending_thread_joins().unwrap(), 0);
}

fn fixture() -> (tempfile::TempDir, StateSettings, StateBootstrap) {
    let root = tempfile::tempdir().unwrap();
    let settings = super::super::bootstrap::tests::settings(root.path());
    std::fs::create_dir(&settings.store.root).unwrap();
    std::fs::set_permissions(&settings.store.root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
    let bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    (root, settings, bootstrap)
}

#[tokio::test]
async fn actual_startup_returns_only_the_same_prepaid_store_and_original_initializer_identity() {
    let (_root, settings, mut bootstrap) = fixture();
    let native = bootstrap.native.clone();
    let store = bootstrap.open_store(&settings).await.unwrap();
    assert!(store.uses_native_capacity(&native));
    assert!(bootstrap.open_store(&settings).await.is_err());
    let expected = settings.store_identity.clone();
    let keeper = bootstrap.original();
    let observed = store
        .with_store_retaining(StoreIoKind::RecoveryRead, 4096, keeper, |engine| {
            let view = engine.snapshot()?;
            StoreIdentity::inspect(&view)?.ok_or(StoreError::Corrupt)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(observed, expected);
    let fresh = store
        .take_initialization_witness()
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(fresh.identity(), &expected);
    assert!(store
        .take_initialization_witness()
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .is_none());
    drop(fresh);
    store.close();
    let report = store
        .drain_async(
            bootstrap.deadline,
            tokio::time::sleep_until(bootstrap.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean);
    assert!(report.snapshot.physically_retired());
    store.reap_retired_threads().unwrap();
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(bootstrap);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn startup_transfers_the_same_ordinary_blob_owner_without_enabling_durable_mode() {
    use latent_blobs::local::{LocalBlobLimits, LocalBlobStore};
    let (root, settings, mut bootstrap) = fixture();
    let blob_root = root.path().join("blobs");
    std::fs::create_dir(&blob_root).unwrap();
    std::fs::set_permissions(&blob_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let owner = LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()).unwrap();
    let pointer = Arc::as_ptr(&owner);
    let provider = crate::config::ProviderIdentity {
        id: "local".into(),
        tenant: "tenant".into(),
        service: "blob".into(),
        epoch: 1,
    };
    let owner = bootstrap
        .open_store_with_local_payloads(&settings, owner, provider, blob_root.clone())
        .await
        .unwrap();
    assert_eq!(Arc::as_ptr(&owner), pointer);
    assert!(!blob_root.join("DURABLE.json").exists());
    let store = Arc::clone(bootstrap.opened_store.as_ref().unwrap());
    drop(owner);
    store.close();
    let report = store
        .drain_async(
            bootstrap.deadline,
            tokio::time::sleep_until(bootstrap.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    store.reap_retired_threads().unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelled_initializer_keeps_the_transferred_blob_lock_until_worker_retirement() {
    use latent_blobs::local::{LocalBlobError, LocalBlobLimits, LocalBlobStore};
    let (root, settings, mut bootstrap) = fixture();
    let blob_root = root.path().join("blocked-blobs");
    std::fs::create_dir(&blob_root).unwrap();
    std::fs::set_permissions(&blob_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let owner = LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()).unwrap();
    let native = bootstrap.native.clone();
    let gate = Arc::new((Mutex::new(false), Condvar::new()));
    let blocked = Arc::clone(&gate);
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (returned, receiver) = std::sync::mpsc::sync_channel(1);
    let provider = crate::config::ProviderIdentity {
        id: "local".into(),
        tenant: "tenant".into(),
        service: "blob".into(),
        epoch: 1,
    };
    let task = tokio::spawn(async move {
        bootstrap
            .open_store_inner(
                &settings,
                Some(Box::new(move || {
                    entered.send(()).unwrap();
                    let lock = blocked.0.lock().unwrap();
                    let (lock, timed) = blocked
                        .1
                        .wait_timeout_while(lock, std::time::Duration::from_secs(10), |release| {
                            !*release
                        })
                        .unwrap();
                    assert!(*lock && !timed.timed_out());
                })),
                false,
                StartupPayload::Local {
                    owner,
                    provider,
                    returned,
                },
            )
            .await
    });
    tokio::time::timeout(std::time::Duration::from_secs(5), observed)
        .await
        .unwrap()
        .unwrap();
    task.abort();
    let Err(cancelled) = task.await else {
        panic!("cancelled initializer returned a result")
    };
    assert!(cancelled.is_cancelled());
    drop(receiver);
    assert!(native.snapshot().unwrap().quarantined);
    assert!(matches!(
        LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()),
        Err(LocalBlobError::Busy)
    ));
    *gate.0.lock().unwrap() = true;
    gate.1.notify_all();
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if let Ok(owner) =
                LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default())
            {
                drop(owner);
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        while !native
            .snapshot()
            .is_ok_and(latent_core::native_capacity::NativeCapacitySnapshot::physically_retired)
        {
            tokio::time::sleep(std::time::Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn startup_rebinds_the_original_existing_durable_blob_owner_to_the_reopened_engine() {
    use latent_blobs::local::{LocalBlobLimits, LocalBlobStore};
    let (root, settings, mut first) = fixture();
    let blob_root = root.path().join("durable-blobs");
    std::fs::create_dir(&blob_root).unwrap();
    std::fs::set_permissions(&blob_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let state = first.open_store(&settings).await.unwrap();
    let path = blob_root.clone();
    let owner = state
        .with_store(StoreIoKind::Read, 4096, move |engine| {
            LocalBlobStore::open_durable(&path, "private", LocalBlobLimits::default(), engine)
                .map_err(|_| StoreError::Unavailable)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let tenant = latent_core::TenantId("tenant".into());
    let mut writer = owner
        .create(&tenant, "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    writer.write(0, b"data", &|| Ok(())).unwrap();
    let blob = writer.seal(&|| Ok(())).unwrap();
    drop(owner);
    state.close();
    let report = state
        .drain_async(
            first.deadline,
            tokio::time::sleep_until(first.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    state.reap_retired_threads().unwrap();
    drop(state);
    drop(first);

    let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
    let mut second = StateBootstrap::new_state(&settings, &clock).unwrap();
    let owner = LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()).unwrap();
    let pointer = Arc::as_ptr(&owner);
    let provider = crate::config::ProviderIdentity {
        id: "local".into(),
        tenant: tenant.0.clone(),
        service: "blob".into(),
        epoch: 1,
    };
    let owner = second
        .open_store_with_local_payloads(&settings, owner, provider, blob_root.clone())
        .await
        .unwrap();
    assert_eq!(Arc::as_ptr(&owner), pointer);
    let pin = owner
        .capture_durable_reference(&tenant, &blob, &|| Ok(()))
        .unwrap();
    assert_eq!(pin.store_identity(), settings.store_identity.as_str());
    drop(pin);
    drop(owner);
    let state = Arc::clone(second.opened_store.as_ref().unwrap());
    state.close();
    let report = state
        .drain_async(
            second.deadline,
            tokio::time::sleep_until(second.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    state.reap_retired_threads().unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the standalone linked-payload qualification orchestrator"]
#[expect(
    clippy::too_many_lines,
    reason = "keep the original linked owner across valid and corrupted restart observations"
)]
async fn actual_linked_payload_recovers_and_corruption_refuses_startup() {
    use crate::config::state::{TenantLimitsConfig, TenantQuotaConfig};
    use latent_blobs::local::{LocalBlobLimits, LocalBlobStore};
    let report = std::path::PathBuf::from(
        std::env::var_os("LSF_LINKED_PAYLOAD_REPORT").expect("orchestrator report path"),
    );
    let temp = std::fs::canonicalize(std::env::temp_dir()).unwrap();
    assert_eq!(
        std::fs::canonicalize(report.parent().unwrap()).unwrap(),
        temp
    );
    let source = std::path::PathBuf::from(std::fs::read_to_string(report).unwrap());
    assert!(!std::fs::symlink_metadata(&source)
        .unwrap()
        .file_type()
        .is_symlink());
    let source = std::fs::canonicalize(source).unwrap();
    assert_eq!(source.parent(), Some(temp.as_path()));
    let (root, mut settings, initial) = fixture();
    drop(initial);
    settings.store_identity = StoreIdentity::new("payload-envelope-a".into()).unwrap();
    settings.tenant_quotas = vec![TenantQuotaConfig {
        tenant: "a".into(),
        limits: TenantLimitsConfig {
            state_keys: 128,
            state_bytes: 4 * 1024 * 1024,
            tombstone_keys: 128,
            tombstone_bytes: 4 * 1024 * 1024,
            result_rows: 128,
            result_bytes: 4 * 1024 * 1024,
            effect_rows: 128,
            effect_bytes: 4 * 1024 * 1024,
            payload_bytes: 4 * 1024 * 1024,
            recovery_bytes: 4 * 1024 * 1024,
            metadata_rows: 1024,
            metadata_bytes: 8 * 1024 * 1024,
        },
    }];
    let state_path = settings.store.root.join(&settings.store.file_name);
    std::fs::rename(source.join("state.redb"), &state_path).unwrap();
    std::fs::set_permissions(&state_path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let blob_root = root.path().join("provider-blobs-payload-local");
    std::fs::rename(source.join("blobs"), &blob_root).unwrap();
    let provider = crate::config::ProviderIdentity {
        id: "payload-local".into(),
        tenant: "a".into(),
        service: "blob-host".into(),
        epoch: 1,
    };
    let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
    let mut bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    let owner = LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()).unwrap();
    let owner = bootstrap
        .open_store_with_local_payloads(&settings, owner, provider.clone(), blob_root.clone())
        .await
        .unwrap();
    let state = Arc::clone(bootstrap.opened_store.as_ref().unwrap());
    let (references, state_link, stored_value, owner_count) = state
        .with_store(StoreIoKind::Read, 8192, |engine| {
            let view = engine.snapshot()?;
            let page = latent_state::payload_references::required_owner_page(&view, None, 4, 4096)?;
            if page.resume.is_some() {
                return Err(latent_state::embedded::StoreError::Capacity);
            }
            let scope = latent_state::session::StateScope {
                tenant: latent_core::TenantId("a".into()),
                namespace: latent_core::StateNamespaceId("aggregate".into()),
                incarnation: 1,
                state_schema: format!("sha256:{}", "4".repeat(64)),
                entity: None,
                mode: latent_state::session::StateMode::Command,
            };
            let cell = latent_state::session::state_payload_cell_key(&scope, b"attached")?;
            let link = latent_state::session::retained_state_payload_reference(&view, &cell)?
                .ok_or(latent_state::embedded::StoreError::Corrupt)?;
            let (_, value) = latent_state::session::describe_state_payload_owner(&view, &cell)?;
            let count = latent_state::payload_references::physical_owner_count(
                &view,
                &link.reference.payload,
            )?;
            Ok((page.references, link, value, count))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(references.len(), 2);
    let result = references
        .iter()
        .find(|reference| {
            reference.owner.kind == latent_state::payload_references::PayloadOwnerKind::Result
        })
        .unwrap();
    let state_reference = references
        .iter()
        .find(|reference| {
            reference.owner.kind == latent_state::payload_references::PayloadOwnerKind::State
        })
        .unwrap();
    assert_eq!(state_link.reference, *state_reference);
    assert_eq!(stored_value.bytes, b"body");
    assert_eq!(owner_count, Some(2));
    assert_eq!(result.payload, state_reference.payload);
    assert_eq!(result.payload.tenant, "a");
    assert_eq!(result.payload.provider, "payload-local");
    assert_eq!(result.payload.size, 4);
    let physical = &result.payload;
    let blob = latent_blobs::BlobReference {
        digest: latent_core::BlobDigest(format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(physical.digest)
        )),
        size_bytes: physical.size,
        media_type: physical.media_type.clone(),
        tenant: latent_core::TenantId(physical.tenant.clone()),
        metadata: latent_core::Metadata::new(),
    };
    let reader = owner.open_read(&blob.tenant, &blob, &|| Ok(())).unwrap();
    let mut bytes = [0; 4];
    reader
        .read(
            &latent_blobs::BlobRange {
                offset: 0,
                length: 4,
            },
            &mut bytes,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(&bytes, b"body");
    drop(reader);
    drop(owner);
    state.close();
    let report = state
        .drain_async(
            bootstrap.deadline,
            tokio::time::sleep_until(bootstrap.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    state.reap_retired_threads().unwrap();
    drop(state);
    drop(bootstrap);
    let owner = LocalBlobStore::open(&blob_root, "private", LocalBlobLimits::default()).unwrap();
    let object = std::fs::read_dir(blob_root.join("objects"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    std::fs::write(object.join("data"), b"evil").unwrap();
    let mut corrupt = StateBootstrap::new_state(&settings, &clock).unwrap();
    assert!(corrupt
        .open_store_with_local_payloads(&settings, owner, provider, blob_root)
        .await
        .is_err());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_blob_provider_installs_after_the_same_prepaid_state_initializer() {
    Box::pin(provider_installs_after_state_initializer(false)).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_blob_provider_reuses_a_reopened_durable_owner() {
    Box::pin(provider_installs_after_state_initializer(true)).await;
}

#[expect(
    clippy::too_many_lines,
    reason = "keep real provider, prepaid state and orderly retirement in one fixture"
)]
async fn provider_installs_after_state_initializer(durable: bool) {
    use crate::standalone::{
        audit::AuditRuntime,
        policies::PolicyRuntime,
        providers::{ProviderRuntime, ProviderServices},
    };
    use latent_artifacts::DirectoryArtifactRepository;
    use latent_control_store::DirectoryDeploymentRepository;
    let (root, settings, mut bootstrap) = fixture();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let input = serde_json::json!({
        "formatVersion":1, "dataDirectory":root.path(), "nodeId":"payload-provider-test", "bind":"127.0.0.1:0",
        "credentials":[{"token":"LSF-PUBLIC-PAYLOAD-PROVIDER-TEST-ONLY","subject":"operator","tenant":"tenant","role":"operator"}],
        "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8,"maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
        "audit":{"mode":"durable"}, "capabilityPolicies":{"formatVersion":1},
        "providers":{"formatVersion":1,"blob":{"identity":{"id":"local","tenant":"tenant","service":"blob-host","epoch":1},"namespace":"private"},"bindings":[{"name":"blob-binding","tenant":"tenant","consumerService":"guest-blob","providerService":"blob-host","contract":"latent:blob/blob@0.2.0","providerBinding":"installed"}]}
    });
    let config = root.path().join("provider-config.json");
    std::fs::write(&config, serde_json::to_vec(&input).unwrap()).unwrap();
    std::fs::set_permissions(&config, std::fs::Permissions::from_mode(0o600)).unwrap();
    let input = crate::config::NodeConfig::load(&config).unwrap();
    let mut node = input.derive().unwrap();
    node.state = Some(settings.clone());
    let runtime = tokio::runtime::Handle::current();
    let clock: Arc<dyn latent_core::ActivationClock> = Arc::new(SystemActivationClock);
    if durable {
        use latent_blobs::local::{LocalBlobLimits, LocalBlobStore};
        let state = bootstrap.open_store(&settings).await.unwrap();
        let blob_root = root.path().join("provider-blobs-local");
        std::fs::create_dir(&blob_root).unwrap();
        std::fs::set_permissions(&blob_root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let owner = state
            .with_store(StoreIoKind::Read, 4096, move |engine| {
                LocalBlobStore::open_durable(
                    &blob_root,
                    "private",
                    LocalBlobLimits::default(),
                    engine,
                )
                .map_err(|_| StoreError::Unavailable)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        drop(owner);
        state.close();
        let report = state
            .drain_async(
                bootstrap.deadline,
                tokio::time::sleep_until(bootstrap.deadline.into()),
            )
            .unwrap()
            .await;
        assert!(report.clean && report.snapshot.physically_retired());
        state.reap_retired_threads().unwrap();
        drop(state);
        drop(bootstrap);
        bootstrap = StateBootstrap::new_state(&settings, &clock).unwrap();
    }
    let audit = AuditRuntime::open(root.path().join("audit"), node.audit, runtime.clone())
        .await
        .unwrap()
        .unwrap();
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open(root.path().join("releases"), node.artifacts).unwrap(),
    );
    artifacts
        .lifecycle_authority()
        .install_rejection_observer(bootstrap.authority.rejection_observer())
        .unwrap();
    let policies = PolicyRuntime::open_with_rejection(
        &root.path().join("capability-policies"),
        node.capability_policies,
        artifacts.lifecycle_authority(),
        Some(&runtime),
        Some(bootstrap.authority.rejection_observer()),
    )
    .unwrap()
    .unwrap();
    let deployments = Arc::new(
        DirectoryDeploymentRepository::open_with_catalog(
            root.path().join("deployments"),
            artifacts.clone(),
            node.deployments,
            artifacts.lifecycle_authority(),
            Arc::clone(&node.runtime_profile),
        )
        .await
        .unwrap(),
    );
    let provider = ProviderRuntime::open(
        &node,
        &artifacts,
        &deployments,
        policies.handle().store().clone(),
        ProviderServices {
            audit: audit.handle(),
            clock,
            control: runtime,
            telemetry: None,
        },
        Some(&mut bootstrap),
    )
    .await
    .unwrap();
    assert!(provider
        .descriptors()
        .iter()
        .any(|entry| serde_json::to_value(entry).unwrap()["id"] == "local"));
    let state = Arc::clone(bootstrap.opened_store.as_ref().unwrap());
    assert!(state.uses_native_capacity(&bootstrap.native));
    assert!(bootstrap.matches_local_payload(&node));
    node.providers
        .as_mut()
        .unwrap()
        .blob
        .as_mut()
        .unwrap()
        .identity
        .epoch += 1;
    assert!(!bootstrap.matches_local_payload(&node));
    node.providers
        .as_mut()
        .unwrap()
        .blob
        .as_mut()
        .unwrap()
        .identity
        .epoch -= 1;
    node.providers
        .as_mut()
        .unwrap()
        .blob
        .as_mut()
        .unwrap()
        .namespace = "other".into();
    assert!(!bootstrap.matches_local_payload(&node));
    node.providers
        .as_mut()
        .unwrap()
        .blob
        .as_mut()
        .unwrap()
        .namespace = "private".into();
    assert!(bootstrap.matches_local_payload(&node));
    let original_data = node.data_directory.clone();
    node.data_directory = original_data.join("different");
    assert!(!bootstrap.matches_local_payload(&node));
    node.data_directory = original_data;
    assert_eq!(
        root.path()
            .join("provider-blobs-local")
            .join("DURABLE.json")
            .exists(),
        durable
    );
    assert!(
        provider
            .shutdown(std::time::Instant::now() + std::time::Duration::from_secs(10))
            .await
            .unwrap()
            .clean
    );
    drop(provider);
    state.close();
    let report = state
        .drain_async(
            bootstrap.deadline,
            tokio::time::sleep_until(bootstrap.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    state.reap_retired_threads().unwrap();
    drop(state);
    drop(bootstrap);
    drop(policies);
    let _ = audit.shutdown(std::time::Duration::from_secs(5)).await;
}

#[tokio::test]
async fn actual_namespace_catalog_reuses_retired_initializer_work_until_its_last_real_owner_drops()
{
    let (_root, settings, mut bootstrap) = fixture();
    let native = bootstrap.native.clone();
    let store = bootstrap.open_store(&settings).await.unwrap();
    let namespaces = bootstrap.open_namespaces(&settings).unwrap();
    assert!(namespaces.uses_native_capacity(&native));
    assert!(bootstrap.open_namespaces(&settings).is_err());
    let metadata =
        latent_state::namespace::lifecycle::NamespaceLifecycleRegistry::retained_memory_bytes(
            latent_state::namespace::lifecycle::NamespaceLifecycleLimits::default(),
        )
        .unwrap();
    let remaining = settings.startup_work_bytes
        - settings.store.io.resident_bytes
        - crate::config::state::STARTUP_APPLICATION_BYTES
        - latent_effects::authority::EffectAuthorityOwner::retained_memory_bytes(
            crate::config::state::EFFECT_AUTHORITY_MAXIMUM_RULES,
        )
        .unwrap()
        - metadata;
    let original = bootstrap.original();
    assert!(original
        .reserve_buffer(
            latent_core::native_capacity::NativeBufferClass::Work,
            remaining + 1
        )
        .is_err());
    let probe = original
        .reserve_buffer(
            latent_core::native_capacity::NativeBufferClass::Work,
            remaining,
        )
        .unwrap();
    drop(probe);
    drop(original);
    store.close();
    let report = store
        .drain_async(
            bootstrap.deadline,
            tokio::time::sleep_until(bootstrap.deadline.into()),
        )
        .unwrap()
        .await;
    assert!(report.clean && report.snapshot.physically_retired());
    store.reap_retired_threads().unwrap();
    drop(bootstrap);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(namespaces);
    assert!(native.snapshot().unwrap().physically_retired());
}

struct Gate {
    release: Mutex<bool>,
    wake: Condvar,
}

#[tokio::test]
async fn detached_actual_initializer_keeps_native_admission_until_worker_buffers_and_files_retire()
{
    let (_root, settings, mut bootstrap) = fixture();
    let native = bootstrap.native.clone();
    let deadline = bootstrap.deadline;
    let gate = Arc::new(Gate {
        release: Mutex::new(false),
        wake: Condvar::new(),
    });
    let (entered, observed) = tokio::sync::oneshot::channel();
    let blocked = Arc::clone(&gate);
    let task = tokio::spawn(async move {
        bootstrap
            .open_store_inner(
                &settings,
                Some(Box::new(move || {
                    entered.send(()).unwrap();
                    let held = blocked.release.lock().unwrap();
                    let (released, timeout) = blocked
                        .wake
                        .wait_timeout_while(
                            held,
                            deadline
                                .checked_duration_since(std::time::Instant::now())
                                .unwrap(),
                            |released| !*released,
                        )
                        .unwrap();
                    assert!(!timeout.timed_out() && *released);
                })),
                false,
                StartupPayload::None,
            )
            .await
    });
    tokio::time::timeout_at(deadline.into(), observed)
        .await
        .unwrap()
        .unwrap();
    task.abort();
    let Err(cancelled) = task.await else {
        panic!("detached initializer unexpectedly returned a ready owner")
    };
    assert!(cancelled.is_cancelled());
    let snapshot = native.snapshot().unwrap();
    assert!(snapshot.quarantined);
    assert_eq!(snapshot.recovery.slots, 1);
    assert!(!snapshot.physically_retired());
    *gate.release.lock().unwrap() = true;
    gate.wake.notify_one();
    let retired = native
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(!retired.clean);
    assert!(retired.snapshot.physically_retired());
}
