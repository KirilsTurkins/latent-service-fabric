use super::*;
mod fixture;
mod provider;
use fixture::{mutation, operator, setup};

fn planned(value: &OwnedPhase4Response) -> c::EffectManagementPlan {
    let contract::Response::PlanEffectMutation(value) = &value.response else {
        panic!("expected plan");
    };
    assert_eq!(
        value.audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
    );
    value.plan.clone().unwrap()
}
fn applied(value: &OwnedPhase4Response) -> &c::MutateStateResponse {
    let contract::Response::MutateState(value) = &value.response else {
        panic!("expected mutation receipt");
    };
    value
}

#[tokio::test]
async fn authenticated_effect_terminal_plan_and_expired_original_receipt_preserve_separate_facts() {
    let mut effect = setup().await;
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            effect.request("terminal-original").into(),
        )
        .await
        .unwrap();
    let plan = planned(&response);
    assert_eq!(
        plan.before,
        latent_rpc::transaction::v1::EffectDisposition::Pending as i32
    );
    assert_eq!(plan.owner_epoch, 0);
    assert_eq!(plan.dispatch_attempt, 0);
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            mutation(&effect.fixture, plan.clone()).into(),
        )
        .await
        .unwrap();
    let receipt = applied(&response).receipt.as_ref().unwrap().clone();
    assert!(!applied(&response).replayed);
    assert_eq!(
        receipt.effect.as_ref().unwrap().fact,
        c::EffectManagementFact::AdministratorTerminated as i32
    );
    assert_eq!(
        receipt.effect.as_ref().unwrap().after,
        latent_rpc::transaction::v1::EffectDisposition::AdministrativelyTerminated as i32
    );
    assert!(receipt.effect.as_ref().unwrap().provider_receipt.is_none());
    drop(response);
    // Native time expires the plan. The current read grant has a separate
    // original finite request deadline and never reissues old execution.
    effect.time.store(
        plan.expires_at_unix_millis + 1,
        std::sync::atomic::Ordering::SeqCst,
    );
    let mut current_read = effect.fixture.document.clone();
    current_read["rules"][0]["operations"] =
        serde_json::json!(["namespace-inspect", "inspect-effect"]);
    effect
        .fixture
        .update(Some(&current_read), "retain-read-without-action");
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            mutation(&effect.fixture, plan.clone()).into(),
        )
        .await
        .unwrap();
    assert!(applied(&response).replayed);
    assert_eq!(applied(&response).receipt.as_ref(), Some(&receipt));
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            c::GetStateOperationReceiptRequest {
                namespace: Some(effect.fixture.target()),
                operation_id: "terminal-original".into(),
                original_effect_plan: Some(plan),
            }
            .into(),
        )
        .await
        .unwrap();
    let contract::Response::GetStateOperationReceipt(value) = &response.response else {
        panic!("expected historical receipt");
    };
    assert_eq!(value.receipt.as_ref(), Some(&receipt));
    assert!(value.namespace_receipt.is_none());
    drop(response);
    effect.finish().await;
}

