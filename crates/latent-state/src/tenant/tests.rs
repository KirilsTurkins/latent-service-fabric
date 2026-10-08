use super::*;
use crate::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, FencedStoreError, RowMutation, StoreLimits,
};
use std::{
    fs::OpenOptions,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
static NEXT_FILE: AtomicU64 = AtomicU64::new(1);
mod census;
mod domain;

fn quota(name: &str) -> TenantQuota {
    TenantQuota {
        tenant: TenantId(name.into()),
        limits: TenantUsage {
            state_keys: 2,
            state_bytes: 4096,
            tombstone_keys: 2,
            tombstone_bytes: 4096,
            result_rows: 2,
            result_bytes: 16 * 1024,
            effect_rows: 2,
            effect_bytes: 16 * 1024,
            payload_bytes: 16 * 1024,
            recovery_bytes: 4096,
            metadata_rows: 8,
            metadata_bytes: 32 * 1024,
        },
    }
}
struct Fixture {
    store: Option<EmbeddedStore>,
    path: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "lsf-tenant397-{}-{}.redb",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed)
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .unwrap();
        let store = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        Self {
            store: Some(store),
            path,
        }
    }
    fn store(&self) -> &EmbeddedStore {
        self.store.as_ref().unwrap()
    }
    fn reopen(&mut self) {
        drop(self.store.take());
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .unwrap();
        self.store = Some(EmbeddedStore::open_file(file, StoreLimits::default()).unwrap());
    }
    fn install(&self, quotas: &[TenantQuota]) -> [u8; 32] {
        let view = self.store().snapshot().unwrap();
        let plan = prepare_install(&view, quotas).unwrap();
        drop(view);
        plan.publish(self.store(), || Ok::<_, ()>(())).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        drop(self.store.take());
        std::fs::remove_file(&self.path).unwrap();
    }
}
fn row(family: Family, key: &[u8], value: &[u8]) -> AtomicBatch {
    let key = RowKey {
        family,
        key: key.to_vec(),
    };
    AtomicBatch {
        expectations: vec![ExpectedRow {
            key: key.clone(),
            value: None,
        }],
        mutations: vec![RowMutation {
            key,
            value: Some(value.to_vec()),
        }],
    }
}
fn snapshot_bytes(batch: &AtomicBatch) -> Vec<u8> {
    format!("{batch:?}").into_bytes()
}
fn assert_stale_counter_merge(view: &ReadView, tenant: &TenantId, old: &PreparedTenantUpdate) {
    let mut fresh = AtomicBatch::default();
    prepare_update(view, tenant, TenantDelta::default())
        .unwrap()
        .append_to(&mut fresh)
        .unwrap();
    let unchanged = snapshot_bytes(&fresh);
    assert_eq!(old.append_to(&mut fresh), Err(StoreError::Conflict));
    assert_eq!(snapshot_bytes(&fresh), unchanged);
}

#[test]
fn exact_tenant_installation_is_bounded_immutable_and_never_infers_namespace_limits() {
    let mut fixture = Fixture::new();
    let quotas = [quota("alpha"), quota("beta")];
    let digest = fixture.install(&quotas);
    assert_eq!(
        configuration_digest(&[quotas[1].clone(), quotas[0].clone()]).unwrap(),
        digest
    );
    let view = fixture.store().snapshot().unwrap();
    assert_eq!(require_installation(&view, &quotas).unwrap(), digest);
    assert!(!prepare_install(&view, &quotas).unwrap().is_new());
    let mut changed = quotas.clone();
    changed[0].limits.state_keys += 1;
    assert!(matches!(
        prepare_install(&view, &changed),
        Err(StoreError::UnsupportedFormat)
    ));
    assert!(configuration_digest(&[quotas[0].clone(), quotas[0].clone()]).is_err());
    assert!(configuration_digest(&vec![quota("same"); MAXIMUM_TENANTS + 1]).is_err());
    let record = inspect(&view, &quotas[0].tenant).unwrap().unwrap();
    assert_eq!(record.usage.metadata_rows, 1);
    assert_eq!(
        record.usage.metadata_bytes,
        row_charge(
            &quota_key(&quotas[0].tenant).unwrap(),
            &record.encode().unwrap()
        )
        .unwrap()
    );
    drop(view);
    fixture.reopen();
    assert_eq!(
        require_installation(&fixture.store().snapshot().unwrap(), &quotas).unwrap(),
        digest
    );
}

