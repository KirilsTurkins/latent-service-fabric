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
        maintenance: Arc::clone(&value.maintenance),
        maintenance_clock: Arc::clone(&value.maintenance_clock),
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
    assert!(matches!(
        dispatcher.bind_native_capacity(&foreign),
        Err(latent_effects::runtime::DispatcherError::InvalidConfiguration)
    ));
    assert!(dispatcher.management_port().uses_store(&fixture.store));
    assert!(dispatcher
        .management_port()
        .uses_native_capacity(&fixture.admission.native));
    // The original same-engine binding was never replaced. A separately
    // started real foreign engine/dispatcher also cannot satisfy the backend.
    let mut other = Fixture::new(false).await;
    let mut foreign_dispatcher = DispatcherOwner::start(
        DispatcherConfig {
            start_paused: true,
            ..DispatcherConfig::default()
        },
        Arc::clone(&other.store),
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
    assert!(!foreign_dispatcher
        .management_port()
        .uses_store(&fixture.store));
    assert!(!foreign_dispatcher
        .management_port()
        .uses_native_capacity(&fixture.admission.native));
    let backend = StateManagementBackend::new(services(&fixture), bindings(&fixture)).unwrap();
    assert!(backend
        .with_dispatcher(foreign_dispatcher.management_port())
        .is_err());
    // The installed node-only constructor has the same exact owner fence.
    // Empty application bindings cannot turn a foreign pool into permission.
    assert!(StateManagementBackend::with_installed_dispatcher(
        services(&fixture),
        vec![],
        foreign_dispatcher.management_port(),
    )
    .is_err());
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert!(dispatcher.shutdown(deadline()).await.unwrap().clean);
    assert!(foreign_dispatcher.shutdown(deadline()).await.unwrap().clean);
    other.finish().await;
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

#[tokio::test]
async fn recovery_binding_installation_is_bounded_unique_and_frozen_before_sharing() {
    use latent_capabilities::namespace::RecoverySelection;
    let mut fixture = Fixture::new(false).await;
    let build = || StateManagementBackend::new(services(&fixture), bindings(&fixture)).unwrap();
    let mapping = || StateManagementRecoveryBinding {
        selector: "approved-group".into(),
        selection: RecoverySelection::Shared {
            name: "order-readers".into(),
        },
    };
    assert!(build()
        .with_recovery_bindings(vec![mapping(), mapping()])
        .is_err());
    assert!(build()
        .with_recovery_bindings(Vec::with_capacity(129))
        .is_err());
    let installed = build().with_recovery_bindings(vec![mapping()]).unwrap();
    let context = context("alice");
    let original = recovery_bindings::scope(&installed.0, &context, None).unwrap();
    let shared = recovery_bindings::scope(&installed.0, &context, Some("approved-group")).unwrap();
    assert_ne!(original.scope, shared.scope);
    assert_eq!(
        shared.kind,
        latent_policy::capability::RecoveryScopeKind::Shared
    );
    assert!(recovery_bindings::scope(&installed.0, &context, Some(&shared.scope)).is_err());
    assert!(installed.clone().with_recovery_bindings(vec![]).is_err());
    drop(installed);
    assert!(build()
        .with_recovery_bindings(vec![])
        .unwrap()
        .with_recovery_bindings(vec![])
        .is_err());
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    fixture.finish().await;
}

#[tokio::test]
async fn unknown_or_incompatible_requested_recovery_scope_fails_before_native_admission() {
    use latent_capabilities::namespace::RecoverySelection;
    let mut fixture = Fixture::new(false).await;
    let backend = StateManagementBackend::new(services(&fixture), bindings(&fixture))
        .unwrap()
        .with_recovery_bindings(vec![StateManagementRecoveryBinding {
            selector: "service-only".into(),
            selection: RecoverySelection::ServiceIntegration,
        }])
        .unwrap();
    for selector in ["unknown-group", "service-only"] {
        let target = fixture.target();
        let request = c::PlanEffectMutationRequest {
            effect: Some(latent_rpc::transaction::v1::GetEffectRequest {
                profile: target.profile,
                authorization_publication: target.authorization_publication,
                command: Some(latent_rpc::transaction::v1::CommandSelector {
                    namespace: target.namespace,
                    operation: "save".into(),
                    entity: None,
                    client_key: "original-command".into(),
                    shared_recovery_scope: Some(selector.into()),
                }),
                effect_id: "a".repeat(64),
            }),
            operation_id: "original-plan".into(),
            mutation: c::StateMutationKind::TerminateEffect as i32,
            expected_version: vec![1; 32],
            expected_policy_digest: format!("sha256:{}", "b".repeat(64)),
            reason: "explicit current operator request".into(),
            retry_delay_millis: 0,
        };
        assert_eq!(
            backend
                .execute_state(context("alice"), request.into())
                .await
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
    }
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    drop(backend);
    fixture.finish().await;
}

#[tokio::test]
async fn installed_dispatcher_only_backend_cannot_resolve_application_namespace_selectors() {
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
    dispatcher
        .bind_native_capacity(&fixture.admission.native)
        .unwrap();
    let backend = StateManagementBackend::with_installed_dispatcher(
        services(&fixture),
        vec![],
        dispatcher.management_port(),
    )
    .unwrap()
    .with_recovery_bindings(vec![])
    .unwrap();
    tokio::time::timeout_at(deadline().into(), async {
        while fixture.store.snapshot().unwrap().accepted != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();

    assert_eq!(
        backend
            .execute_state(context("alice"), fixture.target().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied,
    );
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    drop(backend);
    assert!(dispatcher.shutdown(deadline()).await.unwrap().clean);
    fixture.finish().await;
}

#[tokio::test]
async fn installed_named_recovery_scopes_require_current_subject_delegation_and_scope_policy() {
    use latent_capabilities::namespace::RecoverySelection;
    use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
    let mut fixture = Fixture::new(false).await;
    let backend = StateManagementBackend::new(services(&fixture), bindings(&fixture))
        .unwrap()
        .with_recovery_bindings(vec![
            StateManagementRecoveryBinding {
                selector: "readers".into(),
                selection: RecoverySelection::Shared {
                    name: "order-readers".into(),
                },
            },
            StateManagementRecoveryBinding {
                selector: "delegation".into(),
                selection: RecoverySelection::Delegated {
                    delegation: "approved-42".into(),
                    service: "orders-worker".into(),
                },
            },
            StateManagementRecoveryBinding {
                selector: "service".into(),
                selection: RecoverySelection::ServiceIntegration,
            },
        ])
        .unwrap();
    let admin = context("alice");
    assert!(recovery_bindings::scope(&backend.0, &admin, Some("service")).is_err());
    let delegated = recovery_bindings::scope(&backend.0, &admin, Some("delegation")).unwrap();
    assert_eq!(
        delegated.kind,
        latent_policy::capability::RecoveryScopeKind::Delegated
    );
    let shared = recovery_bindings::scope(&backend.0, &admin, Some("readers")).unwrap();
    assert_eq!(
        shared.kind,
        latent_policy::capability::RecoveryScopeKind::Shared
    );
    // The installed table is only descriptive. The actual current policy has
    // original-caller scopes and cannot authorize this selected shared tuple.
    let deadline = deadline();
    let namespace = authorization::authorize(
        &backend.0.services,
        &backend.0.bindings[0],
        &admin,
        &fixture.target().into(),
        deadline,
    )
    .await
    .unwrap();
    let original = authorization::EffectDecision {
        services: &backend.0.services,
        binding: &namespace.binding,
        context: &admin,
        caller: &shared,
        entity: None,
        deadline,
        input_bytes: 0,
    };
    assert_eq!(
        original.seal("inspect-effect").err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let bob = context("bob");
    let bob_shared = recovery_bindings::scope(&backend.0, &bob, Some("readers")).unwrap();
    assert_eq!(shared.scope, bob_shared.scope);
    assert_eq!(
        authorization::EffectDecision {
            services: &backend.0.services,
            binding: &namespace.binding,
            context: &bob,
            caller: &bob_shared,
            entity: None,
            deadline,
            input_bytes: 0,
        }
        .seal("inspect-effect")
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    let foreign = AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: "alice".into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("foreign".into())),
        service: None,
        claims: Metadata::new(),
    });
    let foreign_shared = recovery_bindings::scope(&backend.0, &foreign, Some("readers")).unwrap();
    assert_ne!(shared.scope, foreign_shared.scope);
    assert_eq!(
        authorization::EffectDecision {
            services: &backend.0.services,
            binding: &namespace.binding,
            context: &foreign,
            caller: &foreign_shared,
            entity: None,
            deadline,
            input_bytes: 0,
        }
        .seal("inspect-effect")
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    let scope_row = |caller: &latent_capabilities::namespace::CallerScope, kind: &str| {
        serde_json::json!({
            "namespace":"orders", "incarnation":1, "entity":null,
            "recoveryKind":kind, "recoveryScope":caller.scope, "resultPolicy":"visibility-v1",
        })
    };
    let mut approved = fixture.document.clone();
    let scopes = approved["rules"][0]["resources"]["scopes"]
        .as_array_mut()
        .unwrap();
    scopes.push(scope_row(&shared, "shared"));
    scopes.push(scope_row(&delegated, "delegated"));
    fixture.update(Some(&approved), "approve-named-recovery-policy");
    let retained_shared = original.seal("inspect-effect").unwrap();
    let delegated_decision = authorization::EffectDecision {
        services: &backend.0.services,
        binding: &namespace.binding,
        context: &admin,
        caller: &delegated,
        entity: None,
        deadline,
        input_bytes: 0,
    }
    .seal("inspect-effect")
    .unwrap();
    assert!(backend
        .0
        .services
        .policy
        .with_retained_decision(&retained_shared, &mut |_, _| Ok(()))
        .is_ok());
    assert!(backend
        .0
        .services
        .policy
        .with_retained_decision(&delegated_decision, &mut |_, _| Ok(()))
        .is_ok());
    // Sharing the descriptive digest does not share Alice's current permission.
    assert_eq!(
        authorization::EffectDecision {
            services: &backend.0.services,
            binding: &namespace.binding,
            context: &bob,
            caller: &bob_shared,
            entity: None,
            deadline,
            input_bytes: 0,
        }
        .seal("inspect-effect")
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    let replaced = latent_capabilities::namespace::CallerScope::derive(
        admin.principal(),
        &RecoverySelection::Delegated {
            delegation: "approved-42".into(),
            service: "other-worker".into(),
        },
    )
    .unwrap();
    assert_ne!(replaced.scope, delegated.scope);
    assert_eq!(
        authorization::EffectDecision {
            services: &backend.0.services,
            binding: &namespace.binding,
            context: &admin,
            caller: &replaced,
            entity: None,
            deadline,
            input_bytes: 0,
        }
        .seal("inspect-effect")
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    let withdrawn = fixture.document.clone();
    fixture.update(Some(&withdrawn), "withdraw-named-recovery-policy");
    assert!(backend
        .0
        .services
        .policy
        .with_retained_decision(&retained_shared, &mut |_, _| Ok(()))
        .is_err());
    assert!(backend
        .0
        .services
        .policy
        .with_retained_decision(&delegated_decision, &mut |_, _| Ok(()))
        .is_err());
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 0);
    drop(original);
    drop(namespace);
    drop(backend);
    fixture.finish().await;
}
