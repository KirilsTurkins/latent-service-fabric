//! These are actual native adapter controls, separate from signed Java qualification.
use super::*;
use latent_effects::dispatch::Disposition;
use latent_state::{
    embedded::{AtomicBatch, RowKey, RowMutation},
    namespace::{
        compatibility::RetainedCount,
        history::{history_key, NamespaceHistory},
    },
    recovery::{namespace_resume::NamespaceRecoveryView, RecoveryGuard},
    store_io::StoreIoKind,
};
use std::time::Duration;

mod fixture;
mod migration;
mod policy;
use fixture::Fixture;

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}

#[tokio::test]
async fn original_pending_effect_resumes_without_changing_original_retained_work() {
    let fixture = Fixture::new(27).await;
    let before = fixture.effect_payload_digest().await;
    let record = EffectRecord::decode(&before.1).unwrap();
    assert_eq!(record.disposition(), Disposition::Pending);
    assert_eq!(record.attempts(), 0);
    assert_eq!(record.durable_format(), ("latent.effect-record.v1", 1));
    assert!(record.management().is_none());
    let first = fixture.resume(fixture.request.clone()).await;
    let accepted = first.as_ref().is_ok_and(|(replay, _)| !replay);
    assert_eq!(fixture.effect_payload_digest().await, before);
    if accepted {
        let request = fixture.request.clone();
        fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 1024 * 1024, move |engine| {
                let actual = NamespaceRecoveryView::capture(
                    &engine.snapshot()?,
                    &request.scope.tenant,
                    &request.scope.namespace,
                )?;
                assert_eq!(actual.namespace.status, NamespaceStatus::Active);
                assert_eq!(actual.history.status, HistoryStatus::Ready);
                assert!(actual.guard.is_none());
                assert_ne!(actual.view_token()?, request.expected_view);
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }
    drop(first);
    drop(before);
    drop(record);
    fixture.finish().await;
    assert!(
        accepted,
        "original decoded Pending0 must resume after actual native/store retirement"
    );
}

#[tokio::test]
async fn accepted_original_resume_replays_lost_reply_but_never_accepts_new_operation_old_view() {
    let fixture = Fixture::new(27).await;
    let first = fixture.resume(fixture.request.clone()).await.unwrap();
    let after = fixture.rows_digest().await;
    let replay = fixture.resume(fixture.request.clone()).await.unwrap();
    assert!(replay.0);
    assert_eq!(first.1, replay.1);
    assert_eq!(fixture.rows_digest().await, after);
    let mut changed = fixture.request.clone();
    changed.operation_id = "different-operation".into();
    assert!(fixture.resume(changed).await.is_err());
    assert_eq!(fixture.rows_digest().await, after);
    drop(first);
    drop(replay);
    fixture.finish().await;
}

#[tokio::test]
async fn maximum_original_payload_stays_unchanged_through_bounded_native_resume() {
    let fixture = Fixture::new(latent_core::transaction_contract::VALUE_BYTES).await;
    let before = fixture.effect_payload_digest().await;
    let result = fixture.resume(fixture.request.clone()).await.unwrap();
    assert!(!result.0);
    assert_eq!(fixture.effect_payload_digest().await, before);
    drop(before);
    drop(result);
    fixture.finish().await;
}

#[tokio::test]
async fn restored_guard_or_history_pending_effect_requires_original_reconciliation() {
    for condition in 0..4 {
        let fixture = Fixture::new(27).await;
        fixture
            .store
            .with_store(StoreIoKind::RecoveryWrite, 1024 * 1024, move |engine| {
                let view = engine.snapshot()?;
                let actual = NamespaceRecoveryView::capture(
                    &view,
                    &latent_core::TenantId("tests".into()),
                    &latent_core::StateNamespaceId("business".into()),
                )?;
                let mut batch = AtomicBatch::default();
                if condition == 0 {
                    let mut restored = actual.history.restored_after(&actual.history).unwrap();
                    restored.status = HistoryStatus::ReconciliationRequired;
                    batch.mutations.push(RowMutation {
                        key: history_key(
                            &restored.tenant,
                            &restored.namespace,
                            restored.incarnation,
                        )
                        .unwrap(),
                        value: Some(restored.encode().unwrap()),
                    });
                } else {
                    let guard = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
                    batch = guard.prepare_staging()?;
                }
                drop(view);
                fixture::apply_accounted(engine, batch)?;
                if condition >= 2 {
                    let view = engine.snapshot()?;
                    let guard = RecoveryGuard::capture(&view)?.unwrap();
                    let completed = guard.prepare_completed()?;
                    drop(view);
                    fixture::apply_accounted(engine, completed)?;
                }
                if condition == 3 {
                    let view = engine.snapshot()?;
                    let guard = RecoveryGuard::capture(&view)?.unwrap();
                    let reviewed = guard.prepare_reviewed(&view, [7; 32], |_, _, _| Ok(()))?;
                    drop(view);
                    fixture::apply_accounted(engine, reviewed)?;
                }
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let before = fixture.rows_digest().await;
        let mut request = fixture.request.clone();
        let scope = request.scope.clone();
        request.expected_view = fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 1024 * 1024, move |engine| {
                NamespaceRecoveryView::capture(
                    &engine.snapshot()?,
                    &scope.tenant,
                    &scope.namespace,
                )?
                .view_token()
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        assert!(fixture.resume(request).await.is_err());
        assert_eq!(fixture.rows_digest().await, before);
        fixture.finish().await;
    }
}

#[tokio::test]
async fn actual_uncertain_command_preserves_pending_effect_and_refuses_original_resume() {
    let fixture = Fixture::with_uncertain_command().await;
    let before = fixture.rows_digest().await;
    let actual = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 1024 * 1024, |engine| {
            let census = fixture::census(&engine.snapshot()?)?;
            Ok(census.entries().iter().any(|(format, count)| {
                format.kind == RetainedKind::CommandAttempt && count.unresolved > 0
            }))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(actual);
    assert!(fixture.resume(fixture.request.clone()).await.is_err());
    assert_eq!(fixture.rows_digest().await, before);
    fixture.finish().await;
}

#[tokio::test]
async fn actual_durable_before_send_attempt_remains_unresolved_after_original_quiesce() {
    let fixture = Fixture::with_attempted_effect().await;
    let before = fixture.effect_payload_digest().await;
    let record = EffectRecord::decode(&before.1).unwrap();
    assert_eq!(record.disposition(), Disposition::Dispatching);
    assert_eq!(record.attempts(), 1);
    assert!(!record.send_started());
    assert!(fixture.resume(fixture.request.clone()).await.is_err());
    assert_eq!(fixture.effect_payload_digest().await, before);
    drop(before);
    drop(record);
    fixture.finish().await;
}

#[tokio::test]
async fn retained_valid_migration_metadata_never_uses_original_pending_exception() {
    let fixture = Fixture::new(27).await;
    let request = fixture.request.clone();
    fixture
        .store
        .with_store(StoreIoKind::RecoveryWrite, 1024 * 1024, move |engine| {
            migration::retain(engine, &request)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let before = fixture.rows_digest().await;
    assert!(fixture.resume(fixture.request.clone()).await.is_err());
    assert_eq!(fixture.rows_digest().await, before);
    fixture.finish().await;
}

#[tokio::test]
async fn unsupported_effect_bytes_or_expired_original_cutoff_never_change_pending_rows() {
    for expired in [false, true] {
        let fixture = Fixture::new(27).await;
        if !expired {
            let effect = fixture.effect.clone();
            fixture
                .store
                .with_store(StoreIoKind::RecoveryWrite, 1024 * 1024, move |engine| {
                    let view = engine.snapshot()?;
                    let key = latent_effects::dispatch_store::effect_row_key(&effect)?;
                    let mut bytes = view.get(&key)?.unwrap();
                    bytes[4] = 99;
                    let guard = view.get(&latent_state::tenant::guard_key())?.unwrap();
                    drop(view);
                    // Explicit TEST-only unsupported-format damage; no new format authority.
                    engine.apply(AtomicBatch {
                        expectations: vec![],
                        mutations: vec![
                            RowMutation {
                                key,
                                value: Some(bytes),
                            },
                            RowMutation {
                                key: latent_state::tenant::guard_key(),
                                value: Some(guard),
                            },
                        ],
                    })
                })
                .unwrap()
                .await
                .unwrap()
                .unwrap();
        }
        let before = fixture.rows_digest().await;
        let request = fixture.request.clone();
        fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 8 * 1024 * 1024, move |engine| {
                let view = engine.snapshot()?;
                if let Ok(census) = fixture::census(&view) {
                    assert!(
                        super::prepare(&view, &request, &census, Instant::now(), || Ok(()))
                            .is_err()
                    );
                } else {
                    assert!(!expired);
                }
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        assert_eq!(fixture.rows_digest().await, before);
        fixture.finish().await;
    }
}

#[tokio::test]
async fn revoked_actual_namespace_policy_or_stale_view_never_changes_pending_rows() {
    for denied in [false, true] {
        let fixture = Fixture::new(27).await;
        let before = fixture.rows_digest().await;
        let mut request = fixture.request.clone();
        if denied {
            fixture.gate.deny();
        } else {
            request.expected_view[43] = request.expected_view[43].checked_add(1).unwrap();
        }
        assert!(fixture.resume(request).await.is_err());
        assert_eq!(fixture.rows_digest().await, before);
        fixture.finish().await;
    }
}

#[tokio::test]
async fn mismatched_or_other_unresolved_census_never_authorizes_original_pending_resume() {
    let fixture = Fixture::new(27).await;
    let before = fixture.rows_digest().await;
    for kind in [
        RetainedKind::CommandAttempt,
        RetainedKind::SuccessResult,
        RetainedKind::RejectionResult,
        RetainedKind::InboxIdentity,
        RetainedKind::OrderingGroup,
        RetainedKind::EffectEnvelope,
    ] {
        let request = fixture.request.clone();
        fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 8 * 1024 * 1024, move |engine| {
                let view = engine.snapshot()?;
                let mut census = fixture::census(&view)?;
                // Test-only altered evidence: no stored record or valid lifecycle is invented.
                census
                    .observe(
                        RetainedFormat {
                            kind,
                            identity: "altered-census.v1".into(),
                        },
                        RetainedCount {
                            rows: 1,
                            bytes: 1,
                            unresolved: 1,
                        },
                    )
                    .unwrap();
                assert!(super::prepare(&view, &request, &census, deadline(), || Ok(())).is_err());
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }
    assert_eq!(fixture.rows_digest().await, before);
    fixture.finish().await;
}

#[tokio::test]
async fn foreign_effect_scope_or_claimed_pending_record_never_uses_original_exception() {
    for foreign in [true, false] {
        let fixture = Fixture::new(27).await;
        let effect = fixture.effect.clone();
        let gate = fixture.gate.clone();
        fixture
            .store
            .with_store(StoreIoKind::RecoveryWrite, 1024 * 1024, move |engine| {
                if foreign {
                    let original = NamespaceRecoveryView::capture(
                        &engine.snapshot()?,
                        &latent_core::TenantId("tests".into()),
                        &latent_core::StateNamespaceId("business".into()),
                    )?;
                    let namespace = latent_state::namespace::NamespaceRecord::create(
                        original.namespace.tenant,
                        latent_core::StateNamespaceId("foreign".into()),
                        original.namespace.state_schema,
                        latent_state::namespace::NamespaceQuota::default(),
                    )
                    .unwrap();
                    let history = NamespaceHistory::initial(&namespace);
                    fixture::apply_accounted(
                        engine,
                        AtomicBatch {
                            expectations: vec![],
                            mutations: vec![
                                RowMutation {
                                    key: RowKey {
                                        family: Family::Namespace,
                                        key: latent_state::namespace::namespace_record_key(
                                            &namespace.tenant,
                                            &namespace.id,
                                        )
                                        .unwrap(),
                                    },
                                    value: Some(namespace.encode().unwrap()),
                                },
                                RowMutation {
                                    key: history_key(
                                        &history.tenant,
                                        &history.namespace,
                                        history.incarnation,
                                    )
                                    .unwrap(),
                                    value: Some(history.encode().unwrap()),
                                },
                            ],
                        },
                    )?;
                    let authority =
                        latent_effects::authority::EffectAuthorityOwner::new(16, 4, 100).unwrap();
                    authority
                        .publish(fixture::rule(&gate, "tests", "foreign"))
                        .unwrap();
                    fixture::publish_named(engine, &gate, &authority, 27, false, "foreign")?;
                    return Ok(());
                }
                let view = engine.snapshot()?;
                let key = latent_effects::dispatch_store::effect_row_key(&effect)?;
                let original = view.get(&key)?.unwrap();
                let mut body: serde_json::Value = serde_json::from_slice(&original[5..]).unwrap();
                body["owner_epoch"] = 1.into();
                let mut changed = original[..5].to_vec();
                changed.extend(serde_json::to_vec(&body).unwrap());
                let guard = view.get(&latent_state::tenant::guard_key())?.unwrap();
                drop(view);
                // Explicit TEST-only same-store damage: unchanged tenant guard; never a valid claim/publication.
                engine.apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![
                        RowMutation {
                            key,
                            value: Some(changed),
                        },
                        RowMutation {
                            key: latent_state::tenant::guard_key(),
                            value: Some(guard),
                        },
                    ],
                })?;
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let before = fixture.rows_digest().await;
        assert!(fixture.resume(fixture.request.clone()).await.is_err());
        assert_eq!(fixture.rows_digest().await, before);
        fixture.finish().await;
    }
}
