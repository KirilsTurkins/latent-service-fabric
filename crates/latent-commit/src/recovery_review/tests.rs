//! Real rows/linked envelopes, conservative current review and opposing format
//! schedules. These fixtures do not establish production RPC/audit or restore.
use super::*;
use crate::atomic::Outcome;
use latent_state::{
    embedded::{AtomicBatch, Family, RowMutation},
    namespace::compatibility::{RetainedFormat, RetainedKind},
    recovery::{snapshot::RequiredArtifact, RecoveryStatus},
    tenant::INSTALLED_GLOBAL_ALLOWANCE,
};
use std::time::Duration;
mod fixture;
mod reconciliation;
mod restore;
use fixture::{Fixture, Owners};

fn workload() -> Fixture {
    let fixture = Fixture::new(false);
    fixture.command("successful", None, b"count".to_vec(), false);
    fixture.command("rejected", None, b"not-written".to_vec(), true);
    fixture.uncertain();
    fixture.quiesce();
    fixture
}

#[test]
fn whole_unit_review_preserves_actual_rejection_inbox_and_uncertain_effect_after_reopen() {
    let mut fixture = workload();
    let metadata = fixture.metadata();
    let reviewed = fixture.review(&metadata, &mut Owners::new()).unwrap();
    let inventory = &reviewed.closure().inventory;
    for (kind, identity) in [
        (RetainedKind::RejectionResult, "latent.result.v1/3"),
        (RetainedKind::CommandFingerprint, "latent.command.v1/4"),
        (RetainedKind::InboxIdentity, "latent.inbox.v1/1"),
        (RetainedKind::CommandAttempt, "latent.effect-attempt.v1/1"),
        (RetainedKind::EffectPayload, "latent.effect-payload.v1/1"),
    ] {
        let observed = inventory
            .entries()
            .get(&RetainedFormat {
                kind,
                identity: identity.into(),
            })
            .unwrap();
        assert!(observed.rows > 0 && observed.bytes > 0);
    }
    assert!(inventory.total().unresolved > 0);
    assert_eq!(
        inventory.require_retirement_drained(),
        Err(latent_state::namespace::NamespaceError::RecoveryRequired)
    );
    assert!(reviewed
        .closure()
        .required_artifacts
        .iter()
        .any(|artifact| artifact.identity == "original-publication"
            && artifact.digest == fixture::PUBLICATION));
    assert_eq!(
        reviewed.source_controls().dispatcher_checkpoint(),
        Some((1, 104))
    );
    let before = reviewed.census();
    let expected = reviewed.into_snapshot_closure();
    drop(fixture.store);
    fixture.store = fixture::open(&fixture.directory.path().join("state.redb"));
    let reopened = fixture.review(&metadata, &mut Owners::new()).unwrap();
    assert_eq!(reopened.census(), before);
    assert_eq!(reopened.closure().inventory, expected.inventory);
    assert_eq!(
        reopened.closure().required_artifacts,
        expected.required_artifacts
    );
    let (_, rejection) = atomic::inspect(
        &fixture.store.snapshot().unwrap(),
        &fixture::input("rejected", None).key,
        fixture::time(105),
        |_, _| Ok(()),
    )
    .unwrap();
    let rejection = rejection.unwrap();
    assert_eq!(rejection.outcome(), Outcome::Rejected);
    assert_eq!(rejection.code(), Some("BUSINESS_DECLINED"));
    assert_eq!(
        rejection.value(),
        Some(&fixture::value(b"original rejection"))
    );
}

