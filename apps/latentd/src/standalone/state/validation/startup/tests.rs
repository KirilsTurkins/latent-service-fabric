use super::*;
use latent_core::{transaction_contract::Value, StateNamespaceId, TenantId};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, RowMutation, StoreLimits},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        NamespaceQuota,
    },
    session::{SessionLimits, StateMode, StateScope, StateSession},
    tenant::{TenantRecord, TenantUsage},
};
use std::{fs::OpenOptions, path::Path};

pub(in crate::standalone::state) fn quota(tenant: &str) -> TenantQuota {
    TenantQuota {
        tenant: TenantId(tenant.into()),
        limits: TenantUsage {
            state_keys: 256,
            state_bytes: 4 * 1024 * 1024,
            tombstone_keys: 256,
            tombstone_bytes: 4 * 1024 * 1024,
            result_rows: 128,
            result_bytes: 16 * 1024 * 1024,
            effect_rows: 128,
            effect_bytes: 8 * 1024 * 1024,
            payload_bytes: 4 * 1024 * 1024,
            recovery_bytes: 8 * 1024 * 1024,
            metadata_rows: 1024,
            metadata_bytes: 1024 * 1024,
        },
    }
}
pub(in crate::standalone::state) fn selected(quotas: Vec<TenantQuota>) -> StartupValidation {
    StartupValidation {
        quotas,
        deadline: Instant::now() + Duration::from_secs(30),
    }
}
fn open(path: &Path, create: bool) -> EmbeddedStore {
    EmbeddedStore::open_file(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(create)
            .open(path)
            .unwrap(),
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap()
}
fn install(store: &EmbeddedStore, quotas: &[TenantQuota]) {
    let prepared = tenant::prepare_install(&store.snapshot().unwrap(), quotas).unwrap();
    prepared.publish(store, || Ok::<(), ()>(())).unwrap();
}
fn put(store: &EmbeddedStore, key: RowKey, value: Option<Vec<u8>>) {
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation { key, value }],
        })
        .unwrap();
}
fn namespace(store: &EmbeddedStore, tenant: &str) {
    let prepared = NamespaceCatalog::new()
        .prepare(
            store,
            NamespaceOperationContext {
                tenant: TenantId(tenant.into()),
                actor: "operator".into(),
                operation_id: "create-business".into(),
            },
            &NamespaceMutation::Create {
                id: StateNamespaceId("business".into()),
                state_schema: format!("sha256:{}", "1".repeat(64)),
                quota: NamespaceQuota::default(),
            },
            0,
        )
        .unwrap();
    store.apply(prepared.batch).unwrap();
}
fn state(store: &EmbeddedStore, tenant: &str) {
    let view = store.snapshot().unwrap();
    let mut session = StateSession::open(
        &view,
        StateScope {
            tenant: TenantId(tenant.into()),
            namespace: StateNamespaceId("business".into()),
            incarnation: 1,
            state_schema: format!("sha256:{}", "1".repeat(64)),
            entity: None,
            mode: StateMode::Command,
        },
        SessionLimits::default(),
        |_, _| Ok(()),
    )
    .unwrap();
    session
        .put(
            &view,
            b"count".to_vec(),
            Value {
                bytes: 7u64.to_le_bytes().to_vec(),
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            |_, _| Ok(()),
        )
        .unwrap();
    let plan = session.seal(&view, |_, _| Ok(())).unwrap();
    let pins = plan.pins();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch, pins).unwrap();
    drop(view);
    store.apply(batch).unwrap();
}

#[test]
fn installed_startup_census_preserves_real_state_and_exact_tenant_records_across_reopen() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("startup.redb");
    let store = open(&path, true);
    let quotas = vec![quota("alpha"), quota("beta")];
    selected(quotas.clone())
        .validate(&store.snapshot().unwrap())
        .unwrap();
    assert!(store
        .snapshot()
        .unwrap()
        .get(&tenant::guard_key())
        .unwrap()
        .is_none());
    install(&store, &quotas);
    for tenant in ["alpha", "beta"] {
        namespace(&store, tenant);
        state(&store, tenant);
    }
    DispatchCatalog::begin_exclusive_epoch(
        &store,
        latent_effects::authority::EffectTime {
            unix_millis: 1_000,
            continuity_proven: true,
        },
        None,
    )
    .unwrap();
    let view = store.snapshot().unwrap();
    let original = quotas
        .iter()
        .map(|quota| {
            let key = tenant::quota_key(&quota.tenant).unwrap();
            (key.clone(), view.get(&key).unwrap().unwrap())
        })
        .collect::<Vec<_>>();
    selected(quotas.clone()).validate(&view).unwrap();
    drop(view);
    drop(store);
    let reopened = open(&path, false);
    selected(quotas)
        .validate(&reopened.snapshot().unwrap())
        .unwrap();
    for (key, bytes) in original {
        assert_eq!(reopened.snapshot().unwrap().get(&key).unwrap(), Some(bytes));
    }
}

