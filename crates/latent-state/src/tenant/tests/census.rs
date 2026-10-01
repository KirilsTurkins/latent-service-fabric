use super::{domain, *};
use std::time::{Duration, Instant};

pub(crate) fn verify(
    view: &ReadView,
    quotas: &[TenantQuota],
) -> Result<TenantCensusReport, StoreError> {
    let mut census = TenantCensus::capture(
        view,
        quotas,
        GlobalMetadataAllowance {
            rows: 5,
            bytes: 256 * 1024,
        },
        Instant::now() + Duration::from_secs(20),
    )?;
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        let mut resume = None;
        loop {
            let page = view.scan_after(family, b"", resume.as_deref(), 128, 2 * 1024 * 1024)?;
            for (key, bytes) in page.rows {
                census.observe(&key, &bytes, census_contribution(view, &key, &bytes)?)?;
            }
            match page.resume {
                Some(next) => resume = Some(next),
                None => break,
            }
        }
    }
    census.finish()
}

#[test]
fn actual_startup_census_reconstructs_state_tombstones_and_metadata_across_tenants_and_reopen() {
    let mut fixture = Fixture::new();
    let quotas = [quota("alpha"), quota("beta")];
    fixture.install(&quotas);
    for tenant in ["alpha", "beta"] {
        fixture
            .store()
            .apply(domain::create(fixture.store(), tenant, "business"))
            .unwrap();
        domain::state_write(
            fixture.store(),
            domain::scope(tenant, "business"),
            Some(b"live"),
        )
        .unwrap();
    }
    domain::state_write(fixture.store(), domain::scope("alpha", "business"), None).unwrap();
    let report = verify(&fixture.store().snapshot().unwrap(), &quotas).unwrap();
    assert_eq!(
        report.configuration_digest,
        configuration_digest(&quotas).unwrap()
    );
    assert_eq!(report.global_rows, 1);
    assert_eq!(report.rows, 11);
    fixture.reopen();
    assert_eq!(
        verify(&fixture.store().snapshot().unwrap(), &quotas).unwrap(),
        report
    );
}

#[test]
fn actual_startup_census_refuses_valid_encoded_drift_and_orphaned_state_instead_of_repairing_counters(
) {
    let fixture = Fixture::new();
    let quotas = [quota("alpha")];
    fixture.install(&quotas);
    fixture
        .store()
        .apply(domain::create(fixture.store(), "alpha", "business"))
        .unwrap();
    domain::state_write(
        fixture.store(),
        domain::scope("alpha", "business"),
        Some(b"live"),
    )
    .unwrap();
    let view = fixture.store().snapshot().unwrap();
    let key = quota_key(&quotas[0].tenant).unwrap();
    let original = view.get(&key).unwrap().unwrap();
    let mut record = TenantRecord::decode(&original).unwrap();
    record.usage.state_bytes += 1;
    let changed = record.encode().unwrap();
    drop(view);
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(original.clone()),
            }],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(changed),
            }],
        })
        .unwrap();
    assert_eq!(
        verify(&fixture.store().snapshot().unwrap(), &quotas),
        Err(StoreError::Corrupt)
    );
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(original),
            }],
        })
        .unwrap();
    let view = fixture.store().snapshot().unwrap();
    let (mut key, bytes) = view
        .scan(Family::State, b"", 1, 4096)
        .unwrap()
        .pop()
        .unwrap();
    key.key.extend_from_slice(b"-orphan");
    drop(view);
    fixture
        .store()
        .apply(row(key.family, &key.key, &bytes))
        .unwrap();
    assert_eq!(
        verify(&fixture.store().snapshot().unwrap(), &quotas),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn census_refuses_unconfigured_ownership_duplicate_rows_and_unbounded_global_exclusions() {
    let fixture = Fixture::new();
    let quotas = [quota("alpha")];
    fixture.install(&quotas);
    let view = fixture.store().snapshot().unwrap();
    let capture = || {
        TenantCensus::capture(
            &view,
            &quotas,
            GlobalMetadataAllowance {
                rows: 5,
                bytes: 256 * 1024,
            },
            Instant::now() + Duration::from_secs(20),
        )
        .unwrap()
    };
    let fake = RowKey {
        family: Family::Namespace,
        key: b"unknown".to_vec(),
    };
    let mut census = capture();
    assert_eq!(
        census.observe(
            &fake,
            b"unknown",
            TenantCensusContribution::Covered {
                tenant: TenantId("missing".into())
            }
        ),
        Err(StoreError::UnsupportedFormat)
    );
    assert_eq!(census.finish(), Err(StoreError::Corrupt));
    let mut census = capture();
    let key = guard_key();
    let bytes = view.get(&key).unwrap().unwrap();
    census
        .observe(&key, &bytes, TenantCensusContribution::Global)
        .unwrap();
    assert_eq!(
        census.observe(&key, &bytes, TenantCensusContribution::Global),
        Err(StoreError::Corrupt)
    );
    let mut census = capture();
    let fake = RowKey {
        family: Family::Maintenance,
        key: b"foreign-global".to_vec(),
    };
    assert_eq!(
        census.observe(&fake, b"unknown", TenantCensusContribution::Global),
        Err(StoreError::UnsupportedFormat)
    );
    let mut census = TenantCensus::capture(
        &view,
        &quotas,
        GlobalMetadataAllowance {
            rows: 1,
            bytes: row_charge(&key, &bytes).unwrap() - 1,
        },
        Instant::now() + Duration::from_secs(20),
    )
    .unwrap();
    assert_eq!(
        census.observe(&key, &bytes, TenantCensusContribution::Global),
        Err(StoreError::Capacity)
    );
    assert!(matches!(
        TenantCensus::capture(
            &view,
            &quotas,
            GlobalMetadataAllowance { rows: 65, bytes: 1 },
            Instant::now() + Duration::from_secs(20)
        ),
        Err(StoreError::Invalid)
    ));
    assert!(matches!(
        TenantCensus::capture(
            &view,
            &quotas,
            GlobalMetadataAllowance { rows: 1, bytes: 1 },
            Instant::now().checked_sub(Duration::from_secs(1)).unwrap()
        ),
        Err(StoreError::Invalid)
    ));
}