#[test]
fn replacement_publication_provider_or_consumer_cannot_satisfy_original_evidence() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let mut replaced = Owners::new();
    replaced.source.publication = "replacement-publication".into();
    assert!(matches!(
        fixture.review(&metadata, &mut replaced),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    let mut recreated = Owners::new();
    recreated.profile.idempotency_profile = "recreated-finite-dedup-v2".into();
    assert!(matches!(
        fixture.review(&metadata, &mut recreated),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    let mut changed_consumer = Owners::new();
    changed_consumer.inbox_binding = "replacement-consumer".into();
    assert!(matches!(
        fixture.review(&metadata, &mut changed_consumer),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn removed_decoder_or_omitted_original_artifact_refuses_without_dropping_rows() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let before = fixture
        .review(&metadata, &mut Owners::new())
        .unwrap()
        .census();
    let mut owners = Owners::new();
    owners.formats.remove(&RetainedFormat {
        kind: RetainedKind::RejectionResult,
        identity: "latent.result.v1/3".into(),
    });
    assert!(matches!(
        fixture.review(&metadata, &mut owners),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    let mut omitted = metadata.clone();
    omitted
        .required_artifacts
        .retain(|artifact| artifact.digest != [0x22; 32]);
    assert!(matches!(
        fixture.review(&omitted, &mut Owners::new()),
        Err(RecoveryReviewError::Review(StoreError::Corrupt))
    ));
    assert_eq!(
        fixture
            .review(&metadata, &mut Owners::new())
            .unwrap()
            .census(),
        before
    );
}

#[test]
fn unknown_actual_result_version_and_missing_effect_payload_never_become_absent_work() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let view = fixture.store.snapshot().unwrap();
    let rows = view
        .scan_after(Family::Result, b"command-result-v1\0", None, 8, 64 * 1024)
        .unwrap()
        .rows;
    let (key, original) = rows
        .into_iter()
        .find(|(_, bytes)| bytes.starts_with(b"LCR\0\x03"))
        .unwrap();
    drop(view);
    let mut unsupported = original.clone();
    unsupported[4] = 255;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(unsupported),
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.review(&metadata, &mut Owners::new()),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(original),
            }],
        })
        .unwrap();
    fixture.review(&metadata, &mut Owners::new()).unwrap();
    let payload = fixture
        .store
        .snapshot()
        .unwrap()
        .scan_after(Family::PayloadReference, b"", None, 2, 64 * 1024)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: payload.0.clone(),
                value: None,
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.review(&metadata, &mut Owners::new()),
        Err(RecoveryReviewError::Source(StoreError::Corrupt))
    ));
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: payload.0,
                value: Some(payload.1),
            }],
        })
        .unwrap();
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn partial_tenant_configuration_and_validly_encoded_counter_drift_refuse_the_unit() {
    let fixture = Fixture::new(true);
    fixture.command("successful", None, b"count".to_vec(), false);
    fixture.quiesce();
    let metadata = fixture.metadata();
    fixture.review(&metadata, &mut Owners::new()).unwrap();
    let view = fixture.store.snapshot().unwrap();
    let result = review_snapshot(
        &view,
        RecoveryReviewRequest {
            quotas: &fixture.quotas[..1],
            global_allowance: INSTALLED_GLOBAL_ALLOWANCE,
            metadata: &metadata,
            deadline: Instant::now() + Duration::from_secs(20),
        },
        &mut Owners::new(),
        || Ok(()),
    );
    assert!(matches!(
        result,
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    let key = latent_state::tenant::quota_key(&fixture.quotas[0].tenant).unwrap();
    let original = view.get(&key).unwrap().unwrap();
    let mut drifted = latent_state::tenant::TenantRecord::decode(&original).unwrap();
    drifted.usage.metadata_bytes += 1;
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(drifted.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.review(&metadata, &mut Owners::new()),
        Err(RecoveryReviewError::Source(StoreError::Corrupt))
    ));
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(original),
            }],
        })
        .unwrap();
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn paused_recovery_controls_remain_original_descriptions_and_never_resume_history() {
    let fixture = workload();
    let guard = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: latent_state::recovery::guard_key(),
                value: Some(guard.encode().unwrap()),
            }],
        })
        .unwrap();
    let metadata = fixture.metadata();
    let reviewed = fixture.review(&metadata, &mut Owners::new()).unwrap();
    assert_eq!(reviewed.source_controls().recovery_guard(), Some(&guard));
    assert_eq!(
        reviewed
            .source_controls()
            .recovery_guard()
            .unwrap()
            .status(),
        RecoveryStatus::Staging
    );
    assert_eq!(
        reviewed.source_controls().dispatcher_checkpoint(),
        Some((1, 104))
    );
    assert_eq!(
        latent_state::recovery::require_ready(&fixture.store.snapshot().unwrap()),
        Err(StoreError::Unavailable)
    );
    assert_eq!(
        RecoveryGuard::capture(&fixture.store.snapshot().unwrap()).unwrap(),
        Some(guard)
    );
}

