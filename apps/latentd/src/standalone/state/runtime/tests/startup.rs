//! The actual signed installed HTTP branch must release only boot suppression.
use super::*;
use crate::standalone::effects::{DispatcherControlRequest, ProtectedEffectStartup};
use crate::standalone::state::installations::tests::{
    startup::{installed, HttpFixture},
    Setup,
};
use latent_effects::runtime::{DeferredEffectAdapter, DispatcherControlAction};
use latent_state::protected_store::ProtectedCheckpointConfig;

struct InstalledRuntime {
    state: StandaloneStateRuntime,
    effects: EffectRuntime,
    fixture: Fixture,
    services: crate::standalone::state::InstalledStateServices,
    policy: Arc<PolicyStore>,
}

fn from_installed(
    setup: Setup,
    installed: crate::standalone::state::installations::InstalledState,
) -> InstalledRuntime {
    assert!(installed.http_rules);
    let original_deadline = setup.kernel.original_deadline().unwrap();
    let state = StandaloneStateRuntime {
        kernel: setup.kernel,
        admission: Some(setup.owners),
        installations: installed.installations,
        management: installed.management,
        operations: setup.fixture.settings.operations.clone(),
        original_deadline,
        ready: false,
        http_rules: installed.http_rules,
    };
    InstalledRuntime {
        state,
        effects: setup.effects,
        fixture: setup.fixture,
        services: setup.services,
        policy: setup.policy,
    }
}

async fn pause(
    effects: &EffectRuntime,
    id: &str,
) -> latent_effects::runtime::DispatcherControlReceipt {
    let request = DispatcherControlRequest::new(
        "tests".into(),
        "operator".into(),
        id.into(),
        effects.snapshot().unwrap().control.generation,
        DispatcherControlAction::Pause,
    )
    .unwrap();
    let prepared = effects.prepare_dispatcher_control(request).unwrap();
    tokio::time::timeout(
        Duration::from_secs(10),
        effects
            .submit_dispatcher_control(prepared, |accept| accept())
            .unwrap(),
    )
    .await
    .unwrap()
    .unwrap()
    .unwrap()
    .unwrap()
    .receipt
}