#[tokio::test]
async fn frozen_rpc_adapter_preserves_effect_plan_receipt_and_original_recovery_association() {
    let mut effect = setup().await;
    let adapter = super::super::super::Phase4ServiceAdapter::with_services(
        Arc::new(effect.fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        super::super::super::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let response = adapter
        .plan_effect_mutation(operator("alice").request(effect.request("rpc-original-effect")))
        .await
        .unwrap();
    let plan = response.get_ref().plan.clone().unwrap();
    drop(response);
    let response = adapter
        .mutate_state(operator("alice").request(mutation(&effect.fixture, plan.clone())))
        .await
        .unwrap();
    let receipt = response.get_ref().receipt.clone().unwrap();
    assert_eq!(
        response.get_ref().audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
    );
    drop(response);
    let response = adapter
        .get_state_operation_receipt(operator("alice").request(
            c::GetStateOperationReceiptRequest {
                namespace: Some(effect.fixture.target()),
                operation_id: "rpc-original-effect".into(),
                original_effect_plan: Some(plan),
            },
        ))
        .await
        .unwrap();
    assert_eq!(response.get_ref().receipt.as_ref(), Some(&receipt));
    drop(response);
    drop(adapter);
    effect.finish().await;
}

#[tokio::test]
async fn unknown_actual_dispatch_attempt_cannot_be_redriven_from_an_operator_declaration() {
    let mut effect =
        fixture::setup_with_provider(Some(latent_effects::dispatch::Disposition::Uncertain)).await;
    effect.settle_original().await;
    let mut request = effect.request("unsafe-unknown-redrive");
    request.mutation = c::StateMutationKind::RetryKnownFailedEffect as i32;
    request.retry_delay_millis = 1;
    let error = effect
        .fixture
        .backend
        .execute_state(operator("alice"), request.into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(
        effect.disposition().await,
        latent_effects::dispatch::Disposition::Uncertain
    );
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .sends
            .load(std::sync::atomic::Ordering::SeqCst),
        1
    );
    effect.finish().await;
}

#[tokio::test]
async fn fresh_lookup_after_execution_expiry_uses_reserved_capacity_and_preserves_provider_fact() {
    use latent_core::native_capacity::{NativeAdmissionClass, NativeReservationRequest};
    use std::sync::atomic::Ordering;
    let mut effect =
        fixture::setup_with_provider(Some(latent_effects::dispatch::Disposition::Uncertain)).await;
    effect.settle_original().await;
    // The old execution expired. Fresh management lookup never authorizes a send.
    effect.time.store(70_000, Ordering::SeqCst);
    let mut ordinary = Vec::new();
    for _ in 0..1024 {
        match effect.fixture.admission.native.reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 1,
                work_bytes: 1,
                response_bytes: 1,
            },
            deadline(),
        ) {
            Ok(permit) => ordinary.push(permit),
            Err(_) => break,
        }
    }
    assert!(!ordinary.is_empty());
    assert!(effect
        .fixture
        .admission
        .native
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 1,
                work_bytes: 1,
                response_bytes: 1
            },
            deadline()
        )
        .is_err());
    let mut request = effect.request("fresh-provider-confirmation");
    request.mutation = c::StateMutationKind::ReconcileEffect as i32;
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), request.into())
        .await
        .unwrap();
    let plan = planned(&response);
    assert_eq!(plan.dispatch_attempt, 1);
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), mutation(&effect.fixture, plan).into())
        .await
        .unwrap();
    let receipt = applied(&response).receipt.as_ref().unwrap();
    let fact = receipt.effect.as_ref().unwrap();
    assert_eq!(fact.fact, c::EffectManagementFact::ProviderConfirmed as i32);
    assert_eq!(
        fact.provider_receipt.as_deref(),
        Some("controlled-positive-provider-receipt")
    );
    assert_eq!(fact.provider_observed_at_unix_millis, Some(70_000));
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .sends
            .load(Ordering::SeqCst),
        1
    );
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .lookups
            .load(Ordering::SeqCst),
        1
    );
    drop(response);
    drop(ordinary);
    effect.finish().await;
}

#[tokio::test]
async fn detached_revoked_lookup_keeps_original_native_owner_until_actual_provider_cleanup() {
    use std::sync::atomic::Ordering;
    let mut effect =
        fixture::setup_with_provider(Some(latent_effects::dispatch::Disposition::Uncertain)).await;
    effect.settle_original().await;
    let provider = Arc::clone(effect.provider.as_ref().unwrap());
    provider.hold.store(true, Ordering::SeqCst);
    let mut request = effect.request("held-current-lookup");
    request.mutation = c::StateMutationKind::ReconcileEffect as i32;
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), request.into())
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let backend = effect.fixture.backend.clone();
    let request = mutation(&effect.fixture, plan);
    let waiter = tokio::spawn(async move {
        backend
            .execute_state(operator("alice"), request.into())
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), provider.entered.notified())
        .await
        .unwrap();
    assert_eq!(
        effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .slots,
        1
    );
    assert_eq!(effect.dispatcher.snapshot().unwrap().physical_owners, 1);
    waiter.abort();
    assert!(waiter.await.err().unwrap().is_cancelled());
    let mut withdrawn = effect.fixture.document.clone();
    withdrawn["rules"][0]["operations"] = serde_json::json!(["namespace-inspect"]);
    effect
        .fixture
        .update(Some(&withdrawn), "withdraw-held-lookup");
    assert_eq!(
        effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .slots,
        1
    );
    provider.release.notify_one();
    tokio::time::timeout(Duration::from_secs(5), async {
        while effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .slots
            != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        effect.disposition().await,
        latent_effects::dispatch::Disposition::Uncertain
    );
    assert_eq!(effect.dispatcher.snapshot().unwrap().physical_owners, 0);
    assert_eq!(provider.sends.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
    effect.finish().await;
}

#[tokio::test]
async fn absent_provider_status_preserves_uncertainty_original_plan_and_independent_audit() {
    use std::sync::atomic::Ordering;
    let mut effect =
        fixture::setup_with_provider(Some(latent_effects::dispatch::Disposition::Uncertain)).await;
    effect.settle_original().await;
    effect
        .provider
        .as_ref()
        .unwrap()
        .positive
        .store(false, Ordering::SeqCst);
    let mut request = effect.request("absent-original-status");
    request.mutation = c::StateMutationKind::ReconcileEffect as i32;
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), request.clone().into())
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let error = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            mutation(&effect.fixture, plan.clone()).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(
        effect.disposition().await,
        latent_effects::dispatch::Disposition::Uncertain
    );
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), request.into())
        .await
        .unwrap();
    assert_eq!(planned(&response), plan);
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            c::GetStateOperationReceiptRequest {
                namespace: Some(effect.fixture.target()),
                operation_id: "absent-original-status".into(),
                original_effect_plan: Some(plan),
            }
            .into(),
        )
        .await
        .unwrap();
    let contract::Response::GetStateOperationReceipt(value) = &response.response else {
        panic!("expected independent receipt inspection");
    };
    assert!(value.receipt.is_none());
    assert_eq!(
        value.audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
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
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .lookups
            .load(Ordering::SeqCst),
        1
    );
    drop(response);
    effect.finish().await;
}

