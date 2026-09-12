use latent_audit::{
    AuditCacheKind, AuditFilter, AuditHandle, AuditQueryRequest, AuditRecordData, AuditScope,
    Phase2AuditEventKind,
};
use latent_core::{ReleaseDigest, TenantId};
use std::time::{Duration, Instant};

pub(super) async fn assert_native_events(handle: &AuditHandle, release: &ReleaseDigest) {
    let deadline = Instant::now() + Duration::from_secs(5);
    let request = || AuditQueryRequest {
        scope: AuditScope::Tenant(TenantId("tests".into())),
        filter: AuditFilter::default(),
        cursor: None,
        limit: 8,
        maximum_bytes: 32768,
    };
    let mut ticket = None;
    // Only the fixture's query enqueue may retry its documented transient busy
    // status. Compilation, loading, invocation and capture are never retried.
    for _ in 0..128 {
        match handle.query(request(), deadline) {
            Ok(accepted) => {
                ticket = Some(accepted);
                break;
            }
            Err(error) if error.message == "audit-busy" => tokio::task::yield_now().await,
            Err(error) => panic!("audit fixture query failed: {}", error.message),
        }
    }
    let page = ticket
        .expect("bounded audit query admission")
        .wait()
        .await
        .unwrap();
    assert_eq!(
        page.records().len() as u64 + page.coverage().dropped_observations,
        2
    );
    for record in page.records() {
        let AuditRecordData::Observation(event) = &record.data else {
            panic!("expected native observation")
        };
        assert!(matches!(
            event.kind,
            Phase2AuditEventKind::CacheMiss | Phase2AuditEventKind::CacheHit
        ));
        assert_eq!(event.cache_kind, Some(AuditCacheKind::Native));
        assert_eq!(event.identities.component.as_ref(), Some(release));
        assert!(event.identities.package.is_none());
    }
}