async fn retire(
    state: StandaloneStateRuntime,
    mut effects: EffectRuntime,
    services: crate::standalone::state::InstalledStateServices,
    policy: Arc<PolicyStore>,
) {
    let deadline = state.original_deadline;
    let store = state.kernel.store.clone();
    let native = state.kernel.native.clone();
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    drop(services);
    drop(policy);
    let report = state.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.store_physically_retired && report.native_physically_retired);
    observe_actual_retirement(&store, &native).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_installed_http_readiness_preserves_saved_pause_after_new_dispatcher_epoch() {
    let http = HttpFixture::new().await;
    let mut setup = http.setup().await;
    let installed_first = installed(&setup).await;
    assert!(setup.fixture.settings.dispatcher.start_paused);
    let original = pause(&setup.effects, "saved-operator-pause").await;
    drop(installed_first);
    let deadline = setup.kernel.original_deadline().unwrap();
    let first = setup.effects.shutdown(deadline).await.unwrap();
    assert!(first.clean && first.physically_retired && first.scheduling_owner_retired);
    let mut dispatcher = setup.fixture.settings.dispatcher.clone();
    dispatcher.start_paused = false; // The same private StateKernel bootstrap translation.
    let (effects, clock) = EffectRuntime::start_protected(ProtectedEffectStartup {
        dispatcher,
        store: setup.kernel.store.clone(),
        authority: setup.authority.clone(),
        adapters: setup
            .services
            .http
            .adapters
            .iter()
            .cloned()
            .map(|a| a as Arc<dyn DeferredEffectAdapter>)
            .collect(),
        supply_chain: setup.fixture.authority.clone(),
        clock: setup.fixture.clock.clone(),
        checkpoint: ProtectedCheckpointConfig {
            root: setup.fixture.settings.checkpoint_root.clone(),
        },
        identity: setup.fixture.settings.store_identity.clone(),
        preparation: None,
        original_deadline: deadline,
        control_runtime: tokio::runtime::Handle::current(),
    })
    .await
    .unwrap();
    drop(std::mem::replace(&mut setup.effects, effects));
    setup.kernel.clock = clock;
    setup.owners = setup
        .kernel
        .admission_owners(setup.policy.clone(), &setup.effects)
        .unwrap();
    let captured = crate::standalone::state::installations::load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    let InstalledRuntime {
        mut state,
        effects,
        fixture,
        services,
        policy,
    } = from_installed(setup, captured);
    let before = effects.snapshot().unwrap();
    assert!(before.paused);
    assert!(before.control.generation.owner_epoch() > original.generation().owner_epoch());
    state.publish_ready(&effects).unwrap();
    assert!(state.is_running(&effects));
    let after = effects.snapshot().unwrap();
    let saved_pause_preserved = after.paused;
    assert_eq!(after.claims, 0);
    assert_eq!(after.accepted_effects, 0);
    let historical = effects
        .lookup_dispatcher_control(original.request().clone())
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(historical, original);
    let second_ready_refused = state.publish_ready(&effects).is_err();
    retire(state, effects, services, policy).await;
    drop(fixture);
    http.finish().await;
    // Cleanup is explicit even for the intended original-source RED assertion.
    assert!(second_ready_refused);
    assert!(
        saved_pause_preserved,
        "installed readiness overwrote the actual saved operator Pause"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_fresh_installed_http_readiness_releases_only_derived_bootstrap_hold() {
    let http = HttpFixture::new().await;
    let setup = http.setup().await;
    let captured = installed(&setup).await;
    let InstalledRuntime {
        mut state,
        effects,
        fixture,
        services,
        policy,
    } = from_installed(setup, captured);
    assert!(fixture.settings.dispatcher.start_paused);
    assert!(effects.snapshot().unwrap().paused);
    state.publish_ready(&effects).unwrap();
    assert!(state.is_running(&effects));
    assert!(!effects.snapshot().unwrap().paused);
    assert!(state.publish_ready(&effects).is_err());
    retire(state, effects, services, policy).await;
    drop(fixture);
    http.finish().await;
}

#[tokio::test]
async fn actual_ready_non_http_runtime_keeps_default_pause_then_accepts_current_managed_resume() {
    let fixture = Fixture::new();
    let (mut state, effects, policies) = started(&fixture).await;
    let generation = effects.snapshot().unwrap().control.generation;
    state.publish_ready(&effects).unwrap();
    assert!(state.is_running(&effects));
    assert!(effects.snapshot().unwrap().paused);
    assert_eq!(effects.snapshot().unwrap().control.generation, generation);
    let request = DispatcherControlRequest::new(
        "tests".into(),
        "operator".into(),
        "resume-ready-non-http".into(),
        generation,
        DispatcherControlAction::Resume,
    )
    .unwrap();
    let prepared = effects.prepare_dispatcher_control(request).unwrap();
    let outcome = effects
        .submit_dispatcher_control(prepared, |accept| accept())
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(outcome.published && !outcome.paused);
    assert!(!effects.snapshot().unwrap().paused);
    assert!(state.is_running(&effects));
    let deadline = state.original_deadline;
    let mut effects = effects;
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    drop(policies);
    let report = state.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.store_physically_retired && report.native_physically_retired);
}

#[tokio::test]
async fn actual_current_non_http_resume_under_bootstrap_hold_waits_for_readiness() {
    let fixture = Fixture::new();
    let (mut state, mut effects, policies) = started(&fixture).await;
    let request = DispatcherControlRequest::new(
        "tests".into(),
        "operator".into(),
        "resume-before-non-http-ready".into(),
        effects.snapshot().unwrap().control.generation,
        DispatcherControlAction::Resume,
    )
    .unwrap();
    let prepared = effects.prepare_dispatcher_control(request).unwrap();
    let outcome = effects
        .submit_dispatcher_control(prepared, |accept| accept())
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(outcome.paused && !outcome.published);
    assert!(effects.snapshot().unwrap().paused);
    assert_eq!(effects.snapshot().unwrap().claims, 0);
    assert!(!state.is_running(&effects));
    let generation = effects.snapshot().unwrap().control.generation;
    state.publish_ready(&effects).unwrap();
    assert!(!effects.snapshot().unwrap().paused);
    assert_eq!(effects.snapshot().unwrap().control.generation, generation);
    assert!(state.is_running(&effects));
    let deadline = state.original_deadline;
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    drop(policies);
    let report = state.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.store_physically_retired && report.native_physically_retired);
}
