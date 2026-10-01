use super::*;
use latent_core::native_capacity::{NativeCapacityLimits, NativeCapacityOwner};
use latent_effects::{
    authority::{EffectAuthorityOwner, EffectTime},
    runtime::{DispatcherConfig, DispatcherOwner},
};
use std::os::unix::fs::PermissionsExt;

fn services(fixture: &Fixture) -> StateManagementServices {
    let value = &fixture.backend.0.services;
    StateManagementServices {
        store: Arc::clone(&value.store),
        namespaces: Arc::clone(&value.namespaces),
        policy: Arc::clone(&value.policy),
        artifacts: Arc::clone(&value.artifacts),
        authorization: Arc::clone(&value.authorization),
        admission: Arc::clone(&value.admission),
        clock: Arc::clone(&value.clock),
        audit: value.audit.clone(),
    }
}
fn bindings(fixture: &Fixture) -> Vec<StateManagementBinding> {
    let value = &fixture.backend.0.bindings[0];
    vec![fixture::binding(
        value.publication.clone(),
        value.component.clone(),
    )]
}
#[tokio::test]
async fn management_construction_rejects_unbound_or_foreign_native_owner_before_lookup() {
    let mut fixture = Fixture::new(false).await;
    let mut foreign = services(&fixture);
    foreign.admission = Arc::new(StateManagementRecoveryAdmission::new(
        NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap(),
    ));
    assert!(StateManagementBackend::new(foreign, bindings(&fixture)).is_err());
    let alias = StateManagementBackend::new(services(&fixture), bindings(&fixture)).unwrap();
    assert!(alias
        .0
        .services
        .store
        .uses_native_capacity(&fixture.admission.native));
    let mut config = fixture.config.clone();
    config.root = config.root.parent().unwrap().join("unbound-store");
    std::fs::create_dir(&config.root).unwrap();
    std::fs::set_permissions(&config.root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let unbound = Arc::new(fixture::start(config).await);
    let mut missing = services(&fixture);
    missing.store = Arc::clone(&unbound);
    assert!(StateManagementBackend::new(missing, bindings(&fixture)).is_err());
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    unbound.close();
    assert!(
        unbound
            .drain_async(deadline(), std::future::pending())
            .unwrap()
            .await
            .clean
    );
    drop(alias);
    fixture.finish().await;
}

#[tokio::test]
async fn management_dispatcher_binding_rejects_a_foreign_global_owner_on_the_same_engine() {
    let mut fixture = Fixture::new(false).await;
    let mut dispatcher = DispatcherOwner::start(
        DispatcherConfig {
            start_paused: true,
            ..DispatcherConfig::default()
        },
        Arc::clone(&fixture.store),
        EffectAuthorityOwner::new(16, 4, 4).unwrap(),
        vec![],
        Arc::new(|| EffectTime {
            unix_millis: 100,
            continuity_proven: true,
        }),
        None,
    )
    .await
    .unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    dispatcher.bind_native_capacity(&foreign).unwrap();
    assert!(dispatcher.management_port().uses_store(&fixture.store));
    assert!(!dispatcher
        .management_port()
        .uses_native_capacity(&fixture.admission.native));
    let backend = StateManagementBackend::new(services(&fixture), bindings(&fixture)).unwrap();
    assert!(backend
        .with_dispatcher(dispatcher.management_port())
        .is_err());
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert!(dispatcher.shutdown(deadline()).await.unwrap().clean);
    fixture.finish().await;
}

struct MismatchedReservationAdmission {
    installed: NativeCapacityOwner,
    foreign: StateManagementRecoveryAdmission,
}
impl StateManagementAdmission for MismatchedReservationAdmission {
    fn native_capacity(&self) -> NativeCapacityOwner {
        self.installed.clone()
    }
    fn reserve_recovery(
        &self,
        request: usize,
        work: usize,
        response: usize,
        deadline: Instant,
    ) -> Result<Arc<dyn StateManagementReservation>, PlatformError> {
        self.foreign
            .reserve_recovery(request, work, response, deadline)
    }
}
#[tokio::test]
async fn foreign_actual_request_reservation_is_refused_before_native_management_submission() {
    let mut fixture = Fixture::new(false).await;
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let mut setup = services(&fixture);
    setup.admission = Arc::new(MismatchedReservationAdmission {
        installed: fixture.admission.native.clone(),
        foreign: StateManagementRecoveryAdmission::new(foreign.clone()),
    });
    let backend = StateManagementBackend::new(setup, bindings(&fixture)).unwrap();
    let response = backend
        .execute_state(context("alice"), fixture.target().into())
        .await;
    assert_eq!(
        response.err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    assert!(foreign.snapshot().unwrap().physically_retired());
    fixture.finish().await;
}
