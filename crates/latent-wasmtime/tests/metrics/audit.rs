use super::*;
use latent_audit::*;

#[tokio::test]
async fn required_audit_records_capture_acceptance_and_rejection_but_not_export_durability() {
    let directory = tempfile::TempDir::new().unwrap();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let mut config = config();
    config.limits.maximum_series_per_tenant = 1;
    let mut f = Fixture::configured(
        MetricActivationLimits::default(),
        config,
        Some(audit.clone()),
    )
    .await;
    assert_eq!(
        invoke(&f, metric("requests", "counter", 1.0), 1, 0).await,
        1
    );
    assert_eq!(
        invoke(&f, metric("temperature", "gauge", 1.0), 1, 0).await,
        EXHAUSTED
    );
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
    let outcomes: Vec<_> = page
        .records()
        .iter()
        .filter_map(|record| match &record.data {
            AuditRecordData::Outcome { conclusion, .. } => {
                let capability = conclusion.identities.capability.as_ref().unwrap();
                assert_eq!(
                    capability.resource_class,
                    AuditCapabilityResourceClass::Telemetry
                );
                Some((capability.operation.as_str(), capability.provider_outcome))
            }
            _ => None,
        })
        .collect();
    assert_eq!(
        outcomes,
        vec![
            ("emit-metric", Some(AuditProviderOutcome::HostCompleted)),
            ("emit-metric", Some(AuditProviderOutcome::Rejected)),
        ]
    );
    drop(page);
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(2))
        .unwrap());
    // Capture must not silently bypass a required audit owner.
    assert_eq!(
        invoke(&f, metric("requests", "counter", 1.0), 1, 0).await,
        UNAVAILABLE
    );
    assert_eq!(f.provider.snapshot().accepted, 1);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
