use super::fixture::FixtureEffect;
use super::*;
use latent_effects::dispatch::Disposition;
use std::sync::atomic::Ordering;
mod fixture;
mod memory;

#[tokio::test]
async fn actual_user_original_effect_current_admin_plan_lookup_and_receipt_preserve_original_actor()
{
    let mut effect = fixture::setup(true).await;
    let result = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "admin-original-reconcile").into(),
        )
        .await;
    let mut accepted = false;
    if let Ok(response) = result {
        let plan = planned(&response);
        assert_eq!(
            plan.safety,
            c::EffectPlanSafety::ProviderReceiptLookup as i32
        );
        assert_eq!(plan.dispatch_attempt, 1);
        drop(response);
        let response = effect
            .fixture
            .backend
            .execute_state(
                operator("bob"),
                mutation(&effect.fixture, plan.clone()).into(),
            )
            .await
            .unwrap();
        let receipt = applied(&response).receipt.clone().unwrap();
        assert_eq!(
            receipt.effect.as_ref().unwrap().fact,
            c::EffectManagementFact::ProviderConfirmed as i32
        );
        let actor = latent_capabilities::namespace::CallerScope::derive(
            operator("bob").principal(),
            &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
        )
        .unwrap();
        assert_eq!(
            receipt.authenticated_operator,
            format!("administrator:{}", actor.scope)
        );
        drop(response);
        let response = effect
            .fixture
            .backend
            .execute_state(
                operator("bob"),
                c::GetStateOperationReceiptRequest {
                    namespace: Some(effect.fixture.target()),
                    operation_id: "admin-original-reconcile".into(),
                    original_effect_plan: Some(plan),
                }
                .into(),
            )
            .await
            .unwrap();
        let contract::Response::GetStateOperationReceipt(value) = &response.response else {
            panic!("receipt lookup");
        };
        assert_eq!(value.receipt.as_ref(), Some(&receipt));
        assert_eq!(
            value.audit_ack.as_ref().unwrap().status,
            c::AuditAckStatus::Durable as i32
        );
        drop(response);
        assert_eq!(
            effect.disposition().await,
            Disposition::ProviderAcknowledged
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
        accepted = true;
    }
    effect.finish().await;
    assert!(accepted, "actual current administrator must reconcile only its explicitly authorized original data target");
}

#[tokio::test]
async fn untagged_original_and_other_caller_own_grants_cannot_select_foreign_effect_data() {
    let mut effect = fixture::setup(false).await;
    let request = fixture::request(&effect, "untagged-source");
    fixture::assert_refused(
        &mut effect,
        request,
        operator("bob"),
        PlatformErrorCode::NotFound,
    )
    .await;
    effect.finish().await;
}

#[tokio::test]
async fn missing_original_target_read_plan_and_reconcile_each_preserve_original_uncertainty() {
    for (operations, expected) in [
        (
            vec!["effect-plan", "effect-reconcile"],
            PlatformErrorCode::NotFound,
        ),
        (
            vec!["inspect-effect", "effect-reconcile"],
            PlatformErrorCode::PermissionDenied,
        ),
        (
            vec!["inspect-effect", "effect-plan"],
            PlatformErrorCode::PermissionDenied,
        ),
    ] {
        let mut effect = fixture::setup(true).await;
        fixture::grant(&mut effect, &operations).await;
        let request = fixture::request(&effect, "missing-original-purpose");
        fixture::assert_refused(&mut effect, request, operator("bob"), expected).await;
        effect.finish().await;
    }
}

#[tokio::test]
async fn original_user_and_untrusted_administrator_remain_denied_before_provider_lookup() {
    let mut effect = fixture::setup(true).await;
    for actor in [super::fixture::reader("alice"), context("bob")] {
        let request = fixture::request(&effect, "real-management-owner-required");
        fixture::assert_refused(
            &mut effect,
            request,
            actor,
            PlatformErrorCode::PermissionDenied,
        )
        .await;
    }
    effect.finish().await;
}

