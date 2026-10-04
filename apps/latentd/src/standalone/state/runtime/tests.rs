//! The production caller owns the actual startup, factory and physical drain.
use super::*;
use crate::standalone::state::kernel::tests::Fixture;
use latent_artifacts::{
    AdmissionStorageLimits, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{native_capacity::NativeCapacityOwner, ActivationClock};
use latent_effects::authority::EffectAuthorityOwner;
use latent_policy::capability::PolicyStoreLimits;
use latent_state::{protected_store::ProtectedStoreOwner, store_io::StoreIoKind};
use std::{
    sync::{Condvar, Mutex},
    time::Duration,
};

struct Policies {
    store: Arc<PolicyStore>,
    _catalog: DirectoryArtifactRepository,
}

fn policies(fixture: &Fixture, effects: &EffectAuthorityOwner) -> Policies {
    let catalog = DirectoryArtifactRepository::open_enforced(
        fixture.root().join("actual-catalog"),
        DirectoryArtifactRepositoryConfig {
            manifest_profile: latent_manifest::ManifestValidationProfile::phase4(
                latent_core::BudgetProfile::Phase4,
                latent_core::PHASE4_HOST_ABI_V1,
                &latent_manifest::phase4_host_abi_digest(),
            )
            .unwrap(),
            ..DirectoryArtifactRepositoryConfig::default()
        },
        AdmissionStorageLimits::default(),
        fixture.authority.clone(),
    )
    .unwrap();
    let observer = effects.rejection_observer();
    catalog
        .lifecycle_authority()
        .install_rejection_observer(Arc::clone(&observer))
        .unwrap();
    let store = Arc::new(
        PolicyStore::open(
            &fixture.root().join("actual-policies"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    store.install_rejection_observer(observer).unwrap();
    Policies {
        store,
        _catalog: catalog,
    }
}

async fn started(fixture: &Fixture) -> (StandaloneStateRuntime, EffectRuntime, Policies) {
    let bootstrap = fixture.bootstrap();
    let policies = policies(fixture, &bootstrap.authority);
    let (state, effects) = StandaloneStateRuntime::start(
        bootstrap,
        &fixture.settings,
        fixture.authority.clone(),
        Arc::clone(&policies.store),
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    (state, effects, policies)
}

async fn observe_actual_retirement(store: &ProtectedStoreOwner, native: &NativeCapacityOwner) {
    // This bounded observation never extends the accepted work or drain cutoff.
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if store.snapshot().unwrap().physically_retired()
                && native.snapshot().unwrap().physically_retired()
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    store.reap_retired_threads().unwrap();
}

#[tokio::test]
async fn actual_standalone_caller_reaches_ready_once_with_same_factory_capacity_and_paused_dispatcher(
) {
    let fixture = Fixture::new();
    let (mut state, mut effects, _policies) = started(&fixture).await;
    let native = state.kernel.native.clone();
    let store = Arc::clone(&state.kernel.store);
    assert!(!state.is_running(&effects));
    assert!(fixture.checkpoint().is_file());
    state.publish_ready(&effects).unwrap();
    assert!(state.is_running(&effects));
    assert!(state.publish_ready(&effects).is_err());
    let snapshot = effects.snapshot().unwrap();
    assert!(snapshot.paused && !snapshot.admission_closed && !snapshot.quarantined);
    assert_eq!(snapshot.claims, 0);
    let deadline = fixture.clock.monotonic_now() + Duration::from_secs(20);
    let ingress = state
        .admission
        .as_ref()
        .unwrap()
        .reserve_ingress(32, deadline)
        .unwrap();
    assert!(ingress.is_from_owner(&native));
    assert_eq!(native.snapshot().unwrap().ordinary.slots, 1);
    drop(ingress);
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    let report = state.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.store_physically_retired && report.native_physically_retired);
    assert_eq!(report.namespace_owners, 0);
    assert_eq!(report.storage_retained_bytes, 0);
    assert_eq!(
        report.ordinary_native_bytes + report.recovery_native_bytes,
        0
    );
    observe_actual_retirement(&store, &native).await;
}

#[tokio::test]
async fn configured_installations_refuse_before_business_io_instead_of_exposing_stateless_readiness(
) {
    for installed_targets in [false, true] {
        let mut fixture = Fixture::new();
        let input = crate::config::state::tests::input();
        let config = serde_json::from_value(input).unwrap();
        let mut declarations = crate::config::state::derive(&config, fixture.root()).unwrap();
        if installed_targets {
            fixture.settings.operations = std::mem::take(&mut declarations.operations);
        } else {
            fixture.settings.tenant_quotas = std::mem::take(&mut declarations.tenant_quotas);
        }
        let bootstrap = fixture.bootstrap();
        let native = bootstrap.native.clone();
        let policies = policies(&fixture, &bootstrap.authority);
        assert!(StandaloneStateRuntime::start(
            bootstrap,
            &fixture.settings,
            fixture.authority.clone(),
            policies.store.clone(),
            tokio::runtime::Handle::current(),
        )
        .await
        .is_err());
        assert!(!fixture
            .settings
            .store
            .root
            .join(&fixture.settings.store.file_name)
            .exists());
        assert!(!fixture.checkpoint().exists());
        let retired = native.snapshot().unwrap();
        assert!(retired.admission_closed && retired.physically_retired());
        assert!(!retired.quarantined);
    }
}

#[tokio::test]
async fn a_foreign_policy_observer_refuses_before_checkpoint_or_dispatch_epoch_allocation() {
    let fixture = Fixture::new();
    let bootstrap = fixture.bootstrap();
    let native = bootstrap.native.clone();
    let foreign = EffectAuthorityOwner::new(1, 1, 0).unwrap();
    let policies = policies(&fixture, &foreign);
    assert!(StandaloneStateRuntime::start(
        bootstrap,
        &fixture.settings,
        fixture.authority.clone(),
        policies.store.clone(),
        tokio::runtime::Handle::current(),
    )
    .await
    .is_err());
    assert!(!fixture
        .settings
        .store
        .root
        .join(&fixture.settings.store.file_name)
        .exists());
    assert!(!fixture.checkpoint().exists());
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn closing_the_actual_dispatch_role_removes_readiness_without_releasing_store_residency() {
    let fixture = Fixture::new();
    let (mut state, mut effects, _policies) = started(&fixture).await;
    state.publish_ready(&effects).unwrap();
    let native = state.kernel.native.clone();
    let store = Arc::clone(&state.kernel.store);
    effects.close();
    assert!(!state.is_running(&effects));
    assert!(!store.snapshot().unwrap().physically_retired());
    assert!(native.snapshot().unwrap().recovery.bytes > 0);
    let deadline = state.original_deadline;
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    let report = state.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.store_physically_retired && report.native_physically_retired);
}

#[tokio::test]
async fn the_original_boot_deadline_refuses_late_readiness_and_never_renews_native_cleanup() {
    let fixture = Fixture::new();
    let (mut state, mut effects, _policies) = started(&fixture).await;
    let deadline = state.original_deadline;
    let native = state.kernel.native.clone();
    let store = Arc::clone(&state.kernel.store);
    let ingress = state
        .admission
        .as_ref()
        .unwrap()
        .reserve_ingress(32, deadline)
        .unwrap();
    fixture.clock.advance_to(deadline);
    assert!(state.publish_ready(&effects).is_err());
    assert!(!state.is_running(&effects));
    let _report = effects.shutdown(deadline).await;
    drop(effects);
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        state.shutdown(deadline + Duration::from_secs(20)),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(!report.clean);
    assert_eq!(report.ordinary_native_reservations, 1);
    assert!(report.ordinary_native_bytes > 0);
    drop(ingress);
    observe_actual_retirement(&store, &native).await;
    assert!(native.snapshot().unwrap().quarantined);
}

struct Gate {
    released: Mutex<bool>,
    wake: Condvar,
}

#[tokio::test]
async fn a_live_native_worker_keeps_original_capacity_after_failed_standalone_drain() {
    let fixture = Fixture::new();
    let (mut state, mut effects, _policies) = started(&fixture).await;
    state.publish_ready(&effects).unwrap();
    let store = Arc::clone(&state.kernel.store);
    let native = state.kernel.native.clone();
    let gate = Arc::new(Gate {
        released: Mutex::new(false),
        wake: Condvar::new(),
    });
    let blocked = Arc::clone(&gate);
    let (entered, entry) = tokio::sync::oneshot::channel();
    let work = store
        .with_store(StoreIoKind::Read, 64, move |_engine| {
            entered.send(()).unwrap();
            let release = blocked.released.lock().unwrap();
            let (release, limit) = blocked
                .wake
                .wait_timeout_while(release, Duration::from_secs(20), |released| !*released)
                .unwrap();
            assert!(*release && !limit.timed_out());
            Ok(())
        })
        .unwrap();
    tokio::time::timeout(Duration::from_secs(5), entry)
        .await
        .unwrap()
        .unwrap();
    let original = state.original_deadline;
    assert!(effects.shutdown(original).await.unwrap().clean);
    drop(effects);
    let report = state.shutdown(fixture.clock.monotonic_now()).await.unwrap();
    assert!(!report.clean && !report.store_physically_retired && !report.native_physically_retired);
    assert!(report.quarantined);
    assert!(report.accepted_storage_jobs > 0);
    assert!(report.recovery_native_bytes > 0);
    assert!(native.snapshot().unwrap().recovery.slots > 0);
    *gate.released.lock().unwrap() = true;
    gate.wake.notify_one();
    work.await.unwrap().unwrap();
    observe_actual_retirement(&store, &native).await;
    assert!(native.snapshot().unwrap().quarantined);
}
