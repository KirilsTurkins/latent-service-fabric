use super::*;
use crate::config::{NodeConfig, StateConfig};
use latent_artifacts::DirectoryArtifactRepositoryConfig;
use latent_core::{test_support::coordination::WATCHDOG, SystemActivationClock, TenantId};
use latent_effects::dispatch_store::DispatchCatalog;
use latent_policy::capability::PolicyStoreLimits;
use latent_state::{store_io::StoreIoKind, tenant::TenantRecord};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf, time::Instant};

struct Fixture {
    _root: tempfile::TempDir,
    settings: NodeSettings,
    artifacts: Arc<DirectoryArtifactRepository>,
    policy: Arc<PolicyStore>,
    clock: Arc<SystemActivationClock>,
}

impl Fixture {
    fn new() -> Self {
        let directory = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(directory).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let data = root.path().join("node");
        for path in [&data, &data.join("state")] {
            fs::create_dir(path).unwrap();
            fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
        }
        let clock = Arc::new(SystemActivationClock);
        let checkpoint = root.path().join("clock.json");
        fs::write(
            &checkpoint,
            serde_json::to_vec(&serde_json::json!({
                "formatVersion": 1, "nodeId": "state-startup-fixture", "ownerEpoch": 1,
                "clockFloorUnixMillis": clock.sample().unix_millis()
            }))
            .unwrap(),
        )
        .unwrap();
        fs::set_permissions(&checkpoint, fs::Permissions::from_mode(0o600)).unwrap();
        let config: NodeConfig = serde_json::from_value(serde_json::json!({
            "formatVersion": 1, "dataDirectory": data, "nodeId": "state-startup-fixture",
            "bind": "127.0.0.1:0", "budgetProfile": {"mode": "phase4"},
            "credentials": [{"token": "LSF-PUBLIC-STATE-STARTUP-TEST-ONLY",
                "subject": "operator", "tenant": "alpha", "role": "operator"}]
        }))
        .unwrap();
        let mut settings = config.derive().unwrap();
        let state: StateConfig = serde_json::from_value(serde_json::json!({
            "formatVersion": 1, "createIfMissing": true, "configurationEpoch": 1,
            "clockCheckpoint": checkpoint, "operations": []
        }))
        .unwrap();
        // This internal composition fixture installs no signed operations or
        // granted policies. Full configuration/admission gates and actual
        // signed Java startup remain independently exercised by their owners.
        let mut state = crate::config::state::derive(&state).unwrap();
        state.tenant_quotas = vec![super::super::validation::test_quota("alpha")];
        settings.state = Some(state);
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open(
                root.path().join("releases"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("policies"),
                PolicyStoreLimits::default(),
                artifacts.lifecycle_authority(),
            )
            .unwrap(),
        );
        Self {
            _root: root,
            settings,
            artifacts,
            policy,
            clock,
        }
    }

    async fn open(&self) -> (Arc<StateRuntime>, super::super::super::EffectRuntime) {
        StateRuntime::open(
            &self.settings,
            Arc::clone(&self.artifacts),
            Arc::clone(&self.policy),
            self.clock.clone(),
            None,
            tokio::runtime::Handle::current(),
            None,
        )
        .await
        .unwrap()
    }
}

async fn observation(store: &ProtectedStoreOwner) -> ((u64, u64), TenantRecord) {
    store
        .with_store(StoreIoKind::Read, 16 * 1024, |engine| {
            let view = engine.snapshot()?;
            Ok((
                DispatchCatalog::owner_checkpoint(&view)?.unwrap(),
                latent_state::tenant::inspect(&view, &TenantId("alpha".into()))?.unwrap(),
            ))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

async fn finish(state: &StateRuntime, effects: &mut super::super::super::EffectRuntime) {
    state.close_ordinary();
    effects.close();
    let deadline = Instant::now() + WATCHDOG;
    let effect = effects.shutdown(deadline).await.unwrap();
    assert!(effect.clean && effect.physically_retired && effect.scheduling_owner_retired);
    assert_eq!(effect.worker_threads_joined, 2);
    assert_eq!(effect.worker_threads_remaining, 0);
    let store = state.shutdown(deadline).await.unwrap();
    assert!(store.clean && !store.store_quarantined && !store.native_quarantined);
    assert!(matches!(
        store.store_engine,
        super::super::lifecycle::StoreEngineState::Closed
    ));
    assert_eq!(store.store_threads_joined, 4);
    assert_eq!(store.store_live_workers, 0);
    assert_eq!(store.store_physical_owners, 0);
}

#[tokio::test]
async fn actual_state_open_initializes_epoch_before_tenant_rows_and_reopens_original_accounting() {
    let mut fixture = Fixture::new();
    let checkpoint = fs::read(&fixture.settings.state.as_ref().unwrap().clock_checkpoint).unwrap();
    let (state, mut effects) = fixture.open().await;
    let original = observation(&state.0.store).await;
    assert_eq!(original.0 .0, 1);
    assert_eq!(original.1.generation, 1);
    assert_eq!(original.1.usage.metadata_rows, 1);
    assert!(state.0.installed.is_empty() && state.0.intents.is_empty());
    assert!(state.0.native.snapshot().unwrap().physically_retired());
    let admission = effects.command_admission_source();
    finish(&state, &mut effects).await;
    assert!(admission.capture().is_err());
    drop((state, effects));
    fixture.settings.state.as_mut().unwrap().create_if_missing = false;
    let (state, mut effects) = fixture.open().await;
    let reopened = observation(&state.0.store).await;
    assert_eq!(reopened.0 .0, 2);
    assert!(reopened.0 .1 >= original.0 .1);
    assert_eq!(reopened.1, original.1);
    assert_eq!(
        fs::read(&fixture.settings.state.as_ref().unwrap().clock_checkpoint).unwrap(),
        checkpoint
    );
    finish(&state, &mut effects).await;
}

#[tokio::test]
async fn expired_post_epoch_tenant_installation_retires_original_dispatcher_and_store() {
    let fixture = Fixture::new();
    let (native, _) =
        startup_capacity(&(fixture.clock.clone() as Arc<dyn ActivationClock>)).unwrap();
    let time = ProtectedCommandClock::load(&fixture.settings, fixture.clock.clone()).unwrap();
    let (store, _) = open_validated_store(&fixture.settings, fixture.clock.clone())
        .await
        .unwrap();
    let authority = EffectAuthorityOwner::new(128, 2, time.minimum_checkpoint().1).unwrap();
    let mut effects = super::super::super::EffectRuntime::start(
        DispatcherConfig::default(),
        Arc::clone(&store),
        authority,
        vec![],
        time.clone(),
        Some(time.minimum_checkpoint()),
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    let original = effects.command_admission_source();
    assert!(finish_tenant_setup(
        &fixture.settings,
        &store,
        &native,
        &[],
        &mut effects,
        Instant::now() - std::time::Duration::from_millis(1),
    )
    .await
    .is_err());
    assert!(original.capture().is_err());
    let effect = effects.snapshot().unwrap();
    assert!(effect.admission_closed && !effect.quarantined);
    assert_eq!(effect.active_jobs, 0);
    assert_eq!(effect.live_workers, 0);
    assert_eq!(effect.physical_owners, 0);
    let snapshot = store.snapshot().unwrap();
    assert!(snapshot.physically_retired() && !snapshot.quarantined);
    assert!(store.failure().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
}
