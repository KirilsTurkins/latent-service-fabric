use super::support::{request, Harness};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditCacheKind, AuditFilter, AuditIdentities, AuditLimits,
    AuditObservation, AuditOutcome, AuditQueryRequest, AuditReason, AuditScope,
    DirectoryPhase2AuditJournal, Phase2AuditEventKind,
};
use latent_core::TenantId;
use latent_wire::management::{proto, ManagementLimits};
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tonic::Code;

fn query(kind: proto::AuditScopeKind, tenant: Option<&str>) -> proto::QueryPhase2AuditRequest {
    proto::QueryPhase2AuditRequest {
        scope: Some(proto::AuditQueryScope {
            kind: kind as i32,
            tenant: tenant.map(Into::into),
        }),
        filter: None,
        page: Some(proto::PageRequest {
            page_size: 1,
            page_token: None,
        }),
    }
}

fn accepted<T>(mut enqueue: impl FnMut() -> Result<T, latent_core::PlatformError>) -> T {
    // Fixture setup alone retries the documented short bookkeeping contention.
    for _ in 0..128 {
        match enqueue() {
            Ok(value) => return value,
            Err(error) if error.message == "audit-busy" => std::thread::yield_now(),
            Err(error) => panic!("audit fixture enqueue failed: {}", error.message),
        }
    }
    panic!("audit fixture enqueue exceeded its finite attempts");
}

async fn populate(handle: &latent_audit::AuditHandle) {
    for scope in [
        AuditScope::Tenant(TenantId("acme".into())),
        AuditScope::Tenant(TenantId("other".into())),
        AuditScope::Node,
    ] {
        let observation = AuditObservation {
            scope,
            actor: AuditActorIdentity {
                kind: AuditActorKind::Host,
                subject: "audit-test".into(),
            },
            kind: Phase2AuditEventKind::CacheMiss,
            outcome: AuditOutcome::Succeeded,
            identities: AuditIdentities::default(),
            reason: AuditReason::CacheMiss,
            cache_kind: Some(AuditCacheKind::Raw),
            occurred_at_unix_millis: 100,
        };
        accepted(|| handle.try_capture(&observation));
    }
    // The queued query follows the three captures on the same worker; its
    // completion proves the fixtures are durably processed without sleeps.
    drop(
        accepted(|| {
            handle.query(
                AuditQueryRequest {
                    scope: AuditScope::Node,
                    filter: AuditFilter::default(),
                    cursor: None,
                    limit: 1,
                    maximum_bytes: 32768,
                },
                Instant::now() + Duration::from_secs(5),
            )
        })
        .wait()
        .await
        .unwrap(),
    );
}

#[tokio::test]
async fn actual_audit_clients_enforce_scopes_and_bound_cursor_reuse() {
    let directory = TempDir::new().unwrap();
    let (handle, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    populate(&handle).await;
    let harness =
        Harness::with_audit(ManagementLimits::default(), None, Some(handle.clone())).await;
    let mut client = proto::audit_service_client::AuditServiceClient::new(harness.channel.clone());
    let acme = query(proto::AuditScopeKind::Tenant, Some("acme"));
    let page = client
        .query_phase2_audit(request("alice", acme.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(page.records.len(), 1);
    assert_eq!(
        page.records[0].scope.as_ref().unwrap().tenant.as_deref(),
        Some("acme")
    );
    assert_eq!(
        page.records[0].actor.as_ref().unwrap().subject,
        "audit-test"
    );
    for identity in ["alice", "operator"] {
        assert_eq!(
            client
                .query_phase2_audit(request(
                    identity,
                    query(proto::AuditScopeKind::Tenant, Some("other"))
                ))
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    assert_eq!(
        client
            .query_phase2_audit(request("caller", acme.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(
        client
            .query_phase2_audit(request("alice", query(proto::AuditScopeKind::Node, None)))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    let node = client
        .query_phase2_audit(request(
            "operator",
            query(proto::AuditScopeKind::Node, None),
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(node.records.len(), 1);
    assert_eq!(
        node.records[0].scope.as_ref().unwrap().kind,
        proto::AuditScopeKind::Node as i32
    );

    let token = page
        .page
        .unwrap()
        .next_page_token
        .expect("the bounded scan stopped before later records");
    let mut foreign = query(proto::AuditScopeKind::Tenant, Some("other"));
    foreign.page.as_mut().unwrap().page_token = Some(token);
    assert!(client
        .query_phase2_audit(request("bob", foreign))
        .await
        .is_err());
    check_legacy_projection(&mut client).await;
    drop(client);
    harness.shutdown().await;
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

async fn check_legacy_projection(
    client: &mut proto::audit_service_client::AuditServiceClient<tonic::transport::Channel>,
) {
    let legacy = client
        .query_audit(request("alice", proto::QueryAuditRequest::default()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(legacy.events.len(), 1);
    assert_eq!(
        legacy.events[0].actor.as_ref().unwrap().tenant.as_deref(),
        Some("acme")
    );
    assert_eq!(legacy.events[0].action, "cache-miss");
    assert_eq!(legacy.events[0].outcome, "succeeded");
    let unsupported = proto::QueryAuditRequest {
        resource_prefix: Some("sha256:".into()),
        ..Default::default()
    };
    assert_eq!(
        client
            .query_audit(request("alice", unsupported))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
}

#[tokio::test]
async fn disabled_audit_is_explicit_and_does_not_bypass_authentication() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client = proto::audit_service_client::AuditServiceClient::new(harness.channel.clone());
    assert_eq!(
        client
            .query_audit(request("alice", proto::QueryAuditRequest::default()))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(
        client
            .query_audit(tonic::Request::new(proto::QueryAuditRequest::default()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    drop(client);
    harness.shutdown().await;
}
