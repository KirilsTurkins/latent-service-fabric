use std::fs::OpenOptions;

use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, Family, FencedStoreError, RowKey, RowMutation, StoreError,
    StoreLimits,
};
use latent_state::reservation::{LogicalReservation, KEY_PREFIX};

use crate::authority::{AuthorityError, DurableEffectAuthority, EffectTime};
use crate::dispatch::{
    effect_record_version, AttemptIdentity, AttemptReceipt, Disposition, EffectManagementFact,
    EffectRecord, RetryProof,
};
use crate::dispatch_store::{
    effect_payload_key, effect_row_key, initial_due_mutation, DispatchCatalog, DispatchEpoch,
    DueRecord,
};
use crate::payload::{tests as payload_fixture, PayloadRecord};
use crate::runtime::ProviderConfirmation;

use super::*;

struct Fixture {
    root: tempfile::TempDir,
    store: Option<EmbeddedStore>,
    limits: StoreLimits,
    authority: DurableEffectAuthority,
    epoch: DispatchEpoch,
    due: DueRecord,
}
impl Fixture {
    fn new(limits: StoreLimits) -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = Self::open(root.path(), limits);
        let value = payload_fixture::value();
        let authority = payload_fixture::authority(&value, &"a".repeat(64));
        let record = EffectRecord::committed(&authority).unwrap();
        let payload = PayloadRecord::new(&authority, value).unwrap();
        let due = initial_due_mutation(&authority).unwrap();
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![
                    RowMutation {
                        key: effect_row_key(&authority.link().effect).unwrap(),
                        value: Some(record.encode().unwrap()),
                    },
                    RowMutation {
                        key: effect_payload_key(&authority.link().effect).unwrap(),
                        value: Some(payload.encode().unwrap()),
                    },
                    due.clone(),
                ],
            })
            .unwrap();
        let epoch = DispatchCatalog::begin_exclusive_epoch(&store, time(100), None).unwrap();
        Self {
            root,
            store: Some(store),
            limits,
            authority,
            epoch,
            due: DueRecord::decode(&due.key, due.value.as_deref().unwrap()).unwrap(),
        }
    }
    fn open(root: &std::path::Path, limits: StoreLimits) -> EmbeddedStore {
        EmbeddedStore::open_file(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(root.join("effects.redb"))
                .unwrap(),
            limits,
        )
        .unwrap()
    }
    fn store(&self) -> &EmbeddedStore {
        self.store.as_ref().unwrap()
    }
    fn reopen(&mut self) {
        drop(self.store.take());
        self.store = Some(Self::open(self.root.path(), self.limits));
        DispatchCatalog::validate_view(&self.store().snapshot().unwrap()).unwrap();
    }
    fn effect(&self) -> &str {
        &self.authority.link().effect
    }
    fn record_bytes(&self) -> Vec<u8> {
        self.store()
            .snapshot()
            .unwrap()
            .get(&effect_row_key(self.effect()).unwrap())
            .unwrap()
            .unwrap()
    }
    fn record(&self) -> EffectRecord {
        EffectRecord::decode(&self.record_bytes()).unwrap()
    }
    fn complete(&self, sent: bool) -> AttemptIdentity {
        let claimed =
            DispatchCatalog::claim(self.store(), self.epoch, &self.due, time(101)).unwrap();
        if sent {
            DispatchCatalog::begin_send(self.store(), self.epoch, &claimed.attempt, time(102))
                .unwrap();
        }
        DispatchCatalog::complete(
            self.store(),
            self.epoch,
            &claimed.attempt,
            AttemptReceipt {
                disposition: if sent {
                    Disposition::Uncertain
                } else {
                    Disposition::KnownFailed
                },
                reason: "actual-cleanup-finished".into(),
                provider_receipt: None,
                observed_at_millis: 103,
            },
            None,
            time(103),
        )
        .unwrap();
        claimed.attempt
    }
    fn request(&self, operation: &str, action: EffectManagementAction) -> EffectManagementRequest {
        EffectManagementRequest::new(EffectManagementInput {
            actor_tenant: "tenant-a".into(),
            actor_subject: "operator-a".into(),
            namespace: "orders".into(),
            incarnation: 7,
            caller_scope: "caller-a".into(),
            command: "command-a".into(),
            command_attempt: 1,
            effect: self.effect().into(),
            operation_id: operation.into(),
            action,
            expected_version: effect_record_version(&self.record_bytes()).unwrap(),
            expected_policy_digest: "policy-original".into(),
            original_request_digest: [1; 32],
            reason: "reviewed-original-effect".into(),
            retry_delay_millis: if action == EffectManagementAction::Redrive {
                10
            } else {
                0
            },
        })
        .unwrap()
    }
    fn plan(
        &self,
        request: EffectManagementRequest,
        proof: Option<RetryProof>,
    ) -> EffectManagementPlan {
        let view = self.store().snapshot().unwrap();
        let prepared =
            EffectManagementCatalog::prepare_plan(&view, self.epoch, request, time(104), proof)
                .unwrap();
        let (batch, plan, _) = prepared.into_parts();
        drop(view);
        self.store().apply(batch).unwrap();
        DispatchCatalog::validate_view(&self.store().snapshot().unwrap()).unwrap();
        plan
    }
    fn mutate(
        &self,
        plan: EffectManagementPlan,
        evidence: EffectManagementEvidence,
        at: u64,
    ) -> EffectManagementReceipt {
        let view = self.store().snapshot().unwrap();
        let prepared =
            EffectManagementCatalog::prepare_mutation(&view, self.epoch, plan, evidence, time(at))
                .unwrap();
        let (batch, receipt, _) = prepared.into_parts();
        drop(view);
        self.store().apply(batch).unwrap();
        DispatchCatalog::validate_view(&self.store().snapshot().unwrap()).unwrap();
        receipt
    }
}
fn time(unix_millis: u64) -> EffectTime {
    EffectTime {
        unix_millis,
        continuity_proven: true,
    }
}

