use super::*;
use latent_core::SystemActivationClock;
use latent_state::{embedded::StoreError, store_identity::StoreIdentity, store_io::StoreIoKind};
use std::{
    os::unix::fs::PermissionsExt,
    sync::{Condvar, Mutex},
};

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
