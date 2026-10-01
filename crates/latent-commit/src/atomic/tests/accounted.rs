use super::*;
use latent_state::{
    embedded::StoreError,
    namespace::catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
    tenant::{self, TenantQuota, TenantUsage},
};

pub(super) fn setup(effects: u64) -> (tempfile::TempDir, EmbeddedStore, EffectAuthorityOwner) {
    let dir = tempfile::tempdir().unwrap();
    let store = open(&dir.path().join("state.redb"));
    let quotas = [TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            state_keys: 8,
            state_bytes: 64 * 1024,
            tombstone_keys: 8,
            tombstone_bytes: 64 * 1024,
            result_rows: 64,
            result_bytes: 16 * 1024 * 1024,
            effect_rows: effects,
            effect_bytes: 16 * 1024 * 1024,
            payload_bytes: 16 * 1024 * 1024,
            recovery_bytes: 8 * 1024 * 1024,
            metadata_rows: 64,
            metadata_bytes: 256 * 1024,
        },
    }];
    let view = store.snapshot().unwrap();
    let plan = tenant::prepare_install(&view, &quotas).unwrap();
    drop(view);
    plan.publish(&store, || Ok::<_, ()>(())).unwrap();
    let namespace = NamespaceCatalog::new()
        .prepare(
            &store,
            NamespaceOperationContext {
                tenant: TenantId("tenant".into()),
                actor: "operator".into(),
                operation_id: "create".into(),
            },
            &NamespaceMutation::Create {
                id: StateNamespaceId("aggregate".into()),
                state_schema: schema(),
                quota: NamespaceQuota::default(),
            },
            0,
        )
        .unwrap();
    store.apply(namespace.batch).unwrap();
    (dir, store, effect_owner())
}
pub(super) fn usage(store: &EmbeddedStore) -> latent_state::tenant::TenantRecord {
    tenant::inspect(&store.snapshot().unwrap(), &TenantId("tenant".into()))
        .unwrap()
        .unwrap()
}
pub(super) fn installed_codec(
    view: &latent_state::embedded::ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<(), StoreError> {
    if *key == tenant::guard_key() || key.key.starts_with(tenant::QUOTA_PREFIX) {
        tenant::validate_row(view, key, bytes)
    } else {
        foreign_codec(view, key, bytes)
    }
}
fn assert_command_totals(view: &latent_state::embedded::ReadView, aggregate: TenantUsage) {
    let key = writer::usage_row_key("tenant", "aggregate", 1).unwrap();
    let original = writer::Usage::decode(&view.get(&key).unwrap().unwrap()).unwrap();
    assert_eq!(aggregate.result_rows, original.results);
    assert_eq!(aggregate.result_bytes, original.result_bytes);
    assert_eq!(aggregate.effect_rows, original.effects);
    assert_eq!(aggregate.effect_bytes, original.effect_bytes);
    assert_eq!(aggregate.payload_bytes, original.payload_bytes);
    assert_eq!(aggregate.recovery_bytes, original.recovery_reserved);
}

#[test]
fn real_state_command_result_and_effect_envelope_advances_one_aggregate_cas_and_reopens_exact_totals(
) {
    let (dir, store, effects) = setup(8);
    let admitted = claim(&store, input("accounted"));
    let before = usage(&store);
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        admitted,
        Some(stage(&view)),
        vec![intent()],
        value(b"original result"),
        &effects,
        time(101),
    )
    .unwrap();
    let record = confirm(envelope, &store, &effects);
    drop(view);
    let after = usage(&store);
    assert_eq!(after.generation, before.generation + 1);
    assert_eq!(after.usage.state_keys, 1);
    assert_eq!(after.usage.effect_rows, 1);
    assert_eq!(after.usage.metadata_rows, 4);
    drop(store);
    let reopened = open(&dir.path().join("state.redb"));
    assert_eq!(usage(&reopened), after);
    let view = reopened.snapshot().unwrap();
    assert_command_totals(&view, after.usage);
    validate_view(&view, installed_codec).unwrap();
    let (original, result) = inspect(&view, &record.key, time(102), permission).unwrap();
    assert_eq!(original, record);
    assert_eq!(result.unwrap().value(), Some(&value(b"original result")));
}

#[test]
fn real_effect_aggregate_saturation_keeps_pending_owner_and_all_business_families_unchanged() {
    let (_dir, store, effects) = setup(0);
    let admitted = claim(&store, input("refused-effect"));
    let before = usage(&store);
    let view = store.snapshot().unwrap();
    let old_namespace = view.get(&namespace_key()).unwrap();
    let result = CompleteEnvelope::success(
        &view,
        admitted,
        Some(stage(&view)),
        vec![intent()],
        value(b"never committed"),
        &effects,
        time(101),
    );
    assert!(matches!(result, Err(AtomicError::Limit)));
    drop(view);
    assert_eq!(usage(&store), before);
    let view = store.snapshot().unwrap();
    assert_eq!(view.get(&namespace_key()).unwrap(), old_namespace);
    assert!(!view.contains_prefix(Family::State, b"state-v1\0").unwrap());
    assert!(!view.contains_prefix(Family::Outbox, b"").unwrap());
    let (record, result) =
        inspect(&view, &input("refused-effect").key, time(102), permission).unwrap();
    assert_eq!(record.outcome(), Outcome::Pending);
    assert!(result.is_none());
    validate_view(&view, installed_codec).unwrap();
}

#[test]
fn actual_response_expiry_reduces_tenant_bytes_but_keeps_original_effect_payload_and_recovery_pins()
{
    let (dir, store, effects) = setup(8);
    let admitted = claim(&store, input("expired-tenant-body"));
    let view = store.snapshot().unwrap();
    let record = confirm(
        CompleteEnvelope::success(
            &view,
            admitted,
            None,
            vec![intent()],
            value(&[5; 512]),
            &effects,
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    let before = usage(&store);
    let owner = ResultMaintenanceOwner::default();
    let observation = |now, elapsed| MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: elapsed,
    };
    owner
        .anchor(&store, None, observation(1000, 0), |record| {
            permission(CommandAccess::Replay, record)
        })
        .unwrap();
    owner
        .step(&store, observation(1100, 100), |record| {
            permission(CommandAccess::Replay, record)
        })
        .unwrap();
    let after = usage(&store);
    assert_eq!(after.generation, before.generation + 1);
    assert!(after.usage.result_bytes < before.usage.result_bytes);
    assert_eq!(after.usage.result_rows, before.usage.result_rows);
    assert_eq!(after.usage.effect_rows, before.usage.effect_rows);
    assert_eq!(after.usage.effect_bytes, before.usage.effect_bytes);
    assert_eq!(after.usage.payload_bytes, before.usage.payload_bytes);
    assert_eq!(after.usage.recovery_bytes, before.usage.recovery_bytes);
    drop(store);
    let reopened = open(&dir.path().join("state.redb"));
    assert_eq!(usage(&reopened), after);
    let view = reopened.snapshot().unwrap();
    assert_command_totals(&view, after.usage);
    let (original, result) = inspect(&view, &record.key, time(1100), permission).unwrap();
    assert!(result.is_none());
    assert_eq!(original.source, record.source);
    assert_eq!(original.effect_ids(), record.effect_ids());
    validate_view(&view, installed_codec).unwrap();
}