#[test]
fn installed_startup_refuses_omitted_changed_or_foreign_declarations_without_repair() {
    let root = tempfile::tempdir().unwrap();
    let store = open(&root.path().join("declarations.redb"), true);
    let quota = quota("alpha");
    install(&store, std::slice::from_ref(&quota));
    let original = tenant::inspect(&store.snapshot().unwrap(), &quota.tenant).unwrap();
    let mut changed = quota.clone();
    changed.limits.metadata_bytes += 1;
    for quotas in [
        vec![],
        vec![changed],
        vec![self::quota("beta")],
        vec![quota.clone(), self::quota("beta")],
    ] {
        assert_eq!(
            selected(quotas).validate(&store.snapshot().unwrap()),
            Err(StoreError::UnsupportedFormat)
        );
        assert_eq!(
            tenant::inspect(&store.snapshot().unwrap(), &quota.tenant).unwrap(),
            original
        );
    }
}

#[test]
fn installed_startup_refuses_valid_counter_drift_unknown_rows_and_orphaned_accounting() {
    let root = tempfile::tempdir().unwrap();
    let store = open(&root.path().join("drift.redb"), true);
    let quota = quota("alpha");
    install(&store, std::slice::from_ref(&quota));
    let key = tenant::quota_key(&quota.tenant).unwrap();
    let original = store.snapshot().unwrap().get(&key).unwrap().unwrap();
    let mut drift = TenantRecord::decode(&original).unwrap();
    drift.usage.metadata_rows += 1;
    put(&store, key.clone(), Some(drift.encode().unwrap()));
    assert_eq!(
        selected(vec![quota.clone()]).validate(&store.snapshot().unwrap()),
        Err(StoreError::Corrupt)
    );
    put(&store, key, Some(original.clone()));
    let unknown = RowKey {
        family: Family::Maintenance,
        key: b"unreviewed-control-v1\0".to_vec(),
    };
    put(&store, unknown.clone(), Some(b"foreign".to_vec()));
    assert_eq!(
        selected(vec![quota.clone()]).validate(&store.snapshot().unwrap()),
        Err(StoreError::UnsupportedFormat)
    );
    put(&store, unknown, None);
    put(&store, tenant::guard_key(), None);
    assert!(selected(vec![quota.clone()])
        .validate(&store.snapshot().unwrap())
        .is_err());
    assert!(selected(vec![])
        .validate(&store.snapshot().unwrap())
        .is_err());
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .get(&tenant::quota_key(&quota.tenant).unwrap())
            .unwrap(),
        Some(original)
    );
    assert!(store
        .snapshot()
        .unwrap()
        .get(&tenant::guard_key())
        .unwrap()
        .is_none());
}

#[test]
fn empty_bootstrap_and_fresh_setup_refuse_legacy_business_and_expired_startup() {
    let root = tempfile::tempdir().unwrap();
    let store = open(&root.path().join("legacy.redb"), true);
    selected(vec![])
        .validate(&store.snapshot().unwrap())
        .unwrap();
    namespace(&store, "alpha");
    super::super::validate_view(&store.snapshot().unwrap()).unwrap();
    for quotas in [vec![], vec![quota("alpha")]] {
        assert_eq!(
            selected(quotas).validate(&store.snapshot().unwrap()),
            Err(StoreError::UnsupportedFormat)
        );
    }
    assert!(store
        .snapshot()
        .unwrap()
        .get(&tenant::guard_key())
        .unwrap()
        .is_none());
    let expired = StartupValidation {
        quotas: vec![quota("alpha")],
        deadline: Instant::now().checked_sub(Duration::from_secs(1)).unwrap(),
    };
    assert_eq!(
        expired.validate(&store.snapshot().unwrap()),
        Err(StoreError::Unavailable)
    );
}

#[test]
fn settings_bound_startup_refuses_ambiguous_declarations_and_nonfinite_cutoffs() {
    let root = tempfile::tempdir().unwrap();
    let config = crate::config::state::StateConfig {
        format_version: 1,
        create_if_missing: true,
        configuration_epoch: 1,
        clock_checkpoint: root.path().join("clock.json"),
        state_root: None,
        operations: vec![],
        tenant_quotas: vec![],
        recovery_selections: vec![],
    };
    let mut settings = crate::config::state::derive(&config).unwrap();
    settings.tenant_quotas = vec![quota("alpha")];
    assert!(startup(&settings, Instant::now() + Duration::from_secs(30)).is_ok());
    for cutoff in [
        Instant::now().checked_sub(Duration::from_secs(1)).unwrap(),
        Instant::now() + Duration::from_secs(61),
    ] {
        assert!(startup(&settings, cutoff).is_err());
    }
    settings.tenant_quotas.push(quota("alpha"));
    assert!(startup(&settings, Instant::now() + Duration::from_secs(30)).is_err());
    settings.tenant_quotas = vec![quota("alpha")];
    settings.tenant_quotas[0].limits.metadata_bytes = 1;
    assert!(startup(&settings, Instant::now() + Duration::from_secs(30)).is_err());
}
