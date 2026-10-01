use super::*;
use crate::{
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        NamespaceError, NamespaceQuota,
    },
    session::{SessionLimits, StateError, StateMode, StateScope, StateSession},
};
use latent_core::{transaction_contract::Value, StateNamespaceId};

pub(super) fn create(store: &EmbeddedStore, tenant: &str, namespace: &str) -> AtomicBatch {
    NamespaceCatalog::new()
        .prepare(
            store,
            NamespaceOperationContext {
                tenant: TenantId(tenant.into()),
                actor: "operator".into(),
                operation_id: format!("create-{namespace}"),
            },
            &NamespaceMutation::Create {
                id: StateNamespaceId(namespace.into()),
                state_schema: format!("sha256:{}", "1".repeat(64)),
                quota: NamespaceQuota::default(),
            },
            0,
        )
        .unwrap()
        .batch
}
pub(super) fn scope(tenant: &str, namespace: &str) -> StateScope {
    StateScope {
        tenant: TenantId(tenant.into()),
        namespace: StateNamespaceId(namespace.into()),
        incarnation: 1,
        state_schema: format!("sha256:{}", "1".repeat(64)),
        entity: None,
        mode: StateMode::Command,
    }
}
pub(super) fn state_write(
    store: &EmbeddedStore,
    scope: StateScope,
    body: Option<&[u8]>,
) -> Result<(), StateError> {
    let view = store.snapshot()?;
    let mut session = StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(()))?;
    if let Some(body) = body {
        session.put(
            &view,
            b"count".to_vec(),
            Value {
                bytes: body.to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: vec![],
            },
            |_, _| Ok(()),
        )?;
    } else {
        session.delete(&view, b"count".to_vec(), |_, _| Ok(()))?;
    }
    let plan = session.seal(&view, |_, _| Ok(()))?;
    let pins = plan.pins();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch, pins)?;
    drop(view);
    store.apply(batch)?;
    Ok(())
}
fn current(fixture: &Fixture, tenant: &str) -> TenantRecord {
    inspect(
        &fixture.store().snapshot().unwrap(),
        &TenantId(tenant.into()),
    )
    .unwrap()
    .unwrap()
}

#[test]
fn real_catalog_and_state_envelopes_share_one_tenant_ceiling_and_keep_other_tenants_independent() {
    let mut fixture = Fixture::new();
    let mut alpha = quota("alpha");
    alpha.limits.state_keys = 1;
    fixture.install(&[alpha, quota("beta")]);
    for (tenant, namespace) in [("alpha", "first"), ("alpha", "second"), ("beta", "first")] {
        fixture
            .store()
            .apply(create(fixture.store(), tenant, namespace))
            .unwrap();
    }
    assert_eq!(current(&fixture, "alpha").usage.metadata_rows, 5);
    state_write(fixture.store(), scope("alpha", "first"), Some(b"1")).unwrap();
    let before = current(&fixture, "alpha");
    assert_eq!(before.usage.state_keys, 1);
    assert_eq!(before.usage.metadata_rows, 6);
    assert_eq!(
        state_write(fixture.store(), scope("alpha", "second"), Some(b"2")),
        Err(StateError::Limit)
    );
    assert_eq!(current(&fixture, "alpha"), before);
    state_write(fixture.store(), scope("beta", "first"), Some(b"3")).unwrap();
    state_write(fixture.store(), scope("alpha", "first"), None).unwrap();
    let deleted = current(&fixture, "alpha");
    assert_eq!(
        (deleted.usage.state_keys, deleted.usage.state_bytes),
        (0, 0)
    );
    assert_eq!(deleted.usage.tombstone_keys, 1);
    assert!(deleted.usage.tombstone_bytes > 65);
    state_write(fixture.store(), scope("alpha", "second"), Some(b"2")).unwrap();
    fixture.reopen();
    let restored = current(&fixture, "alpha");
    assert_eq!(
        (restored.usage.state_keys, restored.usage.tombstone_keys),
        (1, 1)
    );
    assert_eq!(current(&fixture, "beta").usage.state_keys, 1);
}

#[test]
fn actual_catalog_metadata_refuses_saturation_before_namespace_or_operation_publication() {
    let fixture = Fixture::new();
    let mut alpha = quota("alpha");
    alpha.limits.metadata_rows = 2;
    fixture.install(&[alpha]);
    let before = current(&fixture, "alpha");
    let result = NamespaceCatalog::new().prepare(
        fixture.store(),
        NamespaceOperationContext {
            tenant: TenantId("alpha".into()),
            actor: "operator".into(),
            operation_id: "first-create".into(),
        },
        &NamespaceMutation::Create {
            id: StateNamespaceId("first".into()),
            state_schema: format!("sha256:{}", "1".repeat(64)),
            quota: NamespaceQuota::default(),
        },
        0,
    );
    assert!(matches!(result, Err(NamespaceError::Capacity)));
    assert_eq!(current(&fixture, "alpha"), before);
    assert!(!fixture
        .store()
        .snapshot()
        .unwrap()
        .contains_prefix(Family::Namespace, b"ns-")
        .unwrap());
}

#[test]
fn composed_legacy_guard_absence_keeps_generic_duplicate_rejection_and_install_race_cas() {
    let fixture = Fixture::new();
    let mut composed = create(fixture.store(), "alpha", "first");
    let second = create(fixture.store(), "alpha", "second");
    composed.expectations.extend(second.expectations);
    composed.mutations.extend(second.mutations);
    assert_eq!(
        composed
            .expectations
            .iter()
            .filter(|row| row.key == guard_key())
            .count(),
        2
    );
    let mut duplicate = composed.clone();
    duplicate
        .expectations
        .push(duplicate.expectations[0].clone());
    assert_eq!(fixture.store().apply(duplicate), Err(StoreError::Invalid));
    let mut duplicate = composed.clone();
    duplicate.mutations.push(duplicate.mutations[0].clone());
    assert_eq!(fixture.store().apply(duplicate), Err(StoreError::Invalid));
    fixture.install(&[quota("alpha")]);
    assert_eq!(fixture.store().apply(composed), Err(StoreError::Conflict));
    assert_eq!(current(&fixture, "alpha").usage.metadata_rows, 1);
    assert!(!fixture
        .store()
        .snapshot()
        .unwrap()
        .contains_prefix(Family::Namespace, b"ns-")
        .unwrap());
}