#[test]
fn retired_known_nonexecution_redrive_preserves_attempt_and_one_original_receipt() {
    let mut fixture = Fixture::new(StoreLimits::default());
    let attempt = fixture.complete(false);
    let plan = fixture.plan(
        fixture.request("retry-original", EffectManagementAction::Redrive),
        None,
    );
    assert_eq!(plan.original_attempt(), Some(&attempt));
    let historical = fixture.mutate(
        plan.clone(),
        EffectManagementEvidence::Retry(RetryProof::KnownNonexecution),
        105,
    );
    assert_eq!(historical.fact(), EffectManagementFact::RedriveScheduled);
    assert_eq!(fixture.record().attempts(), 1);
    assert_eq!(fixture.record().history_sequence(), 1);
    let view = fixture.store().snapshot().unwrap();
    let replay = EffectManagementCatalog::prepare_mutation(
        &view,
        fixture.epoch,
        plan.clone(),
        EffectManagementEvidence::Administrator,
        time(2000),
    )
    .unwrap();
    let (batch, same, replayed) = replay.into_parts();
    assert!(replayed);
    assert_eq!(same, historical);
    assert!(batch.mutations.is_empty());
    drop(view);
    fixture.reopen();
    assert_eq!(
        EffectManagementCatalog::lookup(&fixture.store().snapshot().unwrap(), &plan).unwrap(),
        Some(historical)
    );
    let due = DispatchCatalog::due_page(&fixture.store().snapshot().unwrap(), 115, None, 8, 4096)
        .unwrap();
    assert_eq!(due.rows.len(), 1);
    assert_eq!(
        fixture.record().management().unwrap().fact(),
        EffectManagementFact::RedriveScheduled
    );
}

#[test]
fn unknown_send_never_manufactures_absence_or_redrive_proof() {
    let fixture = Fixture::new(StoreLimits::default());
    fixture.complete(true);
    let request = fixture.request("unknown-retry", EffectManagementAction::Redrive);
    let view = fixture.store().snapshot().unwrap();
    for proof in [
        None,
        Some(RetryProof::KnownNonexecution),
        Some(RetryProof::QualifiedDeduplication {
            valid_until_millis: 114,
            same_payload: true,
            same_provider_incarnation: true,
        }),
        Some(RetryProof::QualifiedDeduplication {
            valid_until_millis: 500,
            same_payload: false,
            same_provider_incarnation: true,
        }),
    ] {
        assert!(EffectManagementCatalog::prepare_plan(
            &view,
            fixture.epoch,
            request.clone(),
            time(104),
            proof
        )
        .is_err());
    }
    assert!(view
        .scan_after(Family::Maintenance, PLAN_PREFIX, None, 16, 65536)
        .unwrap()
        .rows
        .is_empty());
    drop(view);
    assert_eq!(fixture.record().disposition(), Disposition::Uncertain);
    assert_eq!(fixture.record().attempts(), 1);
}

