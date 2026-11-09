use super::*;
use crate::inbox_scope::{InboxScope, PreparedInboxScope};

fn scope() -> InboxScope {
    InboxScope {
        tenant: "alpha".into(),
        namespace: "orders".into(),
        incarnation: 1,
        processing_scope: "primary".into(),
        provider: "private-nats".into(),
        stream: "orders".into(),
        stream_created: "2026-01-01T00:00:00Z".into(),
    }
}

#[test]
fn first_source_is_atomic_quota_charged_and_survives_reopen() {
    let mut fixture = Fixture::new();
    fixture.install(&[quota("alpha")]);
    fixture
        .store()
        .apply(domain::create(fixture.store(), "alpha", "orders"))
        .unwrap();
    let view = fixture.store().snapshot().unwrap();
    let before = inspect(&view, &TenantId("alpha".into()))
        .unwrap()
        .unwrap()
        .usage;
    let first = PreparedInboxScope::prepare(&view, &scope()).unwrap();
    let mut other_origin = scope();
    other_origin.provider = "other-provider".into();
    let competing = PreparedInboxScope::prepare(&view, &other_origin).unwrap();
    assert!(!first.existing());
    let batch = first.into_batch();
    let stored = batch
        .mutations
        .iter()
        .find(|row| row.key.key.starts_with(b"inbox-source-v1\0"))
        .unwrap();
    let bytes = stored.value.as_ref().unwrap();
    assert!(matches!(
        crate::inbox_scope::census_contribution(&view, &stored.key, bytes),
        Ok(TenantCensusContribution::Usage { .. })
    ));
    let mut wrong_key = stored.key.clone();
    wrong_key.key.push(1);
    assert_eq!(
        crate::inbox_scope::validate_row(&wrong_key, bytes),
        Err(StoreError::Corrupt)
    );
    let mut malformed = bytes.clone();
    malformed.push(b' ');
    assert_eq!(
        crate::inbox_scope::validate_row(&stored.key, &malformed),
        Err(StoreError::Corrupt)
    );
    let mut changed_origin = bytes.clone();
    let offset = changed_origin
        .windows(b"private-nats".len())
        .position(|part| part == b"private-nats")
        .unwrap();
    changed_origin[offset] = b'P';
    assert_eq!(
        crate::inbox_scope::validate_row(&stored.key, &changed_origin),
        Err(StoreError::Corrupt)
    );
    drop(view);
    fixture.store().apply(batch).unwrap();
    assert_eq!(
        fixture.store().apply(competing.into_batch()),
        Err(StoreError::Conflict)
    );
    fixture.reopen();
    let view = fixture.store().snapshot().unwrap();
    census::verify(&view, &[quota("alpha")]).unwrap();
    let after = inspect(&view, &TenantId("alpha".into()))
        .unwrap()
        .unwrap()
        .usage;
    assert_eq!(after.metadata_rows, before.metadata_rows + 1);
    assert!(after.metadata_bytes > before.metadata_bytes);
    let same = PreparedInboxScope::prepare(&view, &scope()).unwrap();
    assert!(same.existing());
    let mut changed = scope();
    changed.stream_created = "2026-02-01T00:00:00Z".into();
    assert!(matches!(
        PreparedInboxScope::prepare(&view, &changed),
        Err(StoreError::Conflict)
    ));
    changed = scope();
    changed.provider = "other-provider".into();
    assert!(matches!(
        PreparedInboxScope::prepare(&view, &changed),
        Err(StoreError::Conflict)
    ));
    drop(view);
    fixture.store().apply(same.into_batch()).unwrap();
}

#[test]
fn final_fence_and_quota_refuse_publication() {
    let fixture = Fixture::new();
    let mut limited = quota("alpha");
    limited.limits.metadata_rows = 4;
    fixture.install(&[limited]);
    fixture
        .store()
        .apply(domain::create(fixture.store(), "alpha", "orders"))
        .unwrap();
    let view = fixture.store().snapshot().unwrap();
    let plan = PreparedInboxScope::prepare(&view, &scope()).unwrap();
    drop(view);
    assert_eq!(
        fixture
            .store()
            .apply_fenced(plan.into_batch(), || Err("revoked")),
        Err(FencedStoreError::Fence("revoked"))
    );
    let view = fixture.store().snapshot().unwrap();
    let first = PreparedInboxScope::prepare(&view, &scope()).unwrap();
    drop(view);
    fixture.store().apply(first.into_batch()).unwrap();
    let view = fixture.store().snapshot().unwrap();
    let mut other = scope();
    other.processing_scope = "approved-replay".into();
    assert!(matches!(
        PreparedInboxScope::prepare(&view, &other),
        Err(StoreError::Capacity)
    ));
}
