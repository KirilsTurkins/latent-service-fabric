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

#[test]
fn ordered_census_captures_all_source_rows_and_refuses_partial_reuse() {
    let fixture = Fixture::new();
    fixture.install(&[quota("alpha")]);
    fixture
        .store()
        .apply(domain::create(fixture.store(), "alpha", "orders"))
        .unwrap();
    let view = fixture.store().snapshot().unwrap();
    assert_eq!(
        census::verify(&view, &[quota("alpha")])
            .unwrap()
            .inbox_custody,
        None
    );
    let first = PreparedInboxScope::prepare(&view, &scope()).unwrap();
    drop(view);
    fixture.store().apply(first.into_batch()).unwrap();
    let view = fixture.store().snapshot().unwrap();
    let first_watermark = census::verify(&view, &[quota("alpha")])
        .unwrap()
        .inbox_custody
        .unwrap();
    assert_eq!(first_watermark.generation, 1);
    let first_page = view
        .scan_after(Family::Maintenance, b"inbox-source-v1\0", None, 8, 8192)
        .unwrap();
    let mut first_addition = crate::inbox_scope::InboxScopeAddition::new(&scope()).unwrap();
    for (key, bytes) in &first_page.rows {
        first_addition.observe(key, bytes).unwrap();
    }
    assert_eq!(first_addition.finish(None), Ok(first_watermark));
    let mut another = scope();
    another.processing_scope = "approved-replay".into();
    let second = PreparedInboxScope::prepare(&view, &another).unwrap();
    drop(view);
    fixture.store().apply(second.into_batch()).unwrap();
    let view = fixture.store().snapshot().unwrap();
    let watermark = census::verify(&view, &[quota("alpha")])
        .unwrap()
        .inbox_custody
        .unwrap();
    assert_eq!(watermark.generation, 2);
    assert_ne!(watermark.digest, first_watermark.digest);
    assert_eq!(
        census::verify_addition(&view, &[quota("alpha")], &another, Some(first_watermark))
            .unwrap()
            .inbox_custody,
        Some(watermark)
    );
    assert!(matches!(
        census::verify_addition(&view, &[quota("alpha")], &another, None),
        Err(StoreError::Conflict)
    ));
    let identity = crate::store_identity::StoreIdentity::new("census-store".into()).unwrap();
    let checkpoint =
        crate::store_identity::ExternalCheckpoint::initial(identity.clone(), 1, 1, 100)
            .unwrap()
            .advance_inbox_custody(first_watermark)
            .unwrap()
            .advance_inbox_custody(watermark)
            .unwrap();
    assert_eq!(
        checkpoint.check_store_with_inbox_custody(&identity, 1, 100, first_watermark),
        Err(StoreError::Conflict)
    );
    assert_eq!(
        checkpoint.check_store_with_inbox_custody(&identity, 1, 100, watermark),
        Ok(())
    );
    let page = view
        .scan_after(Family::Maintenance, b"inbox-source-v1\0", None, 8, 8192)
        .unwrap();
    assert_eq!(page.rows.len(), 2);
    let mut addition = crate::inbox_scope::InboxScopeAddition::new(&another).unwrap();
    for (key, bytes) in &page.rows {
        addition.observe(key, bytes).unwrap();
    }
    assert_eq!(addition.finish(Some(first_watermark)), Ok(watermark));
    let mut wrong_before = crate::inbox_scope::InboxScopeAddition::new(&another).unwrap();
    for (key, bytes) in &page.rows {
        wrong_before.observe(key, bytes).unwrap();
    }
    assert_eq!(wrong_before.finish(None), Err(StoreError::Conflict));
    let mut absent = another.clone();
    absent.processing_scope = "unseen-scope".into();
    let mut absent = crate::inbox_scope::InboxScopeAddition::new(&absent).unwrap();
    for (key, bytes) in &page.rows {
        absent.observe(key, bytes).unwrap();
    }
    assert_eq!(
        absent.finish(Some(first_watermark)),
        Err(StoreError::Conflict)
    );
    let mut changed = another.clone();
    changed.provider = "different-provider".into();
    let mut changed = crate::inbox_scope::InboxScopeAddition::new(&changed).unwrap();
    assert!(page
        .rows
        .iter()
        .any(|(key, bytes)| changed.observe(key, bytes).is_err()));
    assert_eq!(
        changed.finish(Some(first_watermark)),
        Err(StoreError::Corrupt)
    );
    let mut left = crate::inbox_scope::InboxScopeInventory::default();
    let mut right = crate::inbox_scope::InboxScopeInventory::default();
    left.observe(&page.rows[0].0, &page.rows[0].1).unwrap();
    right.observe(&page.rows[1].0, &page.rows[1].1).unwrap();
    let left = left.finish().unwrap().unwrap();
    let right = right.finish().unwrap().unwrap();
    assert_eq!(left.generation, right.generation);
    assert_ne!(left.digest, right.digest);
    let mut inventory = crate::inbox_scope::InboxScopeInventory::default();
    inventory.observe(&page.rows[1].0, &page.rows[1].1).unwrap();
    assert_eq!(
        inventory.observe(&page.rows[0].0, &page.rows[0].1),
        Err(StoreError::Corrupt)
    );
    assert_eq!(inventory.finish(), Err(StoreError::Corrupt));
}

#[test]
fn late_source_transition_poison_cannot_be_ignored() {
    let fixture = Fixture::new();
    let quotas = [quota("alpha")];
    fixture.install(&quotas);
    let view = fixture.store().snapshot().unwrap();
    let mut census = TenantCensus::capture(
        &view,
        &quotas,
        GlobalMetadataAllowance {
            rows: 5,
            bytes: 256 * 1024,
        },
        std::time::Instant::now() + std::time::Duration::from_secs(20),
    )
    .unwrap();
    let key = guard_key();
    let bytes = view.get(&key).unwrap().unwrap();
    census
        .observe(
            &key,
            &bytes,
            census_contribution(&view, &key, &bytes).unwrap(),
        )
        .unwrap();
    assert_eq!(
        census.track_inbox_addition(&scope(), None),
        Err(StoreError::Conflict)
    );
    assert!(matches!(
        census.observe(&key, &bytes, TenantCensusContribution::Global),
        Err(StoreError::Corrupt)
    ));
    assert!(matches!(census.finish(), Err(StoreError::Corrupt)));
}