#[test]
fn install_final_native_fence_refuses_business_race_and_review_revocation_without_partial_setup() {
    let fixture = Fixture::new();
    let quotas = [quota("alpha")];
    let view = fixture.store().snapshot().unwrap();
    let plan = prepare_install(&view, &quotas).unwrap();
    drop(view);
    fixture
        .store()
        .apply(row(Family::State, b"existing", b"original"))
        .unwrap();
    assert_eq!(
        plan.publish(fixture.store(), || Ok::<_, ()>(())),
        Err(FencedStoreError::Store(StoreError::UnsupportedFormat))
    );
    assert!(fixture
        .store()
        .snapshot()
        .unwrap()
        .get(&guard_key())
        .unwrap()
        .is_none());
    let another = Fixture::new();
    let view = another.store().snapshot().unwrap();
    let plan = prepare_install(&view, &quotas).unwrap();
    drop(view);
    assert_eq!(
        plan.publish(another.store(), || Err("revoked")),
        Err(FencedStoreError::Fence("revoked"))
    );
    assert!(another
        .store()
        .snapshot()
        .unwrap()
        .get(&guard_key())
        .unwrap()
        .is_none());
    assert!(another
        .store()
        .snapshot()
        .unwrap()
        .get(&quota_key(&quotas[0].tenant).unwrap())
        .unwrap()
        .is_none());
}

#[test]
fn missing_changed_or_malformed_tenant_record_refuses_instead_of_auto_upgrading_legacy() {
    let fixture = Fixture::new();
    let quota = quota("alpha");
    let tenant = quota.tenant.clone();
    fixture.install(std::slice::from_ref(&quota));
    assert_eq!(
        inspect(
            &fixture.store().snapshot().unwrap(),
            &TenantId("unknown".into())
        ),
        Err(StoreError::UnsupportedFormat)
    );
    let key = quota_key(&tenant).unwrap();
    let view = fixture.store().snapshot().unwrap();
    let original = view.get(&key).unwrap().unwrap();
    let record = TenantRecord::decode(&original).unwrap();
    for hostile in [
        vec![],
        vec![0; RECORD_BYTES],
        original[..RECORD_BYTES - 1].to_vec(),
    ] {
        assert!(TenantRecord::decode(&hostile).is_err());
    }
    let mut corrupted = original.clone();
    corrupted[100] ^= 1;
    assert_eq!(TenantRecord::decode(&corrupted), Err(StoreError::Corrupt));
    let mut changed = record;
    changed.quota.limits.state_keys += 1;
    let changed = changed.encode().unwrap();
    drop(view);
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(original),
            }],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(changed),
            }],
        })
        .unwrap();
    assert_eq!(
        inspect(&fixture.store().snapshot().unwrap(), &tenant),
        Err(StoreError::UnsupportedFormat)
    );
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value: None }],
        })
        .unwrap();
    assert_eq!(
        inspect(&fixture.store().snapshot().unwrap(), &tenant),
        Err(StoreError::UnsupportedFormat)
    );
    let legacy = Fixture::new();
    let view = legacy.store().snapshot().unwrap();
    assert_eq!(inspect(&view, &tenant).unwrap(), None);
    let mut old = row(Family::State, b"legacy", b"original");
    let update = prepare_update(&view, &tenant, TenantDelta::default()).unwrap();
    assert!(update.is_legacy());
    update.append_to(&mut old).unwrap();
    assert_eq!(old.mutations.len(), 1);
    drop(view);
    legacy.install(&[quota]);
    assert_eq!(legacy.store().apply(old), Err(StoreError::Conflict));
}

