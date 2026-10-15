use super::fixture::{
    reader, setup_with_maximum_recovery, setup_with_recovery, setup_with_recovery_provider,
    FixtureEffect,
};
use super::*;
use latent_core::native_capacity::{NativeAdmissionClass, NativeReservationRequest};
use latent_rpc::transaction::v1::{self as t, transaction_service_server::TransactionService};

fn request(effect: &FixtureEffect) -> t::GetEffectRequest {
    t::GetEffectRequest {
        profile: Some(contract::current_profile()),
        command: Some(effect.command.clone()),
        effect_id: effect.effect.clone(),
        authorization_publication: effect.fixture.target().authorization_publication,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_effect_rpc_read_uses_current_user_policy_and_recovery_owners() {
    let mut effect = setup_with_recovery().await;
    let before = effect.rows().await;
    let native = &effect.fixture.admission.native;
    let mut ordinary = Vec::new();
    while let Ok(reservation) = native.reserve(
        NativeAdmissionClass::Ordinary,
        NativeReservationRequest::default(),
        deadline(),
    ) {
        ordinary.push(reservation);
    }
    assert!(!ordinary.is_empty());
    let capacity = native.snapshot().unwrap().recovery;
    let adapter = crate::phase4::Phase4ServiceAdapter::with_services(
        Arc::new(effect.fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        crate::phase4::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let response = adapter
        .get_effect(reader("alice").request(request(&effect)))
        .await
        .unwrap();
    let receipt = response.get_ref().effect.as_ref().unwrap();
    assert_eq!(receipt.effect_id, effect.effect);
    let committed = before
        .iter()
        .find_map(|(_, bytes)| latent_commit::atomic::CommandRecord::decode(bytes).ok())
        .unwrap();
    assert_eq!(receipt.command_id, committed.id().hex());
    assert_eq!(receipt.record_version, effect.version);
    assert_eq!(receipt.disposition, t::EffectDisposition::Pending as i32);
    assert_eq!(receipt.command_attempt_id, "1");
    assert_eq!(receipt.dispatch_attempt, 0);
    assert!(receipt.provider_receipt.is_none());
    assert!(receipt.owner_epoch.is_none() && receipt.claim_generation.is_none());
    assert!(native.snapshot().unwrap().recovery.bytes > capacity.bytes);
    assert_eq!(effect.rows().await, before);
    drop(response);
    drop(adapter);
    assert_eq!(native.snapshot().unwrap().recovery, capacity);
    drop(ordinary);
    effect.finish().await;
}

async fn read(effect: &FixtureEffect) -> OwnedPhase4Response {
    effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(effect).into())
        .await
        .unwrap()
}

fn receipt(value: &OwnedPhase4Response) -> &t::EffectReceipt {
    let contract::Response::GetEffect(value) = &value.response else {
        panic!("effect response");
    };
    value.effect.as_ref().unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_refuses_foreign_missing_and_uninstalled_selectors_without_rewriting_rows(
) {
    let mut effect = setup_with_recovery().await;
    let (_, foreign_effect) = effect.related_command().await;
    let before = effect.rows().await;
    for kind in [
        "foreign-effect",
        "missing-effect",
        "missing-command",
        "publication",
        "tenant",
        "namespace",
        "incarnation",
        "shared-scope",
    ] {
        let mut value = request(&effect);
        let selector = value.command.as_mut().unwrap();
        let expected = match kind {
            "foreign-effect" => {
                value.effect_id = foreign_effect.clone();
                PlatformErrorCode::PermissionDenied
            }
            "missing-effect" => {
                value.effect_id = "f".repeat(64);
                PlatformErrorCode::PermissionDenied
            }
            "missing-command" => {
                selector.client_key = "missing-command".into();
                PlatformErrorCode::NotFound
            }
            "publication" => {
                value.authorization_publication.as_mut().unwrap().id =
                    format!("publication:sha256:{}", "6".repeat(64));
                PlatformErrorCode::PermissionDenied
            }
            "tenant" => {
                selector.namespace.as_mut().unwrap().tenant = "foreign".into();
                value.authorization_publication.as_mut().unwrap().tenant = "foreign".into();
                PlatformErrorCode::PermissionDenied
            }
            "namespace" => {
                selector.namespace.as_mut().unwrap().namespace = "other-orders".into();
                PlatformErrorCode::PermissionDenied
            }
            "incarnation" => {
                selector.namespace.as_mut().unwrap().incarnation = "2".into();
                PlatformErrorCode::PermissionDenied
            }
            "shared-scope" => {
                selector.shared_recovery_scope = Some("uninstalled-recovery".into());
                PlatformErrorCode::PermissionDenied
            }
            _ => unreachable!(),
        };
        let failed = effect
            .fixture
            .backend
            .execute_state(reader("alice"), value.into())
            .await
            .err()
            .unwrap();
        assert_eq!(failed.code, expected, "{kind}");
    }
    let failed = effect
        .fixture
        .backend
        .execute_state(reader("bob"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(failed.code, PlatformErrorCode::NotFound);
    assert_eq!(effect.rows().await, before);
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_retains_original_inspect_purpose_and_revoked_frame_cannot_adopt_new_grant(
) {
    let mut effect = setup_with_recovery().await;
    let response = read(&effect).await;
    response.owner.with_current(&mut || {}).unwrap();
    let mut document = effect.fixture.document.clone();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "alice-effect-reader");
    effect
        .fixture
        .update(Some(&document), "revoke-original-effect-read");
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let failed = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(failed.code, PlatformErrorCode::PermissionDenied);
    let original = effect.fixture.document.clone();
    effect
        .fixture
        .update(Some(&original), "fresh-effect-read-grant");
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    drop(read(&effect).await);
    drop(response);
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_after_payload_and_delivery_horizon_keeps_persisted_pending_and_identity_cutoff(
) {
    use std::sync::atomic::Ordering;
    let mut effect = setup_with_recovery().await;
    let response = read(&effect).await;
    let before = effect.rows().await;
    let retention = receipt(&response).retention.as_ref().unwrap();
    let expired_payload = retention.payload_expires_at_unix_millis.unwrap() + 1;
    let identity_cutoff = retention.identity_expires_at_unix_millis.unwrap();
    effect.time.store(expired_payload, Ordering::SeqCst);
    response.owner.with_current(&mut || {}).unwrap();
    let after = read(&effect).await;
    assert_eq!(
        receipt(&after).disposition,
        t::EffectDisposition::Pending as i32
    );
    assert_eq!(receipt(&after).dispatch_attempt, 0);
    assert!(receipt(&after).provider_receipt.is_none());
    assert!(
        receipt(&after)
            .retention
            .as_ref()
            .unwrap()
            .payload_available
    );
    assert_eq!(effect.rows().await, before);
    effect.time.store(identity_cutoff, Ordering::SeqCst);
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(
        after.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    let failed = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(failed.code, PlatformErrorCode::DeadlineExceeded);
    drop(after);
    drop(response);
    effect.finish().await;
}

fn fresh_backend(effect: &FixtureEffect) -> StateManagementBackend {
    let original = &effect.fixture.backend.0;
    let services = &original.services;
    let binding = &original.bindings[0];
    StateManagementBackend::new(
        StateManagementServices {
            store: Arc::clone(&services.store),
            namespaces: Arc::clone(&services.namespaces),
            policy: Arc::clone(&services.policy),
            artifacts: Arc::clone(&services.artifacts),
            authorization: Arc::clone(&services.authorization),
            admission: Arc::clone(&services.admission),
            maintenance: Arc::clone(&services.maintenance),
            maintenance_clock: Arc::clone(&services.maintenance_clock),
            clock: Arc::clone(&services.clock),
            audit: services.audit.clone(),
        },
        vec![super::super::fixture::binding(
            binding.publication.clone(),
            binding.component.clone(),
        )],
    )
    .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_requires_exact_original_store_native_and_recovery_source() {
    let mut effect = setup_with_recovery().await;
    let mut foreign = setup_with_recovery().await;
    assert!(fresh_backend(&effect)
        .with_command_recovery(foreign.dispatcher.command_admission_source())
        .is_err());
    let unbound = fresh_backend(&effect);
    let failed = unbound
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(failed.code, PlatformErrorCode::Unavailable);
    drop(unbound);
    let valid = fresh_backend(&effect)
        .with_command_recovery(effect.dispatcher.command_admission_source())
        .unwrap();
    drop(
        valid
            .execute_state(reader("alice"), request(&effect).into())
            .await
            .unwrap(),
    );
    drop(valid);
    foreign.finish().await;
    effect.finish().await;
}

async fn tamper_row_for_rejection_only(
    effect: &FixtureEffect,
    key: latent_state::embedded::RowKey,
    value: Option<Vec<u8>>,
) {
    effect
        .fixture
        .store
        .with_store(
            latent_state::store_io::StoreIoKind::RecoveryWrite,
            WORK_BYTES as u64,
            move |engine| {
                let view = engine.snapshot()?;
                let old = view.get(&key)?;
                let guard = latent_state::tenant::guard_key();
                let original_guard = view.get(&guard)?;
                // Deliberately damage this isolated fixture's closure while
                // leaving its original tenant guard unchanged. This is not a
                // valid mutation, recovery plan, quota update or usable store.
                engine.apply(latent_state::embedded::AtomicBatch {
                    expectations: vec![
                        latent_state::embedded::ExpectedRow {
                            key: key.clone(),
                            value: old,
                        },
                        latent_state::embedded::ExpectedRow {
                            key: guard.clone(),
                            value: original_guard.clone(),
                        },
                    ],
                    mutations: vec![
                        latent_state::embedded::RowMutation { key, value },
                        latent_state::embedded::RowMutation {
                            key: guard.clone(),
                            value: original_guard.clone(),
                        },
                    ],
                })?;
                if engine.snapshot()?.get(&guard)? != original_guard {
                    return Err(latent_state::embedded::StoreError::Corrupt);
                }
                Ok(())
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

async fn retire_tampered_fixture(effect: &mut FixtureEffect) {
    // This damaged store supplies rejection evidence only, never a clean or
    // recovered store. Cleanup still proves physical destruction of its owners.
    let dispatcher = effect.dispatcher.shutdown(deadline()).await.unwrap();
    assert!(dispatcher.physically_retired);
    effect.fixture.store.close();
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        effect
            .fixture
            .store
            .drain_async(deadline(), std::future::pending())
            .unwrap(),
    )
    .await
    .unwrap();
    assert!(report.snapshot.physically_retired());
    let (audit, worker) = effect.fixture.audit.as_mut().unwrap();
    audit.close();
    assert!(worker.join_until(deadline()).unwrap());
    assert_eq!(
        effect.fixture.admission.budget.outstanding_reservations(),
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_unknown_profile_and_missing_required_rows_never_supply_status() {
    let mut effect = setup_with_recovery().await;
    let mut unknown = request(&effect);
    unknown.profile.as_mut().unwrap().profile = "unsupported-effect-v99".into();
    let calls = effect
        .fixture
        .admission
        .calls
        .load(std::sync::atomic::Ordering::Relaxed);
    let refused = effect
        .fixture
        .backend
        .execute_state(reader("alice"), unknown.into())
        .await
        .err()
        .unwrap();
    assert_eq!(refused.code, PlatformErrorCode::Unavailable);
    assert_eq!(
        effect
            .fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        calls
    );
    effect.finish().await;
    for kind in ["unknown", "missing", "payload"] {
        let mut effect = setup_with_recovery().await;
        let key = if kind == "payload" {
            latent_effects::dispatch_store::effect_payload_key(&effect.effect).unwrap()
        } else {
            latent_effects::dispatch_store::effect_row_key(&effect.effect).unwrap()
        };
        let selected = key.clone();
        let original = effect
            .fixture
            .store
            .with_store(
                latent_state::store_io::StoreIoKind::RecoveryRead,
                WORK_BYTES as u64,
                move |engine| engine.snapshot()?.get(&selected),
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        let damage = if kind == "unknown" {
            let mut bytes = original.clone();
            bytes[4] = 255;
            Some(bytes)
        } else {
            None
        };
        tamper_row_for_rejection_only(&effect, key.clone(), damage).await;
        let failed = effect
            .fixture
            .backend
            .execute_state(reader("alice"), request(&effect).into())
            .await
            .err()
            .unwrap();
        assert!(effect
            .fixture
            .audit
            .as_ref()
            .unwrap()
            .0
            .wait_until_idle_for_test(deadline())
            .unwrap());
        retire_tampered_fixture(&mut effect).await;
        assert_eq!(
            failed.code,
            if kind == "missing" {
                PlatformErrorCode::NotFound
            } else {
                PlatformErrorCode::Unavailable
            }
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_closed_namespace_refuses_frame_without_releasing_retained_native_bytes()
{
    let mut effect = setup_with_recovery().await;
    let original = effect.fixture.admission.native.snapshot().unwrap().recovery;
    let response = read(&effect).await;
    let retained = effect.fixture.admission.native.snapshot().unwrap().recovery;
    assert!(retained.bytes > original.bytes);
    effect
        .fixture
        .backend
        .0
        .services
        .namespaces
        .lifecycle()
        .retire()
        .unwrap();
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::Unavailable
    );
    assert_eq!(
        effect.fixture.admission.native.snapshot().unwrap().recovery,
        retained
    );
    let failed = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(failed.code, PlatformErrorCode::Unavailable);
    drop(response);
    assert_eq!(
        effect.fixture.admission.native.snapshot().unwrap().recovery,
        original
    );
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_maximum_payload_metadata_and_history_fit_original_work_reservation() {
    let mut effect = setup_with_maximum_recovery().await;
    let native = effect.fixture.admission.native.snapshot().unwrap().recovery;
    let response = read(&effect).await;
    let actual = receipt(&response);
    assert_eq!(actual.dispatch_attempt, 128);
    assert_eq!(
        actual.disposition,
        t::EffectDisposition::KnownFailure as i32
    );
    assert!(actual.provider_receipt.is_none());
    assert!(actual.retention.as_ref().unwrap().payload_available);
    assert_eq!(actual.failure_code.as_deref(), Some("provider-failure"));
    assert!(
        effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .recovery
            .bytes
            > native.bytes
    );
    assert_eq!(WORK_BYTES, 8 * 1024 * 1024);
    assert!(response.response.encoded_len() < 4096);
    response.owner.with_current(&mut || {}).unwrap();
    drop(response);
    assert_eq!(
        effect.fixture.admission.native.snapshot().unwrap().recovery,
        native
    );
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_read_preserves_physically_retired_provider_ack_and_ambiguous_attempt() {
    use latent_effects::dispatch::Disposition;
    for disposition in [Disposition::ProviderAcknowledged, Disposition::Uncertain] {
        let mut effect = setup_with_recovery_provider(disposition).await;
        effect.settle_original().await;
        let response = read(&effect).await;
        let actual = receipt(&response);
        assert_eq!(actual.dispatch_attempt, 1);
        assert_eq!(
            actual.disposition,
            if disposition == Disposition::ProviderAcknowledged {
                t::EffectDisposition::ProviderAcknowledged as i32
            } else {
                t::EffectDisposition::UncertainAfterDispatch as i32
            }
        );
        assert_eq!(
            actual.provider_receipt.is_some(),
            disposition == Disposition::ProviderAcknowledged
        );
        assert!(actual.owner_epoch.is_some() && actual.claim_generation.is_some());
        assert_eq!(actual.record_version, effect.version);
        drop(response);
        effect.finish().await;
    }
}
