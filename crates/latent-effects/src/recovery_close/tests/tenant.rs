//! The installed lower-domain quota is real; namespace/history and the new
//! receipt are charged by their original owners in the same physical batches.
use super::*;
use latent_state::tenant::{self, TenantQuota, TenantRecord};

fn fixture(rows: u64) -> Fixture {
    let payload = payload_fixture::value();
    let authority = payload_fixture::authority(&payload, &"a".repeat(64));
    Fixture::configured(
        false,
        Some(TenantQuota {
            tenant: TenantId(authority.scope().tenant.clone()),
            limits: TenantUsage {
                metadata_rows: rows,
                metadata_bytes: 64 * 1024,
                ..TenantUsage::default()
            },
        }),
    )
}
fn counter(fixture: &Fixture) -> TenantRecord {
    tenant::inspect(
        &fixture.store.snapshot().unwrap(),
        &TenantId(fixture.scope.tenant.clone()),
    )
    .unwrap()
    .unwrap()
}

#[test]
fn close_receipt_charges_installed_metadata_once_and_replay_keeps_original_counter_generation() {
    let fixture = fixture(4);
    let plan = fixture.plan();
    let before = counter(&fixture);
    assert_eq!(before.usage.metadata_rows, 3);
    let prepared = fixture.prepare(&plan);
    let receipt_key = plan.receipt_key().unwrap();
    let charge = row_charge(&receipt_key, &prepared.receipt.encode().unwrap()).unwrap();
    fixture.store.apply(prepared.batch).unwrap();
    let closed = counter(&fixture);
    assert_eq!(closed.quota, before.quota);
    assert_eq!(closed.generation, before.generation + 1);
    let mut expected = before.usage;
    expected.metadata_rows += 1;
    expected.metadata_bytes += charge;
    assert_eq!(closed.usage, expected);
    let receipt = fixture.row(&receipt_key);
    let replay = fixture.prepare(&plan);
    assert!(replay.replay && replay.batch.mutations.is_empty());
    fixture.store.apply(replay.batch).unwrap();
    assert_eq!(counter(&fixture), closed);
    assert_eq!(fixture.row(&receipt_key), receipt);
}

#[test]
fn exhausted_installed_metadata_refuses_close_without_using_retained_work_capacity() {
    let fixture = fixture(3);
    let plan = fixture.plan();
    let before = counter(&fixture);
    let key = effect_row_key(&fixture.effect).unwrap();
    let record = fixture.row(&key);
    assert_eq!(
        prepare(
            &fixture.store.snapshot().unwrap(),
            &plan,
            &fixture.scope,
            "operator",
            "close-1",
            plan.digest().unwrap(),
            time(110)
        )
        .err(),
        Some(StoreError::Capacity)
    );
    assert_eq!(counter(&fixture), before);
    assert_eq!(fixture.row(&key), record);
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .get(&plan.receipt_key().unwrap())
        .unwrap()
        .is_none());
}
