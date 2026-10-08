use super::*;
use crate::tenant::{self, GlobalMetadataAllowance, TenantCensus, TenantQuota, TenantUsage};
use latent_core::TenantId;

fn verify(store: &EmbeddedStore, quota: &TenantQuota) -> tenant::TenantCensusReport {
    let view = store.snapshot().unwrap();
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

#[test]
fn restored_tenant_accounting_uses_original_quota_and_charges_new_paused_history_with_reopen() {
    let quota = TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            state_keys: 2,
            state_bytes: 4096,
            tombstone_keys: 2,
            tombstone_bytes: 4096,
            metadata_rows: 16,
            metadata_bytes: 64 * 1024,
            ..TenantUsage::default()
        },
    };
    let fixture = crate::recovery::snapshot::tests::fixture_with_tenant(Some(quota.clone()));
    verify(&fixture.store, &quota);
    let original = tenant::inspect(&fixture.store.snapshot().unwrap(), &quota.tenant)
        .unwrap()
        .unwrap();
    let (bytes, snapshot) = export(&fixture);
    retire_after_backup(&fixture);
    let current = fixture.store.snapshot().unwrap();
    let plan = RestorePlan::prepare(
        &current,
        snapshot.clone(),
        &request(&current, &snapshot),
        |_, _| Ok(()),
    )
    .unwrap();
    let (directory, restored) = destination(StoreLimits::default());
    plan.execute(
        &mut Cursor::new(bytes),
        &restored,
        deadline(),
        |key, bytes| validate_row(&current, key, bytes),
        |view| closure(view, &fixture.metadata),
    )
    .unwrap();
    let report = verify(&restored, &quota);
    assert_eq!(report.global_rows, 2);
    let counter = tenant::inspect(&restored.snapshot().unwrap(), &quota.tenant)
        .unwrap()
        .unwrap();
    assert_eq!(counter.quota, original.quota);
    assert_eq!(counter.usage.state_bytes, original.usage.state_bytes);
    assert_eq!(
        counter.usage.metadata_rows,
        original.usage.metadata_rows + 1
    );
    assert_eq!(counter.generation, original.generation + 1);
    let view = restored.snapshot().unwrap();
    assert_eq!(
        crate::recovery::require_ready(&view),
        Err(StoreError::Unavailable)
    );
    let history = NamespaceHistory::decode(
        &view
            .scan(
                Family::Namespace,
                crate::namespace::history::HISTORY_PREFIX,
                1,
                4096,
            )
            .unwrap()[0]
            .1,
    )
    .unwrap();
    assert_eq!(history.incarnation, 1);
    assert_eq!(history.status, HistoryStatus::ReconciliationRequired);
    assert_eq!(history.epochs.recovery, 2);
    drop(view);
    drop(restored);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(directory.path().join("restored.redb"))
        .unwrap();
    let reopened = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
    assert_eq!(verify(&reopened, &quota), report);
    assert_eq!(
        tenant::inspect(&reopened.snapshot().unwrap(), &quota.tenant)
            .unwrap()
            .unwrap(),
        counter
    );
    assert_eq!(
        crate::recovery::require_ready(&reopened.snapshot().unwrap()),
        Err(StoreError::Unavailable)
    );
}