#[test]
fn same_atomic_envelope_merges_state_and_command_counter_once_and_rejects_overflow_without_partial_rows(
) {
    let mut fixture = Fixture::new();
    let tenant = TenantId("alpha".into());
    fixture.install(&[quota("alpha")]);
    let view = fixture.store().snapshot().unwrap();
    let before = inspect(&view, &tenant).unwrap().unwrap();
    let mut batch = row(Family::State, b"synthetic-state-owner", b"body");
    prepare_update(
        &view,
        &tenant,
        TenantDelta {
            added: TenantUsage {
                state_keys: 1,
                state_bytes: 100,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut batch)
    .unwrap();
    prepare_update(
        &view,
        &tenant,
        TenantDelta {
            added: TenantUsage {
                result_rows: 1,
                result_bytes: 512,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut batch)
    .unwrap();
    let unchanged = snapshot_bytes(&batch);
    let excessive = prepare_update(
        &view,
        &tenant,
        TenantDelta {
            added: TenantUsage {
                state_keys: 2,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap();
    assert_eq!(excessive.append_to(&mut batch), Err(StoreError::Capacity));
    assert_eq!(snapshot_bytes(&batch), unchanged);
    assert_eq!(
        batch
            .mutations
            .iter()
            .filter(|row| row.key == quota_key(&tenant).unwrap())
            .count(),
        1
    );
    drop(view);
    fixture.store().apply(batch).unwrap();
    fixture.reopen();
    let actual = inspect(&fixture.store().snapshot().unwrap(), &tenant)
        .unwrap()
        .unwrap();
    assert_eq!(actual.generation, before.generation + 1);
    assert_eq!(actual.usage.state_keys, 1);
    assert_eq!(actual.usage.result_rows, 1);
}

#[test]
fn noisy_tenant_saturation_and_stale_counter_fence_do_not_consume_another_tenant_or_partial_business_commit(
) {
    let fixture = Fixture::new();
    let alpha = TenantId("alpha".into());
    let beta = TenantId("beta".into());
    fixture.install(&[quota("alpha"), quota("beta")]);
    let view = fixture.store().snapshot().unwrap();
    let mut stale = row(Family::State, b"stale", b"never");
    prepare_update(
        &view,
        &alpha,
        TenantDelta {
            added: TenantUsage {
                state_keys: 1,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut stale)
    .unwrap();
    let old_capture = prepare_update(&view, &alpha, TenantDelta::default()).unwrap();
    let mut full = row(Family::State, b"full", b"owner");
    prepare_update(
        &view,
        &alpha,
        TenantDelta {
            added: TenantUsage {
                state_keys: 2,
                state_bytes: 100,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut full)
    .unwrap();
    drop(view);
    fixture.store().apply(full).unwrap();
    assert_eq!(fixture.store().apply(stale), Err(StoreError::Conflict));
    let view = fixture.store().snapshot().unwrap();
    assert_stale_counter_merge(&view, &alpha, &old_capture);
    assert!(matches!(
        prepare_update(
            &view,
            &alpha,
            TenantDelta {
                added: TenantUsage {
                    state_keys: 1,
                    ..TenantUsage::default()
                },
                ..TenantDelta::default()
            }
        ),
        Err(StoreError::Capacity)
    ));
    assert!(view
        .get(&RowKey {
            family: Family::State,
            key: b"stale".to_vec()
        })
        .unwrap()
        .is_none());
    let mut other = row(Family::State, b"beta", b"owner");
    prepare_update(
        &view,
        &beta,
        TenantDelta {
            added: TenantUsage {
                state_keys: 1,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut other)
    .unwrap();
    drop(view);
    fixture.store().apply(other).unwrap();
    assert_eq!(
        inspect(&fixture.store().snapshot().unwrap(), &alpha)
            .unwrap()
            .unwrap()
            .usage
            .state_keys,
        2
    );
    assert_eq!(
        inspect(&fixture.store().snapshot().unwrap(), &beta)
            .unwrap()
            .unwrap()
            .usage
            .state_keys,
        1
    );
}

#[test]
fn finite_management_metadata_is_encoded_charged_in_the_same_counter_and_refuses_missing_originals()
{
    let fixture = Fixture::new();
    let tenant = TenantId("alpha".into());
    let mut quota = quota("alpha");
    quota.limits.metadata_rows = 2;
    fixture.install(&[quota]);
    let view = fixture.store().snapshot().unwrap();
    let before = inspect(&view, &tenant).unwrap().unwrap();
    let mut batch = row(
        Family::Namespace,
        b"ns-state-op-v1\0closed-original",
        &[3; 8192],
    );
    let charge = row_charge(
        &batch.mutations[0].key,
        batch.mutations[0].value.as_deref().unwrap(),
    )
    .unwrap();
    let update = prepare_metadata_update(&view, &tenant, &batch).unwrap();
    update.append_to(&mut batch).unwrap();
    drop(view);
    fixture.store().apply(batch).unwrap();
    let view = fixture.store().snapshot().unwrap();
    let actual = inspect(&view, &tenant).unwrap().unwrap();
    assert_eq!(actual.usage.metadata_rows, 2);
    assert_eq!(
        actual.usage.metadata_bytes,
        before.usage.metadata_bytes + charge
    );
    let too_many = row(Family::Namespace, b"ns-state-op-v1\0second", b"body");
    assert!(matches!(
        prepare_metadata_update(&view, &tenant, &too_many),
        Err(StoreError::Capacity)
    ));
    let mut absent_original = too_many.clone();
    absent_original.expectations.clear();
    assert!(matches!(
        prepare_metadata_update(&view, &tenant, &absent_original),
        Err(StoreError::Corrupt)
    ));
    let oversized = row(Family::Namespace, b"ns-state-op-v1\0too-large", &[0; 8193]);
    assert!(matches!(
        prepare_metadata_update(&view, &tenant, &oversized),
        Err(StoreError::Capacity)
    ));
    assert!(view.get(&too_many.mutations[0].key).unwrap().is_none());
}

#[test]
fn checked_terminal_capacity_release_survives_reopen_and_never_underflows_a_protective_identity() {
    let mut fixture = Fixture::new();
    let tenant = TenantId("alpha".into());
    fixture.install(&[quota("alpha")]);
    let view = fixture.store().snapshot().unwrap();
    let mut batch = AtomicBatch::default();
    prepare_update(
        &view,
        &tenant,
        TenantDelta {
            added: TenantUsage {
                result_rows: 2,
                result_bytes: 2048,
                effect_rows: 1,
                effect_bytes: 2048,
                payload_bytes: 128,
                recovery_bytes: 1024,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut batch)
    .unwrap();
    drop(view);
    fixture.store().apply(batch).unwrap();
    fixture.reopen();
    let view = fixture.store().snapshot().unwrap();
    let mut next = AtomicBatch::default();
    prepare_update(
        &view,
        &tenant,
        TenantDelta {
            removed: TenantUsage {
                effect_rows: 1,
                effect_bytes: 2048,
                payload_bytes: 128,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )
    .unwrap()
    .append_to(&mut next)
    .unwrap();
    drop(view);
    fixture.store().apply(next).unwrap();
    fixture.reopen();
    let view = fixture.store().snapshot().unwrap();
    let remaining = inspect(&view, &tenant).unwrap().unwrap();
    assert_eq!(remaining.usage.result_rows, 2);
    assert_eq!(remaining.usage.recovery_bytes, 1024);
    assert_eq!(remaining.usage.effect_rows, 0);
    assert!(matches!(
        prepare_update(
            &view,
            &tenant,
            TenantDelta {
                removed: TenantUsage {
                    effect_rows: 1,
                    ..TenantUsage::default()
                },
                ..TenantDelta::default()
            }
        ),
        Err(StoreError::Corrupt)
    ));
}

#[test]
fn typed_accounting_reads_and_setup_existence_checks_refuse_oversized_bytes_before_copying_values()
{
    let fixture = Fixture::new();
    fixture
        .store()
        .apply(row(
            Family::State,
            b"existing-large-body",
            &vec![0; 128 * 1024],
        ))
        .unwrap();
    let view = fixture.store().snapshot().unwrap();
    assert!(view.contains_prefix(Family::State, b"existing-").unwrap());
    assert!(!view.contains_prefix(Family::State, b"missing-").unwrap());
    assert_eq!(
        view.get_bounded(
            &RowKey {
                family: Family::State,
                key: b"existing-large-body".to_vec()
            },
            1024
        ),
        Err(StoreError::Corrupt)
    );
    assert!(matches!(
        prepare_install(&view, &[quota("alpha")]),
        Err(StoreError::UnsupportedFormat)
    ));
    drop(view);
    let installed = Fixture::new();
    installed.install(&[quota("alpha")]);
    let view = installed.store().snapshot().unwrap();
    let mut rewritten = AtomicBatch::default();
    rewritten.mutations.push(RowMutation {
        key: guard_key(),
        value: Some(vec![0; GUARD_BYTES + 1]),
    });
    let update = prepare_update(&view, &TenantId("alpha".into()), TenantDelta::default()).unwrap();
    assert_eq!(update.append_to(&mut rewritten), Err(StoreError::Corrupt));
    drop(view);
    installed.store().apply(rewritten).unwrap();
    assert_eq!(
        inspect(
            &installed.store().snapshot().unwrap(),
            &TenantId("alpha".into())
        ),
        Err(StoreError::Corrupt)
    );
}
