use super::*;
use crate::tenant::{self, GlobalMetadataAllowance, TenantCensus, TenantQuota, TenantUsage};

fn quota() -> TenantQuota {
    TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            state_keys: 1,
            state_bytes: 4096,
            tombstone_keys: 1,
            tombstone_bytes: 4096,
            metadata_rows: 16,
            metadata_bytes: 64 * 1024,
            ..TenantUsage::default()
        },
    }
}
fn fixture(quota: TenantQuota) -> Fixture {
    fixture_with_tenant(
        u64::MAX.to_le_bytes().to_vec(),
        NamespaceQuota::default(),
        Some(quota),
    )
}
fn census(f: &Fixture, quota: &TenantQuota) -> tenant::TenantCensusReport {
    let view = f.store.snapshot().unwrap();
    let mut census = TenantCensus::capture(
        &view,
        std::slice::from_ref(quota),
        GlobalMetadataAllowance {
            rows: 5,
            bytes: 256 * 1024,
        },
        deadline(),
    )
    .unwrap();
    super::super::super::snapshot::visit_view(&view, deadline(), |_, key, bytes| {
        census.observe(key, bytes, tenant::census_contribution(&view, key, bytes)?)
    })
    .unwrap();
    census.finish().unwrap()
}
fn counter(f: &Fixture) -> tenant::TenantRecord {
    tenant::inspect(&f.store.snapshot().unwrap(), &f.request.scope.tenant)
        .unwrap()
        .unwrap()
}

#[test]
fn installed_tenant_migration_and_resume_charge_actual_changed_rows_with_restart_and_read_only_replay(
) {
    let quota = quota();
    let mut f = fixture(quota.clone());
    census(&f, &quota);
    let original = counter(&f);
    let stage = prepare(&f);
    f.store.apply(stage.into_batch()).unwrap();
    let staged = counter(&f);
    assert_eq!(staged.usage.state_bytes, original.usage.state_bytes);
    assert_eq!(staged.usage.metadata_rows, original.usage.metadata_rows + 2);
    census(&f, &quota);
    drop(f.store);
    f.store = open(f.root.path(), false);
    let complete = prepare(&f);
    f.store.apply(complete.into_batch()).unwrap();
    let completed = counter(&f);
    assert_eq!(completed.usage.state_bytes, original.usage.state_bytes + 4);
    census(&f, &quota);
    let active = activate(&f);
    assert_actual_tagged_value(&f, &active);
    census(&f, &quota);
    let before_replay = counter(&f);
    let replay = prepare(&f);
    assert_eq!(replay.action(), MigrationAction::Replay);
    let batch = replay.into_batch();
    assert!(batch.mutations.is_empty());
    f.store.apply(batch).unwrap();
    assert_eq!(counter(&f), before_replay);
    drop(f.store);
    f.store = open(f.root.path(), false);
    assert_eq!(counter(&f), before_replay);
    census(&f, &quota);
}

#[test]
fn installed_tenant_capacity_refuses_migration_before_paused_history_or_progress_publication() {
    let observed = fixture(quota());
    let original_bytes = counter(&observed).usage.state_bytes;
    let mut tight = quota();
    tight.limits.state_bytes = original_bytes;
    let f = fixture(tight);
    let before = counter(&f);
    let view = f.store.snapshot().unwrap();
    let checkpoint = checkpoint(&f, &view);
    assert!(matches!(
        AggregateMigrationPlan::prepare(
            &view,
            &f.request,
            &checkpoint,
            &f.schema,
            MigrationAction::Stage,
            deadline(),
            |_, _, _| Ok(())
        ),
        Err(StoreError::Capacity)
    ));
    assert!(view
        .get(&f.request.progress_key().unwrap())
        .unwrap()
        .is_none());
    let current =
        NamespaceRecoveryView::capture(&view, &f.request.scope.tenant, &f.request.scope.namespace)
            .unwrap();
    assert_eq!(current.history.status, HistoryStatus::Ready);
    assert_eq!(counter(&f), before);
}