#[tokio::test]
async fn effect_identifiers_and_operator_flag_cannot_replace_exact_caller_data_read_permission() {
    let mut effect = setup().await;
    let error = effect
        .fixture
        .backend
        .execute_state(context("alice"), effect.request("no-operator").into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    let error = effect
        .fixture
        .backend
        .execute_state(operator("bob"), effect.request("other-caller").into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    let mut document = effect.fixture.document.clone();
    document["rules"][0]["operations"] = serde_json::json!([
        "namespace-create",
        "namespace-inspect",
        "effect-plan",
        "effect-terminate"
    ]);
    effect
        .fixture
        .update(Some(&document), "withdraw-effect-read");
    let error = effect
        .fixture
        .backend
        .execute_state(operator("alice"), effect.request("missing-read").into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    effect.finish().await;
}

#[tokio::test]
async fn effect_plan_full_original_semantics_and_stale_policy_are_never_refreshed() {
    let mut effect = setup().await;
    let response = effect
        .fixture
        .backend
        .execute_state(operator("alice"), effect.request("exact-plan").into())
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let mut changed = effect.request("exact-plan");
    changed.reason = "different administrator declaration".into();
    let error = effect
        .fixture
        .backend
        .execute_state(operator("alice"), changed.into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::StateConflict);
    let mut changed = plan.clone();
    changed.prepared_at_unix_millis += 1;
    let error = effect
        .fixture
        .backend
        .execute_state(operator("alice"), mutation(&effect.fixture, changed).into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::StateConflict);
    let mut changed = effect.request("stale-policy");
    changed.expected_policy_digest = format!("sha256:{}", "f".repeat(64));
    let error = effect
        .fixture
        .backend
        .execute_state(operator("alice"), changed.into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::StateConflict);
    assert_eq!(
        effect.disposition().await,
        latent_effects::dispatch::Disposition::Pending
    );
    effect.finish().await;
}

#[tokio::test]
async fn accepted_effect_response_rechecks_current_data_read_before_physical_frame_release() {
    let mut effect = setup().await;
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            effect.request("response-currentness").into(),
        )
        .await
        .unwrap();
    let original_slots = effect
        .fixture
        .admission
        .native
        .snapshot()
        .unwrap()
        .recovery
        .slots;
    assert_eq!(original_slots, 1);
    let mut document = effect.fixture.document.clone();
    document["rules"][0]["operations"] = serde_json::json!(["namespace-inspect"]);
    effect
        .fixture
        .update(Some(&document), "revoke-before-effect-frame");
    let mut encoded = false;
    let error = response
        .owner
        .with_current(&mut || {
            encoded = true;
        })
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert!(!encoded);
    assert_eq!(
        effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .slots,
        original_slots
    );
    drop(response);
    assert_eq!(
        effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .slots,
        0
    );
    effect.finish().await;
}