#[test]
fn qualified_redrive_is_original_payload_profile_and_horizon_bound() {
    let fixture = Fixture::new(StoreLimits::default());
    fixture.complete(true);
    let proof = RetryProof::QualifiedDeduplication {
        valid_until_millis: 150,
        same_payload: true,
        same_provider_incarnation: true,
    };
    let plan = fixture.plan(
        fixture.request("dedup-original", EffectManagementAction::Redrive),
        Some(proof),
    );
    assert_eq!(plan.expires_at_millis(), 140);
    let view = fixture.store().snapshot().unwrap();
    assert!(EffectManagementCatalog::prepare_mutation(
        &view,
        fixture.epoch,
        plan.clone(),
        EffectManagementEvidence::Retry(RetryProof::KnownNonexecution),
        time(105)
    )
    .is_err());
    assert!(EffectManagementCatalog::prepare_mutation(
        &view,
        fixture.epoch,
        plan.clone(),
        EffectManagementEvidence::Retry(proof),
        time(140)
    )
    .is_err());
    drop(view);
    fixture.mutate(plan, EffectManagementEvidence::Retry(proof), 105);
    assert_eq!(fixture.record().disposition(), Disposition::RetryScheduled);
    assert_eq!(fixture.record().attempts(), 1);
}

#[test]
fn provider_confirmation_is_distinct_from_original_uncertain_attempt_and_admin_declaration() {
    let fixture = Fixture::new(StoreLimits::default());
    let attempt = fixture.complete(true);
    let plan = fixture.plan(
        fixture.request("lookup-original", EffectManagementAction::Reconcile),
        None,
    );
    let bad = ProviderConfirmation::new(
        attempt.clone(),
        [9; 32],
        "endpoint:91:duplicate=1".into(),
        105,
    )
    .unwrap();
    assert!(EffectManagementCatalog::prepare_mutation(
        &fixture.store().snapshot().unwrap(),
        fixture.epoch,
        plan.clone(),
        EffectManagementEvidence::Provider(bad),
        time(106)
    )
    .is_err());
    let confirmation = ProviderConfirmation::new(
        attempt.clone(),
        plan.request().input().expected_version,
        "endpoint:91:duplicate=1".into(),
        105,
    )
    .unwrap();
    let receipt = fixture.mutate(plan, EffectManagementEvidence::Provider(confirmation), 106);
    assert_eq!(receipt.fact(), EffectManagementFact::ProviderConfirmed);
    assert_eq!(receipt.provider_observed_at_millis(), Some(105));
    assert_eq!(receipt.completed_at_millis(), 106);
    let record = fixture.record();
    assert_eq!(record.disposition(), Disposition::ProviderAcknowledged);
    assert_eq!(record.latest().unwrap().disposition, Disposition::Uncertain);
    let history = DispatchCatalog::history_page(
        &fixture.store().snapshot().unwrap(),
        fixture.effect(),
        None,
        8,
        4096,
    )
    .unwrap();
    assert_eq!(history.rows[0].attempt, Some(attempt));
    assert_eq!(history.rows[0].receipt.disposition, Disposition::Uncertain);
    assert!(fixture.record_bytes().starts_with(b"LER\0\x02"));
}