#[tokio::test]
async fn current_target_selector_key_effect_namespace_and_version_cannot_be_retargeted() {
    let mut effect = fixture::setup(true).await;
    let base = fixture::request(&effect, "original-selector");
    let mut changed = base.clone();
    changed
        .effect
        .as_mut()
        .unwrap()
        .command
        .as_mut()
        .unwrap()
        .client_key = "foreign-key".into();
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::NotFound,
    )
    .await;
    let mut changed = base.clone();
    changed
        .effect
        .as_mut()
        .unwrap()
        .command
        .as_mut()
        .unwrap()
        .shared_recovery_scope = Some("not-installed".into());
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::PermissionDenied,
    )
    .await;
    let mut changed = base.clone();
    changed
        .effect
        .as_mut()
        .unwrap()
        .command
        .as_mut()
        .unwrap()
        .namespace
        .as_mut()
        .unwrap()
        .incarnation = "2".into();
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::PermissionDenied,
    )
    .await;
    let mut changed = base.clone();
    changed.expected_version = vec![0; 32];
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::StateConflict,
    )
    .await;
    let mut changed = base.clone();
    changed.effect.as_mut().unwrap().effect_id = "f".repeat(64);
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::NotFound,
    )
    .await;
    let mut changed = base;
    changed.expected_policy_digest = format!("sha256:{}", "f".repeat(64));
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::StateConflict,
    )
    .await;
    effect.finish().await;
}

#[tokio::test]
async fn current_original_target_lookup_keeps_reserved_capacity_under_ordinary_saturation() {
    use latent_core::native_capacity::{NativeAdmissionClass, NativeReservationRequest};
    let mut effect = fixture::setup(true).await;
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
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "reserved-original-target").into(),
        )
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(operator("bob"), mutation(&effect.fixture, plan).into())
        .await
        .unwrap();
    assert_eq!(
        applied(&response)
            .receipt
            .as_ref()
            .unwrap()
            .effect
            .as_ref()
            .unwrap()
            .fact,
        c::EffectManagementFact::ProviderConfirmed as i32
    );
    drop(response);
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
    drop(ordinary);
    effect.finish().await;
}

#[tokio::test]
async fn withdrawal_of_original_target_read_is_checked_at_physical_result_release() {
    let mut effect = fixture::setup(true).await;
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "original-release").into(),
        )
        .await
        .unwrap();
    let mut document = effect.fixture.document.clone();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "bob-original-alice-effect");
    effect
        .fixture
        .update(Some(&document), "withdraw-original-target");
    let mut published = false;
    assert_eq!(
        response
            .owner
            .with_current(&mut || published = true)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!published);
    drop(response);
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .lookups
            .load(Ordering::SeqCst),
        0
    );
    effect.finish().await;
}

#[tokio::test]
async fn absent_actual_provider_fact_does_not_upgrade_cross_caller_plan_to_acknowledgement() {
    let mut effect = fixture::setup(true).await;
    effect
        .provider
        .as_ref()
        .unwrap()
        .positive
        .store(false, Ordering::SeqCst);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "original-absent").into(),
        )
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let error = effect
        .fixture
        .backend
        .execute_state(operator("bob"), mutation(&effect.fixture, plan).into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(effect.disposition().await, Disposition::Uncertain);
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
    effect.finish().await;
}

#[tokio::test]
async fn missing_or_shared_captured_mode_cannot_be_inferred_from_absent_selector() {
    for mode in [
        None,
        Some(latent_policy::capability::RecoveryScopeKind::Shared),
    ] {
        let mut effect = fixture::setup(true).await;
        Arc::get_mut(&mut effect.fixture.backend.0)
            .unwrap()
            .bindings[0]
            .recovery = mode;
        let request = fixture::request(&effect, "exact-original-source-kind");
        fixture::assert_refused(
            &mut effect,
            request,
            operator("bob"),
            PlatformErrorCode::NotFound,
        )
        .await;
        effect.finish().await;
    }
}

#[tokio::test]
async fn captured_target_rejects_foreign_publication_tenant_profile_and_effect() {
    let mut effect = fixture::setup(true).await;
    let base = fixture::request(&effect, "exact-original-source-selector");
    let mut changed = base.clone();
    changed
        .effect
        .as_mut()
        .unwrap()
        .authorization_publication
        .as_mut()
        .unwrap()
        .id = format!("publication:sha256:{}", "f".repeat(64));
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::PermissionDenied,
    )
    .await;
    let mut changed = base.clone();
    changed
        .effect
        .as_mut()
        .unwrap()
        .command
        .as_mut()
        .unwrap()
        .namespace
        .as_mut()
        .unwrap()
        .tenant = "foreign".into();
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::PermissionDenied,
    )
    .await;
    let mut changed = base.clone();
    changed.effect.as_mut().unwrap().profile = None;
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::InvalidArgument,
    )
    .await;
    let mut changed = base;
    changed.effect.as_mut().unwrap().effect_id = "f".repeat(64);
    fixture::assert_refused(
        &mut effect,
        changed,
        operator("bob"),
        PlatformErrorCode::NotFound,
    )
    .await;
    effect.finish().await;
}

