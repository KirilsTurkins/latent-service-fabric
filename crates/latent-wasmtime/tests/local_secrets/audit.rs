use super::*;
use latent_audit::*;
use sha2::{Digest, Sha256};

#[tokio::test]
async fn real_secret_audit_and_status_contain_no_plaintext_or_value_digest() {
    let directory = tempfile::TempDir::new().unwrap();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let f = Fixture::configured(
        Some(audit.clone()),
        latent_capabilities::broker::pools::ProviderPoolLimits::default(),
    )
    .await;
    let secret = "never-log-secret-plaintext-215";
    write(&f.directory.path().join("secrets/value"), secret.as_bytes());
    f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
    assert_eq!(invoke(&f, 0).await, marker(b'n', b'2', secret.len() as u64));
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
            Err(e) if e.message == "audit-busy" && Instant::now() < deadline => {
                tokio::task::yield_now().await;
            }
            result => break result.unwrap().wait().await.unwrap(),
        }
    };
    assert_eq!(page.records().len(), 2);
    let text = serde_json::to_string(page.records()).unwrap();
    assert!(!text.contains(secret));
    assert!(!text.contains(&format!("{:x}", Sha256::digest(secret.as_bytes()))));
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("terminal audit")
    };
    assert_eq!(
        conclusion
            .identities
            .capability
            .as_ref()
            .unwrap()
            .provider_outcome,
        Some(AuditProviderOutcome::SecretResolved)
    );
    let status = format!(
        "{:?} {:?} {:?}",
        f.secrets.snapshot().unwrap(),
        f.pools.snapshot().unwrap(),
        f.broker.snapshot()
    );
    assert!(!status.contains(secret));
    drop(page);
    shutdown(&f).await;
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(2))
        .unwrap());
}
