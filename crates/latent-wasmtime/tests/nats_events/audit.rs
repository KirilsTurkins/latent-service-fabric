use super::*;
use latent_audit::*;
use sha2::{Digest, Sha256};
#[tokio::test]
#[ignore = "requires tools/run_nats_event_tests.py owned pinned TLS JetStream"]
async fn real_nats_audit_preserves_broker_ack_and_uncertainty_without_event_or_credentials() {
    control("reset-fixture");
    let directory = tempfile::TempDir::new().unwrap();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let proxy = proxy::Proxy::new(config()).await;
    let f = Fixture::new(
        proxy.config.clone(),
        Some(audit.clone()),
        ProviderPoolLimits::default(),
    )
    .await;
    assert_eq!(invoke(&f, 0).await, 2);
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    assert_eq!(invoke(&f, 0).await, 1007);
    let query = AuditQueryRequest {
        scope: AuditScope::Tenant(TenantId("tests".into())),
        filter: AuditFilter::default(),
        cursor: None,
        limit: 32,
        maximum_bytes: 32768,
    };
    let deadline = Instant::now() + Duration::from_secs(2);
    let page = loop {
        match audit.query(query.clone(), deadline) {
            Err(e) if e.message == "audit-busy" && Instant::now() < deadline => {
                tokio::task::yield_now().await
            }
            result => break result.unwrap().wait().await.unwrap(),
        }
    };
    assert_eq!(page.records().len(), 4);
    let outcomes: Vec<_> = page
        .records()
        .iter()
        .filter_map(|record| match &record.data {
            AuditRecordData::Outcome { conclusion, .. } => Some(
                conclusion
                    .identities
                    .capability
                    .as_ref()
                    .unwrap()
                    .provider_outcome,
            ),
            _ => None,
        })
        .collect();
    assert_eq!(
        outcomes,
        vec![
            Some(AuditProviderOutcome::BrokerAcknowledged),
            Some(AuditProviderOutcome::Unknown)
        ]
    );
    let public = format!(
        "{} {:?} {:?}",
        serde_json::to_string(page.records()).unwrap(),
        f.provider.snapshot(),
        f.pools.snapshot().unwrap()
    );
    for secret in ["lsf-public-nats-password", "synthetic-event", "guest-key"] {
        assert!(!public.contains(secret));
        assert!(!public.contains(&format!("{:x}", Sha256::digest(secret.as_bytes()))));
    }
    drop(page);
    shutdown(&f).await;
    proxy.close().await;
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(2))
        .unwrap());
}
