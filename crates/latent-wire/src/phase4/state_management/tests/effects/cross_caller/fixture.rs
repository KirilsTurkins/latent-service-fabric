use super::*;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeReservationRequest,
};

pub(super) fn binding(value: &StateManagementBinding) -> StateManagementBinding {
    StateManagementBinding {
        publication: value.publication.clone(),
        component: value.component.clone(),
        service: value.service.clone(),
        namespace: value.namespace.clone(),
        incarnation: value.incarnation,
        state_schema: value.state_schema.clone(),
        result_policy: value.result_policy.clone(),
        maximum_quota: value.maximum_quota,
        state: latent_node::PolicyCallBinding {
            policies: value.state.policies.clone(),
            binding: value.state.binding.clone(),
            profile: value.state.profile.clone(),
            configuration_digest: value.state.configuration_digest.clone(),
            configuration_epoch: value.state.configuration_epoch,
            operations: value.state.operations.clone(),
            deployment: serde_json::from_value(
                serde_json::to_value(&value.state.deployment).unwrap(),
            )
            .unwrap(),
            provider_configuration: serde_json::from_value(
                serde_json::to_value(&value.state.provider_configuration).unwrap(),
            )
            .unwrap(),
        },
    }
}

pub(super) fn captured(effect: &mut FixtureEffect) {
    let old = &effect.fixture.backend.0;
    // The fixed metadata slice is prepaid before either clone/vector allocates.
    let original = effect
        .fixture
        .admission
        .native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 64 * 1024,
                ..NativeReservationRequest::default()
            },
            deadline(),
        )
        .unwrap();
    let memory = Arc::new(
        original
            .reserve_buffer(NativeBufferClass::Work, 64 * 1024)
            .unwrap(),
    );
    let services = services(effect);
    let bindings = old.bindings.iter().map(|entry| binding(entry)).collect();
    assert!(
        StateManagementBackend::captured_effect_binding_peak_bytes(&bindings).unwrap()
            <= memory.bytes()
    );
    effect.fixture.backend = StateManagementBackend::new_with_captured_effect_recovery(
        services,
        bindings,
        &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
        vec![memory],
        0,
    )
    .unwrap()
    .with_dispatcher(effect.dispatcher.management_port())
    .unwrap()
    .with_command_recovery(effect.dispatcher.command_admission_source())
    .unwrap();
    drop(original);
}

pub(super) fn services(effect: &FixtureEffect) -> StateManagementServices {
    let old = &effect.fixture.backend.0;
    StateManagementServices {
        store: Arc::clone(&old.services.store),
        namespaces: Arc::clone(&old.services.namespaces),
        policy: Arc::clone(&old.services.policy),
        artifacts: Arc::clone(&old.services.artifacts),
        authorization: Arc::clone(&old.services.authorization),
        admission: Arc::clone(&old.services.admission),
        maintenance: Arc::clone(&old.services.maintenance),
        maintenance_clock: Arc::clone(&old.services.maintenance_clock),
        clock: Arc::clone(&old.services.clock),
        audit: old.services.audit.clone(),
    }
}

pub(super) async fn grant(effect: &mut FixtureEffect, operations: &[&str]) {
    let mut document = effect.fixture.document.clone();
    let mut rule = document["rules"][1].clone();
    rule["id"] = "bob-original-alice-effect".into();
    rule["operations"] = serde_json::json!(operations);
    rule["resources"]["scopes"][0]["recoveryScope"] =
        latent_capabilities::namespace::CallerScope::derive(
            super::super::fixture::reader("alice").principal(),
            &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
        )
        .unwrap()
        .scope
        .into();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "bob-original-alice-effect");
    document["rules"].as_array_mut().unwrap().push(rule);
    let operation = format!(
        "exact-original-effect-purpose-{}",
        effect.fixture.policy_revision
    );
    effect.fixture.update(Some(&document), &operation);
    effect.fixture.document = document;
    let response = effect
        .fixture
        .backend
        .execute_state(context("bob"), effect.fixture.target().into())
        .await
        .unwrap();
    let contract::Response::InspectNamespace(value) = &response.response else {
        panic!("actual namespace inspection");
    };
    effect
        .policy_digest
        .clone_from(&value.namespace.as_ref().unwrap().namespace_policy_digest);
    drop(response);
}

pub(super) async fn setup(tagged: bool) -> FixtureEffect {
    let mut effect =
        super::super::fixture::setup_with_recovery_provider(Disposition::Uncertain).await;
    effect.settle_original().await;
    if tagged {
        captured(&mut effect);
    }
    grant(
        &mut effect,
        &["inspect-effect", "effect-plan", "effect-reconcile"],
    )
    .await;
    effect
}

pub(super) fn request(effect: &FixtureEffect, operation: &str) -> c::PlanEffectMutationRequest {
    let mut request = effect.request(operation);
    request.mutation = c::StateMutationKind::ReconcileEffect as i32;
    request.reason = "lookup the retained original provider receipt".into();
    request
}

pub(super) async fn assert_refused(
    effect: &mut FixtureEffect,
    request: c::PlanEffectMutationRequest,
    actor: AuthenticatedInvocationContext,
    expected: PlatformErrorCode,
) {
    let rows = effect.rows().await;
    let error = effect
        .fixture
        .backend
        .execute_state(actor, request.into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, expected);
    assert_eq!(effect.rows().await, rows);
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .lookups
            .load(Ordering::SeqCst),
        0
    );
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .sends
            .load(Ordering::SeqCst),
        1
    );
}
