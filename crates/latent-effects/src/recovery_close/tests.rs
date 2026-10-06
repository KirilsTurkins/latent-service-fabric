use super::*;
use crate::{
    dispatch::AttemptReceipt,
    dispatch_store::{effect_payload_key, initial_due_mutation},
    payload::{tests as payload_fixture, PayloadRecord},
};
use latent_state::{
    embedded::{EmbeddedStore, FencedStoreError, StoreLimits},
    namespace::{
        history::{history_key, NamespaceHistory},
        namespace_record_key, NamespaceQuota, NamespaceRecord, NamespaceStatus,
    },
    recovery::guard_key,
};
use std::fs::OpenOptions;

mod compatibility;
mod safety;
mod tenant;

fn time(value: u64) -> EffectTime {
    EffectTime {
        unix_millis: value,
        continuity_proven: true,
    }
}
struct Fixture {
    _directory: tempfile::TempDir,
    store: EmbeddedStore,
    scope: CloseScope,
    effect: String,
}
impl Fixture {
    fn new(uncertain: bool) -> Self {
        Self::configured(uncertain, None)
    }
    fn configured(uncertain: bool, quota: Option<latent_state::tenant::TenantQuota>) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let store = open(directory.path());
        let payload = payload_fixture::value();
        let effect = "a".repeat(64);
        let authority = payload_fixture::authority(&payload, &effect);
        let scope = CloseScope {
            tenant: authority.scope().tenant.clone(),
            namespace: authority.scope().namespace.clone(),
            incarnation: authority.scope().incarnation,
        };
        let tenant = TenantId(scope.tenant.clone());
        let id = StateNamespaceId(scope.namespace.clone());
        if let Some(quota) = quota {
            latent_state::tenant::prepare_install(&store.snapshot().unwrap(), &[quota])
                .unwrap()
                .publish(&store, || Ok::<(), StoreError>(()))
                .unwrap();
        }
        let mut namespace = NamespaceRecord::create(
            tenant.clone(),
            id.clone(),
            format!("sha256:{}", "1".repeat(64)),
            NamespaceQuota::default(),
        )
        .unwrap();
        namespace.version.incarnation = scope.incarnation;
        let namespace_key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&tenant, &id).unwrap(),
        };
        let record = EffectRecord::committed(&authority).unwrap();
        let due = initial_due_mutation(&authority).unwrap();
        let mut initial = AtomicBatch {
            expectations: vec![ExpectedRow {
                key: namespace_key.clone(),
                value: None,
            }],
            mutations: vec![
                RowMutation {
                    key: namespace_key.clone(),
                    value: Some(namespace.encode().unwrap()),
                },
                RowMutation {
                    key: effect_row_key(&effect).unwrap(),
                    value: Some(record.encode().unwrap()),
                },
                RowMutation {
                    key: effect_payload_key(&effect).unwrap(),
                    value: Some(
                        PayloadRecord::new(&authority, payload)
                            .unwrap()
                            .encode()
                            .unwrap(),
                    ),
                },
                due.clone(),
            ],
        };
        latent_state::tenant::prepare_metadata_update(
            &store.snapshot().unwrap(),
            &tenant,
            &initial,
        )
        .unwrap()
        .append_to(&mut initial)
        .unwrap();
        store.apply(initial).unwrap();
        let epoch = DispatchCatalog::begin_exclusive_epoch(&store, time(100), None).unwrap();
        if uncertain {
            let due = DueRecord::decode(&due.key, due.value.as_deref().unwrap()).unwrap();
            let claimed = DispatchCatalog::claim(&store, epoch, &due, time(101)).unwrap();
            DispatchCatalog::begin_send(&store, epoch, &claimed.attempt, time(102)).unwrap();
            DispatchCatalog::complete(
                &store,
                epoch,
                &claimed.attempt,
                AttemptReceipt {
                    disposition: Disposition::Uncertain,
                    reason: "remote-response-lost".into(),
                    provider_receipt: None,
                    observed_at_millis: 103,
                },
                None,
                time(103),
            )
            .unwrap();
        }
        Self::paused(&store, namespace_key, namespace);
        Self {
            _directory: directory,
            store,
            scope,
            effect,
        }
    }
    fn paused(store: &EmbeddedStore, namespace_key: RowKey, mut namespace: NamespaceRecord) {
        let tenant = namespace.tenant.clone();
        let id = namespace.id.clone();
        let incarnation = namespace.version.incarnation;
        namespace.status = NamespaceStatus::Quiescing;
        let history = NamespaceHistory::initial(&namespace);
        let restored = history.restored_after(&history).unwrap();
        let history_key = history_key(&tenant, &id, incarnation).unwrap();
        let mut paused = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: namespace_key.clone(),
                    value: store.snapshot().unwrap().get(&namespace_key).unwrap(),
                },
                ExpectedRow {
                    key: history_key.clone(),
                    value: None,
                },
            ],
            mutations: vec![
                RowMutation {
                    key: namespace_key,
                    value: Some(namespace.encode().unwrap()),
                },
                RowMutation {
                    key: history_key,
                    value: Some(restored.encode().unwrap()),
                },
            ],
        };
        latent_state::tenant::prepare_metadata_update(&store.snapshot().unwrap(), &tenant, &paused)
            .unwrap()
            .append_to(&mut paused)
            .unwrap();
        store.apply(paused).unwrap();
        let guard = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
        store.apply(guard.prepare_staging().unwrap()).unwrap();
        store.apply(guard.prepare_completed().unwrap()).unwrap();
    }
    fn plan(&self) -> ClosePlan {
        inspect(
            &self.store.snapshot().unwrap(),
            self.scope.clone(),
            "operator".into(),
            "close-1".into(),
            vec![self.effect.clone()],
            "explicitly abandon uncertain restored work".into(),
        )
        .unwrap()
    }
    fn prepare(&self, plan: &ClosePlan) -> PreparedClose {
        prepare(
            &self.store.snapshot().unwrap(),
            plan,
            &self.scope,
            "operator",
            "close-1",
            plan.digest().unwrap(),
            time(110),
        )
        .unwrap()
    }
    fn row(&self, key: &RowKey) -> Vec<u8> {
        self.store.snapshot().unwrap().get(key).unwrap().unwrap()
    }
}
fn open(directory: &std::path::Path) -> EmbeddedStore {
    EmbeddedStore::open_file(
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(directory.join("recovery.redb"))
            .unwrap(),
        StoreLimits::default(),
    )
    .unwrap()
}
#[test]
fn inspected_close_is_read_only_and_old_v1_bytes_and_attempts_remain_exact() {
    let fixture = Fixture::new(true);
    let key = effect_row_key(&fixture.effect).unwrap();
    let before = fixture.row(&key);
    let guard = fixture.row(&guard_key());
    let record = EffectRecord::decode(&before).unwrap();
    assert!(before.starts_with(b"LER\0\x01"));
    assert_eq!(record.encode().unwrap(), before);
    let value: serde_json::Value = serde_json::from_slice(&before[5..]).unwrap();
    assert!(value.get("recovery_close").is_none());
    let plan = fixture.plan();
    assert_eq!(
        plan.effects[0].original_digest,
        Sha256::digest(&before).as_slice()
    );
    assert_eq!(ClosePlan::decode(&plan.encode().unwrap()).unwrap(), plan);
    assert_eq!(fixture.row(&key), before);
    assert_eq!(fixture.row(&guard_key()), guard);
    assert_eq!(record.attempts(), 1);
}
#[test]
fn atomic_close_keeps_original_payload_history_result_and_guard_and_receipt_replays() {
    let fixture = Fixture::new(true);
    let plan = fixture.plan();
    let key = effect_row_key(&fixture.effect).unwrap();
    let original = EffectRecord::decode(&fixture.row(&key)).unwrap();
    let payload_key = effect_payload_key(&fixture.effect).unwrap();
    let payload = fixture.row(&payload_key);
    let guard = fixture.row(&guard_key());
    let history = DispatchCatalog::history_page(
        &fixture.store.snapshot().unwrap(),
        &fixture.effect,
        None,
        16,
        65536,
    )
    .unwrap()
    .rows;
    let prepared = fixture.prepare(&plan);
    let receipt = prepared.receipt.encode().unwrap();
    assert!(!prepared.replay);
    fixture
        .store
        .apply_fenced(prepared.batch, || Ok::<(), StoreError>(()))
        .unwrap();
    let closed = EffectRecord::decode(&fixture.row(&key)).unwrap();
    assert!(fixture.row(&key).starts_with(b"LER\0\x03"));
    assert_eq!(closed.disposition(), Disposition::DeadLettered);
    assert_eq!(
        closed.authority().unwrap().encode().unwrap(),
        original.authority().unwrap().encode().unwrap()
    );
    assert_eq!(closed.attempts(), original.attempts());
    assert_eq!(closed.latest(), original.latest());
    assert_eq!(closed.history_sequence(), original.history_sequence());
    assert_eq!(fixture.row(&payload_key), payload);
    assert_eq!(fixture.row(&guard_key()), guard);
    assert_eq!(
        DispatchCatalog::history_page(
            &fixture.store.snapshot().unwrap(),
            &fixture.effect,
            None,
            16,
            65536
        )
        .unwrap()
        .rows,
        history
    );
    DispatchCatalog::validate_view(&fixture.store.snapshot().unwrap()).unwrap();
    assert_eq!(
        DispatchCatalog::retention_rows(&fixture.store.snapshot().unwrap(), &fixture.effect).err(),
        Some(StoreError::UnsupportedFormat)
    );
    let replay = fixture.prepare(&plan);
    assert!(replay.replay);
    assert!(replay.batch.mutations.is_empty());
    assert_eq!(replay.receipt.encode().unwrap(), receipt);
    fixture
        .store
        .apply_fenced(replay.batch, || Ok::<(), StoreError>(()))
        .unwrap();
    assert_eq!(EffectRecord::decode(&fixture.row(&key)).unwrap(), closed);
}
#[test]
fn wrong_actor_scope_operation_acknowledgement_clock_and_stale_rows_refuse_before_write() {
    let fixture = Fixture::new(true);
    let plan = fixture.plan();
    let key = effect_row_key(&fixture.effect).unwrap();
    let original = fixture.row(&key);
    let view = fixture.store.snapshot().unwrap();
    let mut wrong_scope = fixture.scope.clone();
    wrong_scope.tenant = "other".into();
    for (scope, actor, operation, ack, clock) in [
        (
            &wrong_scope,
            "operator",
            "close-1",
            plan.digest().unwrap(),
            time(110),
        ),
        (
            &fixture.scope,
            "other",
            "close-1",
            plan.digest().unwrap(),
            time(110),
        ),
        (
            &fixture.scope,
            "operator",
            "other",
            plan.digest().unwrap(),
            time(110),
        ),
        (&fixture.scope, "operator", "close-1", [9; 32], time(110)),
        (
            &fixture.scope,
            "operator",
            "close-1",
            plan.digest().unwrap(),
            EffectTime {
                unix_millis: 110,
                continuity_proven: false,
            },
        ),
        (
            &fixture.scope,
            "operator",
            "close-1",
            plan.digest().unwrap(),
            time(99),
        ),
    ] {
        assert!(prepare(&view, &plan, scope, actor, operation, ack, clock).is_err());
    }
    let mut stale = plan.clone();
    stale.effects[0].original_digest = [8; 32];
    assert!(prepare(
        &view,
        &stale,
        &fixture.scope,
        "operator",
        "close-1",
        stale.digest().unwrap(),
        time(110)
    )
    .is_err());
    assert_eq!(fixture.row(&key), original);
}
#[test]
fn revoked_real_writer_fence_preserves_the_original_pending_work_and_operation_identity() {
    let fixture = Fixture::new(false);
    let plan = fixture.plan();
    let key = effect_row_key(&fixture.effect).unwrap();
    let before = fixture.row(&key);
    let prepared = fixture.prepare(&plan);
    assert!(matches!(
        fixture
            .store
            .apply_fenced(prepared.batch, || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    ));
    assert_eq!(fixture.row(&key), before);
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .get(&plan.receipt_key().unwrap())
        .unwrap()
        .is_none());
    let prepared = fixture.prepare(&plan);
    fixture
        .store
        .apply_fenced(prepared.batch, || Ok::<(), StoreError>(()))
        .unwrap();
    assert_eq!(
        DispatchCatalog::due_page(&fixture.store.snapshot().unwrap(), 120, None, 16, 65536).err(),
        Some(StoreError::Unavailable)
    );
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .scan(
            Family::Maintenance,
            crate::dispatch_store::DUE_PREFIX,
            16,
            65536
        )
        .unwrap()
        .is_empty());
    let mut changed = plan.clone();
    changed.reason = "different acknowledged plan".into();
    assert!(prepare(
        &fixture.store.snapshot().unwrap(),
        &changed,
        &fixture.scope,
        "operator",
        "close-1",
        changed.digest().unwrap(),
        time(120)
    )
    .is_err());
}
#[test]
fn v2_marker_requires_its_exact_linked_receipt_and_cannot_relax_v1_dead_letter_rules() {
    let fixture = Fixture::new(true);
    let plan = fixture.plan();
    let key = effect_row_key(&fixture.effect).unwrap();
    let prepared = fixture.prepare(&plan);
    fixture.store.apply(prepared.batch).unwrap();
    for legacy in [1, 2] {
        let mut closed = fixture.row(&key);
        closed[4] = legacy;
        assert!(EffectRecord::decode(&closed).is_err());
    }
    let before = EffectRecord::decode(&fixture.row(&key)).unwrap();
    let digest = before.recovery_close_digest().unwrap();
    assert_ne!(digest, [0; 32]);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: plan.receipt_key().unwrap(),
                value: None,
            }],
        })
        .unwrap();
    assert!(DispatchCatalog::validate_view(&fixture.store.snapshot().unwrap()).is_err());
}