#[test]
fn administrative_terminal_disposition_keeps_uncertain_facts_and_payload_holds() {
    let fixture = Fixture::new(StoreLimits::default());
    let attempt = fixture.complete(true);
    let plan = fixture.plan(
        fixture.request("stop-original", EffectManagementAction::Terminate),
        None,
    );
    let receipt = fixture.mutate(plan, EffectManagementEvidence::Administrator, 105);
    assert_eq!(
        receipt.fact(),
        EffectManagementFact::AdministratorTerminated
    );
    assert_eq!(receipt.provider_receipt(), None);
    assert_eq!(fixture.record().disposition(), Disposition::DeadLettered);
    assert_eq!(
        fixture.record().latest().unwrap().disposition,
        Disposition::Uncertain
    );
    assert_eq!(
        DispatchCatalog::last_completed_attempt(
            &fixture.store().snapshot().unwrap(),
            fixture.effect()
        )
        .unwrap(),
        Some(attempt)
    );
    assert!(fixture
        .store()
        .snapshot()
        .unwrap()
        .get(&effect_payload_key(fixture.effect()).unwrap())
        .unwrap()
        .is_some());
}

#[test]
fn interrupted_recovery_uses_original_history_identity_instead_of_replacement_epoch() {
    let mut fixture = Fixture::new(StoreLimits::default());
    let claimed =
        DispatchCatalog::claim(fixture.store(), fixture.epoch, &fixture.due, time(101)).unwrap();
    DispatchCatalog::begin_send(fixture.store(), fixture.epoch, &claimed.attempt, time(102))
        .unwrap();
    fixture.reopen();
    let epoch = DispatchCatalog::begin_exclusive_epoch(
        fixture.store(),
        time(103),
        Some((fixture.epoch.generation(), 102)),
    )
    .unwrap();
    DispatchCatalog::recover_page(fixture.store(), epoch, None, true, time(104)).unwrap();
    let record = fixture.record();
    assert!(record.owner_epoch() > claimed.attempt.owner_epoch());
    assert!(record.claim_generation() > claimed.attempt.claim_generation());
    assert_eq!(
        DispatchCatalog::last_completed_attempt(
            &fixture.store().snapshot().unwrap(),
            fixture.effect()
        )
        .unwrap(),
        Some(claimed.attempt)
    );
}

#[test]
fn stale_operation_recovery_cannot_change_actor_action_target_or_original_cas() {
    let fixture = Fixture::new(StoreLimits::default());
    fixture.complete(false);
    let request = fixture.request("stable-operation", EffectManagementAction::Redrive);
    let plan = fixture.plan(request.clone(), None);
    let mut changed = request.input().clone();
    changed.action = EffectManagementAction::Terminate;
    changed.retry_delay_millis = 0;
    let view = fixture.store().snapshot().unwrap();
    assert!(EffectManagementCatalog::prepare_plan(
        &view,
        fixture.epoch,
        EffectManagementRequest::new(changed).unwrap(),
        time(104),
        None
    )
    .is_err());
    let mut wrong_tenant = request.input().clone();
    wrong_tenant.actor_tenant = "tenant-b".into();
    assert!(EffectManagementCatalog::prepare_plan(
        &view,
        fixture.epoch,
        EffectManagementRequest::new(wrong_tenant).unwrap(),
        time(104),
        None
    )
    .is_err());
    let prepared = EffectManagementCatalog::prepare_mutation(
        &view,
        fixture.epoch,
        plan.clone(),
        EffectManagementEvidence::Retry(RetryProof::KnownNonexecution),
        time(105),
    )
    .unwrap();
    let (batch, _, _) = prepared.into_parts();
    drop(view);
    assert_eq!(
        fixture
            .store()
            .apply_fenced(batch, || Err(EffectManagementError::PermissionDenied)),
        Err(FencedStoreError::Fence(
            EffectManagementError::PermissionDenied
        ))
    );
    assert_eq!(fixture.record().disposition(), Disposition::KnownFailed);
    assert!(
        EffectManagementCatalog::lookup(&fixture.store().snapshot().unwrap(), &plan)
            .unwrap()
            .is_none()
    );
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
}

