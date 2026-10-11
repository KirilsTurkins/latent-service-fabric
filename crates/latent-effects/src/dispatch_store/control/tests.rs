//! The original control CAS with installed global capacity, no operator grant.
use super::*;
use crate::dispatch_store::DispatchCatalog;
use latent_core::TenantId;
use latent_state::{
    embedded::StoreLimits,
    tenant::{
        self, TenantCensus, TenantCensusContribution, TenantQuota, TenantUsage,
        INSTALLED_GLOBAL_ALLOWANCE,
    },
};
use std::{
    fs::OpenOptions,
    path::Path,
    time::{Duration, Instant},
};

fn open(path: &Path) -> EmbeddedStore {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .unwrap();
    EmbeddedStore::open_file(file, StoreLimits::default()).unwrap()
}
fn quota() -> TenantQuota {
    TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            metadata_rows: 4,
            metadata_bytes: 16 * 1024,
            ..TenantUsage::default()
        },
    }
}
fn install(store: &EmbeddedStore) {
    let view = store.snapshot().unwrap();
    let install = tenant::prepare_install(&view, &[quota()]).unwrap();
    drop(view);
    install.publish(store, || Ok::<_, ()>(())).unwrap();
}
fn seed_owner(store: &EmbeddedStore) {
    DispatchCatalog::begin_exclusive_epoch(
        store,
        EffectTime {
            unix_millis: 100,
            continuity_proven: true,
        },
        None,
    )
    .unwrap();
}
fn request(operation: &str, revision: u64) -> DispatcherControlRequest {
    DispatcherControlRequest::new(
        "operator-tenant".into(),
        "operator".into(),
        operation.into(),
        DispatcherControlGeneration::new(1, revision).unwrap(),
        DispatcherControlAction::Pause,
    )
    .unwrap()
}
fn plan(store: &EmbeddedStore, request: &DispatcherControlRequest) -> PlannedControl {
    ControlCatalog::plan(
        store,
        request,
        false,
        EffectTime {
            unix_millis: 100,
            continuity_proven: true,
        },
    )
    .unwrap()
}
fn publish(store: &EmbeddedStore, request: &DispatcherControlRequest) -> DispatcherControlReceipt {
    let PlannedControl::Write { batch, receipt } = plan(store, request) else {
        panic!("expected fresh original control")
    };
    store.apply(batch).unwrap();
    receipt
}
fn census(store: &EmbeddedStore) -> latent_state::tenant::TenantCensusReport {
    let view = store.snapshot().unwrap();
    let mut census = TenantCensus::capture(
        &view,
        &[quota()],
        INSTALLED_GLOBAL_ALLOWANCE,
        Instant::now() + Duration::from_secs(20),
    )
    .unwrap();
    let page = view
        .scan_after(Family::Maintenance, b"", None, 128, 256 * 1024)
        .unwrap();
    assert!(page.resume.is_none());
    for (key, bytes) in page.rows {
        let contribution = match tenant::census_contribution(&view, &key, &bytes) {
            Err(StoreError::UnsupportedFormat) => {
                DispatchCatalog::tenant_census_contribution(&view, &key, &bytes)
            }
            other => other,
        }
        .unwrap();
        census.observe(&key, &bytes, contribution).unwrap();
    }
    census.finish().unwrap()
}

#[test]
fn installed_global_control_limit_keeps_recovery_slots_replays_read_only_and_reopens() {
    let dir = tempfile::tempdir().unwrap();
    let store = open(&dir.path().join("global.redb"));
    install(&store);
    seed_owner(&store);
    let original = tenant::inspect(&store.snapshot().unwrap(), &quota().tenant)
        .unwrap()
        .unwrap();
    let first = request("control-0", 1);
    let original_receipt = publish(&store, &first);
    // Six closed singleton slots include the original StoreIdentity, alongside
    // the installation/recovery/retention/dispatcher owners. They stay reserved
    // even when this small fixture has only three physically occupied slots.
    for i in 1..58 {
        publish(&store, &request(&format!("control-{i}"), i + 1));
    }
    assert!(matches!(
        ControlCatalog::plan(
            &store,
            &request("overflow", 59),
            false,
            EffectTime {
                unix_millis: 100,
                continuity_proven: true
            }
        ),
        Err(DispatcherControlError::Store(StoreError::Capacity))
    ));
    let report = census(&store);
    // Three reserved singleton slots are not occupied yet; all 58 receipts and
    // three actual singleton controls fit the same fixed allowance.
    assert_eq!(report.global_rows, 61);
    assert!(report.global_bytes <= INSTALLED_GLOBAL_ALLOWANCE.bytes);
    assert_eq!(
        tenant::inspect(&store.snapshot().unwrap(), &quota().tenant).unwrap(),
        Some(original.clone())
    );
    assert!(
        matches!(plan(&store, &first), PlannedControl::Replay(receipt) if receipt == original_receipt)
    );
    assert_eq!(census(&store), report);
    drop(store);
    let store = open(&dir.path().join("global.redb"));
    ControlCatalog::validate_view(&store.snapshot().unwrap()).unwrap();
    assert_eq!(
        ControlCatalog::lookup(&store.snapshot().unwrap(), &first).unwrap(),
        Some(original_receipt)
    );
    assert_eq!(census(&store), report);
    assert_eq!(
        tenant::inspect(&store.snapshot().unwrap(), &quota().tenant).unwrap(),
        Some(original)
    );
}

#[test]
fn control_original_cas_refuses_concurrent_write_and_legacy_plan_after_installation() {
    let dir = tempfile::tempdir().unwrap();
    let store = open(&dir.path().join("stale.redb"));
    seed_owner(&store);
    let PlannedControl::Write { batch: legacy, .. } = plan(&store, &request("legacy", 1)) else {
        panic!()
    };
    install(&store);
    assert_eq!(store.apply(legacy), Err(StoreError::Conflict));
    let second = request("stale-second", 1);
    let PlannedControl::Write { batch: stale, .. } = plan(&store, &second) else {
        panic!()
    };
    publish(&store, &request("first", 1));
    assert_eq!(store.apply(stale), Err(StoreError::Conflict));
    assert_eq!(
        ControlCatalog::lookup(&store.snapshot().unwrap(), &second).unwrap(),
        None
    );
    let report = census(&store);
    assert_eq!(report.global_rows, 4);
}

#[test]
fn installed_control_capacity_scan_requires_actual_closed_receipt_codec_and_key() {
    let dir = tempfile::tempdir().unwrap();
    let store = open(&dir.path().join("closed.redb"));
    install(&store);
    seed_owner(&store);
    let first = request("first", 1);
    publish(&store, &first);
    let view = store.snapshot().unwrap();
    let key = receipt_key(&first);
    let mut bytes = view.get(&key).unwrap().unwrap();
    assert!(matches!(
        DispatchCatalog::tenant_census_contribution(&view, &key, &bytes).unwrap(),
        TenantCensusContribution::Global
    ));
    bytes[FORMAT.len()] = b'!';
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(bytes),
            }],
        })
        .unwrap();
    assert!(matches!(
        ControlCatalog::plan(
            &store,
            &request("next", 2),
            false,
            EffectTime {
                unix_millis: 100,
                continuity_proven: true
            }
        ),
        Err(DispatcherControlError::Store(StoreError::Corrupt))
    ));
    assert_eq!(
        ControlCatalog::lookup(&store.snapshot().unwrap(), &request("next", 2)).unwrap(),
        None
    );
}