#[tokio::test]
async fn captured_original_source_component_schema_and_publication_cannot_be_substituted() {
    for substitute in 0..3 {
        let mut effect = fixture::setup(true).await;
        let captured = &mut Arc::get_mut(&mut effect.fixture.backend.0)
            .unwrap()
            .bindings[0];
        let binding = Arc::get_mut(&mut captured.binding).unwrap();
        match substitute {
            0 => binding.component.0 = format!("sha256:{}", "f".repeat(64)),
            1 => binding.state_schema = format!("sha256:{}", "f".repeat(64)),
            _ => {
                binding.publication.id = format!("publication:sha256:{}", "f".repeat(64))
                    .parse()
                    .unwrap()
            }
        }
        let request = fixture::request(&effect, "exact-original-source-capture");
        fixture::assert_refused(
            &mut effect,
            request,
            operator("bob"),
            PlatformErrorCode::PermissionDenied,
        )
        .await;
        effect.finish().await;
    }
}

#[tokio::test]
async fn cross_caller_expired_original_transport_and_plan_cannot_refresh_authority() {
    let mut effect = fixture::setup(true).await;
    let actor =
        operator("bob").with_transport_deadline_at(1, Instant::now() - Duration::from_secs(1));
    let request = fixture::request(&effect, "expired-original-transport");
    fixture::assert_refused(
        &mut effect,
        request,
        actor,
        PlatformErrorCode::DeadlineExceeded,
    )
    .await;
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "expired-plan").into(),
        )
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    effect
        .time
        .store(plan.expires_at_unix_millis + 1, Ordering::SeqCst);
    let error = effect
        .fixture
        .backend
        .execute_state(operator("bob"), mutation(&effect.fixture, plan).into())
        .await
        .err()
        .unwrap();
    assert!(matches!(
        error.code,
        PlatformErrorCode::DeadlineExceeded | PlatformErrorCode::StateConflict
    ));
    assert_eq!(effect.disposition().await, Disposition::Uncertain);
    assert_eq!(
        effect
            .provider
            .as_ref()
            .unwrap()
            .lookups
            .load(Ordering::SeqCst),
        0
    );
    effect.finish().await;
}

#[tokio::test]
async fn detached_cross_caller_lookup_retains_native_owner_until_real_provider_cleanup() {
    let mut effect = fixture::setup(true).await;
    let provider = Arc::clone(effect.provider.as_ref().unwrap());
    provider.hold.store(true, Ordering::SeqCst);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("bob"),
            fixture::request(&effect, "held-original-lookup").into(),
        )
        .await
        .unwrap();
    let plan = planned(&response);
    drop(response);
    let backend = effect.fixture.backend.clone();
    let request = mutation(&effect.fixture, plan);
    let waiter =
        tokio::spawn(async move { backend.execute_state(operator("bob"), request.into()).await });
    tokio::time::timeout(Duration::from_secs(5), provider.entered.notified())
        .await
        .unwrap();
    let held = effect.dispatcher.snapshot().unwrap();
    assert!(held.physical_owners > 0);
    let mut document = effect.fixture.document.clone();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "bob-original-alice-effect");
    effect
        .fixture
        .update(Some(&document), "withdraw-held-original-target");
    waiter.abort();
    assert!(matches!(waiter.await, Err(error) if error.is_cancelled()));
    assert!(effect.dispatcher.snapshot().unwrap().physical_owners > 0);
    provider.hold.store(false, Ordering::SeqCst);
    provider.release.notify_one();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let snapshot = effect.dispatcher.snapshot().unwrap();
            if snapshot.physical_owners == 0 && snapshot.active_jobs == 0 {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(effect.disposition().await, Disposition::Uncertain);
    assert_eq!(provider.sends.load(Ordering::SeqCst), 1);
    effect.finish().await;
}