#[test]
fn preallocated_management_disposition_progresses_at_exact_native_logical_high_water() {
    let limits = StoreLimits {
        maximum_logical_bytes: 128 * 1024,
        ..StoreLimits::default()
    };
    let fixture = Fixture::new(limits);
    let plan = fixture.plan(
        fixture.request("high-water-stop", EffectManagementAction::Terminate),
        None,
    );
    let view = fixture.store().snapshot().unwrap();
    let mut used = 0usize;
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        for (key, bytes) in view
            .scan_after(family, b"", None, 256, 4 * 1024 * 1024)
            .unwrap()
            .rows
        {
            used += key.key.len() + 1 + bytes.len();
            if family == Family::Maintenance && key.key.starts_with(KEY_PREFIX) {
                used += usize::try_from(LogicalReservation::decode(&bytes).unwrap().bytes).unwrap();
            }
        }
    }
    drop(view);
    let filler = RowKey {
        family: Family::State,
        key: b"ordinary-full".to_vec(),
    };
    let body = vec![42; limits.maximum_logical_bytes - used - filler.key.len() - 1];
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: filler.clone(),
                value: Some(body.clone()),
            }],
        })
        .unwrap();
    assert_eq!(
        fixture.store().apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::State,
                    key: b"ordinary-extra".to_vec()
                },
                value: Some(vec![1]),
            }]
        }),
        Err(StoreError::Capacity)
    );
    let receipt = fixture.mutate(plan, EffectManagementEvidence::Administrator, 105);
    assert_eq!(
        receipt.fact(),
        EffectManagementFact::AdministratorTerminated
    );
    assert_eq!(
        fixture.store().snapshot().unwrap().get(&filler).unwrap(),
        Some(body)
    );
    assert_eq!(fixture.record().attempts(), 0);
    assert!(fixture
        .store()
        .snapshot()
        .unwrap()
        .get(&fixture.due.key().unwrap())
        .unwrap()
        .is_none());
}

#[test]
fn old_unmanaged_format_remains_exact_and_foreign_managed_versions_fail_closed() {
    let fixture = Fixture::new(StoreLimits::default());
    let before = fixture.record_bytes();
    assert!(before.starts_with(b"LER\0\x01"));
    assert_eq!(
        EffectRecord::decode(&before).unwrap().encode().unwrap(),
        before
    );
    let plan = fixture.plan(
        fixture.request("terminal-original", EffectManagementAction::Terminate),
        None,
    );
    fixture.mutate(plan, EffectManagementEvidence::Administrator, 105);
    let managed = fixture.record_bytes();
    assert!(managed.starts_with(b"LER\0\x02"));
    let mut wrong = managed.clone();
    wrong[4] = 1;
    assert_eq!(
        EffectRecord::decode(&wrong),
        Err(AuthorityError::UnsupportedFormat)
    );
    wrong[4] = 99;
    assert_eq!(
        effect_record_version(&wrong),
        Err(AuthorityError::UnsupportedFormat)
    );
    assert_eq!(
        EffectRecord::decode(&managed).unwrap().encode().unwrap(),
        managed
    );
}

#[test]
fn missing_reserved_disposition_or_orphaned_management_receipt_rejects_readiness() {
    let fixture = Fixture::new(StoreLimits::default());
    let plan = fixture.plan(
        fixture.request("protected-original", EffectManagementAction::Terminate),
        None,
    );
    let key = codec::reservation(&codec::operation(plan.request())).unwrap();
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value: None }],
        })
        .unwrap();
    assert_eq!(
        DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()),
        Err(StoreError::Corrupt)
    );
    assert_eq!(fixture.record().disposition(), Disposition::Pending);
    let mut unsupported = plan.encode().unwrap();
    unsupported[4] = 2;
    assert_eq!(
        EffectManagementPlan::decode(&unsupported),
        Err(EffectManagementError::Store(StoreError::UnsupportedFormat))
    );
}

#[test]
fn abandoned_management_plans_have_a_finite_per_effect_capacity() {
    let fixture = Fixture::new(StoreLimits::default());
    for index in 0..128 {
        fixture.plan(
            fixture.request(
                &format!("bounded-plan-{index}"),
                EffectManagementAction::Terminate,
            ),
            None,
        );
    }
    let view = fixture.store().snapshot().unwrap();
    assert_eq!(
        EffectManagementCatalog::prepare_plan(
            &view,
            fixture.epoch,
            fixture.request("over-capacity", EffectManagementAction::Terminate),
            time(104),
            None
        )
        .err(),
        Some(EffectManagementError::Capacity)
    );
    DispatchCatalog::validate_view(&view).unwrap();
    assert_eq!(fixture.record().attempts(), 0);
}
