use super::*;
use latent_activation::{ActivationRequest, ActivationRequestBuilder, ActivationRequestLimits};
use latent_core::{
    native_capacity::{NativeAdmissionClass, NativeCapacityError, NativeReservationRequest},
    ActivationBudget, EffectiveActivationBudget, ResourceBudget,
};
use latent_node::transaction_runtime::CommandTimeSource;

fn original_request(
    clock: &dyn latent_core::ActivationClock,
) -> (latent_activation::ActivationEnvelope, ActivationBudget) {
    let sample = clock.sample();
    let requested = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(5_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let budget = ActivationBudget::with_profile(
        EffectiveActivationBudget::admit_at(&requested, &requested, &requested, None, sample)
            .unwrap(),
        latent_core::BudgetProfile::Phase4,
    )
    .unwrap();
    let builder = ActivationRequestBuilder::with_profile(
        ActivationRequestLimits::default(),
        Arc::new(latent_activation::SystemActivationIdSource::default()),
        latent_core::BudgetProfile::Phase4,
    )
    .unwrap();
    let envelope = builder
        .build(ActivationRequest {
            activation_id: Some(latent_core::ActivationId("original-result-capacity".into())),
            principal: latent_core::InvocationPrincipal {
                subject: "alice".into(),
                kind: latent_core::PrincipalKind::User,
                tenant: Some(TenantId("alpha".into())),
                service: None,
                claims: latent_core::Metadata::new(),
            },
            target: latent_routing::InvocationTarget {
                tenant: TenantId("alpha".into()),
                service: latent_core::ServiceId("alpha/aggregate".into()),
                contract: latent_core::ContractId("alpha:aggregate/api@1.0.0".into()),
                function: latent_core::FunctionId("update".into()),
                route: None,
            },
            budget: requested,
            input_media_type: "application/vnd.latent.wit-values.v1+json".into(),
            parent_activation_id: None,
            root_activation_id: None,
            deadline_unix_millis: None,
            priority: 0,
            trace: latent_activation::TraceContext {
                trace_id: latent_core::TraceId("result-capacity-trace".into()),
                span_id: latent_core::SpanId("result-capacity-span".into()),
                trace_flags: 0,
                baggage: latent_core::Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            metadata: latent_core::Metadata::new(),
            input: Vec::new(),
        })
        .unwrap();
    (envelope, budget)
}

#[tokio::test]
async fn original_result_admission_retains_reserved_capacity_under_ordinary_pressure() {
    let fixture = Fixture::new();
    let (state, mut effects) = fixture.open().await;
    let (envelope, budget) = original_request(fixture.clock.as_ref());
    let deadline = budget.deadline().monotonic().unwrap();
    let mut ordinary = Vec::new();
    let mut refused = false;
    for _ in 0..=1024 {
        match state.0.native.reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest::default(),
            deadline,
        ) {
            Ok(reservation) => ordinary.push(reservation),
            Err(NativeCapacityError::SlotsFull) => {
                refused = true;
                break;
            }
            Err(error) => panic!("ordinary saturation must hit its original slot limit: {error:?}"),
        }
    }
    assert!(refused && !ordinary.is_empty());
    let before = state.0.native.snapshot().unwrap();
    let source = effects.command_admission_source();
    let denied = AdmissionTime::new(source.clone(), state.0.native.clone());
    assert!(denied.retain_admission(&envelope, &budget).is_err());
    assert_eq!(state.0.native.snapshot().unwrap(), before);
    let recovery = AdmissionTime::recovery(source, state.0.native.clone());
    recovery.retain_admission(&envelope, &budget).unwrap();
    let admitted = state.0.native.snapshot().unwrap();
    assert_eq!(admitted.ordinary, before.ordinary);
    assert_eq!(admitted.recovery.slots, before.recovery.slots + 1);
    assert!(recovery.reserved_response_bytes() > 0);
    let frame_owner = Arc::clone(&recovery);
    drop(recovery);
    assert_eq!(state.0.native.snapshot().unwrap(), admitted);
    let mut deliveries = 0;
    frame_owner
        .with_delivery(&mut || {
            deliveries += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(deliveries, 1);
    drop(frame_owner);
    assert_eq!(state.0.native.snapshot().unwrap(), before);
    drop(ordinary);
    assert!(state.0.native.snapshot().unwrap().physically_retired());
    assert!(state.0.installed.is_empty());
    finish(&state, &mut effects).await;
}