#[test]
fn maximum_original_entity_key_fits_physical_census_without_widening_business_key_cap() {
    let fixture = Fixture::new(false);
    fixture.command(
        "maximum-key",
        Some("e".repeat(256)),
        vec![b'k'; 1024],
        false,
    );
    fixture.quiesce();
    let rows = fixture
        .store
        .snapshot()
        .unwrap()
        .scan_after(Family::State, b"", None, 2, 2 * 1024 * 1024)
        .unwrap()
        .rows;
    assert_eq!(rows.len(), 1);
    assert!(rows[0].0.key.len() > 1024 && rows[0].0.key.len() <= 4096);
    let cell = latent_state::session::inspect_cell(
        &fixture.store.snapshot().unwrap(),
        &rows[0].0,
        &rows[0].1,
    )
    .unwrap();
    assert_eq!(cell.key.len(), 1024);
    assert_eq!(cell.scope.entity.as_deref(), Some("e".repeat(256).as_str()));
    fixture
        .review(&fixture.metadata(), &mut Owners::new())
        .unwrap();
}

#[test]
fn original_deadline_and_current_refusal_do_not_refresh_review_or_touch_rows() {
    let fixture = workload();
    let metadata = fixture.metadata();
    let view = fixture.store.snapshot().unwrap();
    let mut owners = Owners::new();
    let expired = review_snapshot(
        &view,
        RecoveryReviewRequest {
            quotas: &fixture.quotas,
            global_allowance: INSTALLED_GLOBAL_ALLOWANCE,
            metadata: &metadata,
            deadline: Instant::now() - Duration::from_millis(1),
        },
        &mut owners,
        || panic!("expired original reached current reviewer"),
    );
    assert!(matches!(expired, Err(RecoveryReviewError::Deadline)));
    assert_eq!(owners.calls, 0);
    let before = fixture
        .review(&metadata, &mut Owners::new())
        .unwrap()
        .census();
    let mut observations = 0usize;
    let revoked = review_snapshot(
        &view,
        RecoveryReviewRequest {
            quotas: &fixture.quotas,
            global_allowance: INSTALLED_GLOBAL_ALLOWANCE,
            metadata: &metadata,
            deadline: Instant::now() + Duration::from_secs(20),
        },
        &mut Owners::new(),
        || {
            observations += 1;
            if observations == 8 {
                Err(StoreError::Unavailable)
            } else {
                Ok(())
            }
        },
    );
    assert!(matches!(
        revoked,
        Err(RecoveryReviewError::Review(StoreError::Unavailable))
    ));
    assert_eq!(observations, 8);
    assert_eq!(
        fixture
            .review(&metadata, &mut Owners::new())
            .unwrap()
            .census(),
        before
    );
}

#[test]
fn uninstalled_migration_producer_and_unknown_runtime_refuse_without_inventing_counters() {
    let fixture = workload();
    let mut metadata = fixture.metadata();
    metadata.runtime_digest = [255; 32];
    assert!(matches!(
        fixture.review(&metadata, &mut Owners::new()),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    metadata.runtime_digest = fixture::RUNTIME;
    let key = RowKey {
        family: Family::Maintenance,
        key: b"uninstalled-migration-v2\0".to_vec(),
    };
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(b"unknown producer bytes".to_vec()),
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.review(&metadata, &mut Owners::new()),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value: None }],
        })
        .unwrap();
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn processing_identity_binds_original_scope_and_changes_never_relabel_message_history() {
    let original = fixture::input("one", None);
    let second = fixture::input("two", None);
    let inbox = original.inbox.as_ref().unwrap();
    let identity = original_inbox_profile_identity(&original.key, &original.source, inbox).unwrap();
    assert_eq!(
        identity,
        original_inbox_profile_identity(
            &second.key,
            &second.source,
            second.inbox.as_ref().unwrap()
        )
        .unwrap()
    );
    let mut foreign = original.key.clone();
    foreign.tenant = "other-tenant".into();
    assert_ne!(
        identity,
        original_inbox_profile_identity(&foreign, &original.source, inbox).unwrap()
    );
    let mut changed = inbox.clone();
    changed.binding = "different-processing-subscription".into();
    assert_ne!(
        identity,
        original_inbox_profile_identity(&original.key, &original.source, &changed).unwrap()
    );
    assert_eq!(inbox.message, "message-one");
}
