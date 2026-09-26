use super::*;
use latent_audit::*;
use sha2::{Digest, Sha256};

#[tokio::test]
#[ignore = "requires tools/run_vault_secret_tests.py owned pinned TLS Vault"]
async fn real_vault_audit_and_status_redact_token_and_value_material() {
    setup::control("reset-fixture");
    let directory = tempfile::TempDir::new().unwrap();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let f = setup::fixture(setup::configured(), Some(audit.clone())).await;
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
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
                tokio::task::yield_now().await
            }
            result => break result.unwrap().wait().await.unwrap(),
        }
    };
    assert_eq!(page.records().len(), 2);
    let text = format!(
        "{} {:?} {:?} {:?}",
        serde_json::to_string(page.records()).unwrap(),
        f.provider.snapshot().unwrap(),
        f.pools.snapshot().unwrap(),
        f.broker.snapshot()
    );
    for material in ["Alpha", setup::FIRST_TOKEN, setup::SECOND_TOKEN] {
        assert!(!text.contains(material));
        assert!(!text.contains(&format!("{:x}", Sha256::digest(material.as_bytes()))));
    }
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("terminal audit")
    };
    let capability = conclusion.identities.capability.as_ref().unwrap();
    assert_eq!(
        capability.provider_outcome,
        Some(AuditProviderOutcome::SecretResolved)
    );
    assert_eq!(capability.provider_configuration_epoch, 1);
    drop(page);
    shutdown(&f).await;
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(2))
        .unwrap());
}
