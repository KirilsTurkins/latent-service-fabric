use super::*;
use latent_audit::*;
use sha2::{Digest, Sha256};

#[tokio::test]
async fn required_audit_records_operations_and_outcomes_without_generated_bytes_or_digests() {
    let directory = tempfile::TempDir::new().unwrap();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let source = Arc::new(Source::default());
    let f = Fixture::configured(
        Some(source.clone()),
        RandomLimits::default(),
        Some(audit.clone()),
    )
    .await;
    assert_eq!(invoke(&f, 0, 16, 1).await, marker(16));
    source.fail.store(true, Ordering::Release);
    assert_eq!(invoke(&f, 1, 0, 1).await, UNAVAILABLE);
    let request = AuditQueryRequest {
        scope: AuditScope::Tenant(TenantId("tests".into())),
        filter: AuditFilter::default(),
        cursor: None,
        limit: 32,
        maximum_bytes: 32768,
    };
    let deadline = Instant::now() + Duration::from_secs(2);
    let page = loop {
        match audit.query(request.clone(), deadline) {
            Err(error) if error.message == "audit-busy" && Instant::now() < deadline => {
                tokio::task::yield_now().await;
            }
            result => break result.unwrap().wait().await.unwrap(),
        }
    };
    assert_eq!(page.records().len(), 4);
    let text = serde_json::to_string(page.records()).unwrap();
    for forbidden in [
        "*".repeat(16),
        format!("{:x}", Sha256::digest([42; 16])),
        SCALAR.to_string(),
    ] {
        assert!(!text.contains(&forbidden));
        assert!(!format!("{:?}", f.provider.snapshot()).contains(&forbidden));
    }
    let outcomes: Vec<_> = page
        .records()
        .iter()
        .filter_map(|record| match &record.data {
            AuditRecordData::Outcome { conclusion, .. } => {
                let capability = conclusion.identities.capability.as_ref().unwrap();
                assert_eq!(
                    capability.resource_class,
                    AuditCapabilityResourceClass::Random
                );
                Some((capability.operation.as_str(), capability.provider_outcome))
            }
            _ => None,
        })
        .collect();
    assert_eq!(
        outcomes,
        vec![
            ("bytes", Some(AuditProviderOutcome::HostCompleted)),
            ("u64-value", Some(AuditProviderOutcome::Rejected)),
        ]
    );
    drop(page);
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(2))
        .unwrap());
    // A required audit owner cannot be silently replaced with unrecorded entropy.
    source.fail.store(false, Ordering::Release);
    assert_eq!(invoke(&f, 0, 8, 1).await, UNAVAILABLE);
    assert_eq!(source.calls.load(Ordering::Acquire), 2);
}
