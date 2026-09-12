use super::*;
use latent_audit::AuditLimits;
use latent_wire::management::proto;
use std::time::Duration;

#[tokio::test]
async fn configured_node_serves_audit_and_joins_the_same_worker_on_shutdown() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    settings.shutdown_grace = Duration::from_secs(5);
    let node = super::super::StandaloneNode::start(
        settings,
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    )
    .await
    .unwrap();
    let endpoint = format!("http://{}", node.endpoint());
    let mut client = proto::audit_service_client::AuditServiceClient::connect(endpoint)
        .await
        .unwrap();
    let mut request = tonic::Request::new(proto::QueryPhase2AuditRequest {
        scope: Some(proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Node as i32,
            tenant: None,
        }),
        filter: None,
        page: None,
    });
    request.metadata_mut().insert(
        "authorization",
        "Bearer test-token-000000000000000000000000000000"
            .parse()
            .unwrap(),
    );
    request.set_timeout(Duration::from_secs(5));
    let page = client
        .query_phase2_audit(request)
        .await
        .unwrap()
        .into_inner();
    assert!(page.records.is_empty());
    let coverage = page.coverage.unwrap();
    assert_eq!(coverage.stop, proto::AuditPageStop::End as i32);
    assert!(!coverage.previous_session_loss_unknown);
    drop(client);
    let report = node.shutdown().await.unwrap();
    assert!(report.clean);
    assert!(report.audit.unwrap().worker_joined);
}

#[tokio::test]
async fn omitted_audit_rejects_a_previously_owned_root_after_reopen() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    assert!(catalogs
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
    drop(catalogs);
    settings.audit = None;
    let error = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(error.message, "audit-mode-downgrade-forbidden");
}

#[tokio::test]
async fn failed_authority_startup_closes_audit_before_returning() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    enforce(&mut settings);
    assert!(
        Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
            .await
            .is_err()
    );
    let reopened = crate::standalone::audit::AuditRuntime::open(
        settings.data_directory.join("audit"),
        settings.audit,
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap()
    .unwrap();
    let report = reopened.shutdown(Duration::from_secs(5)).await.unwrap();
    assert!(report.clean());
    assert!(report.previous_session_loss_unknown);
}

#[tokio::test]
async fn unaudited_catalog_cannot_be_composed_under_audited_settings() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    let catalogs = Catalogs::open(&settings).await.unwrap();
    settings.audit = Some(AuditLimits::default());
    assert_eq!(
        super::super::StandaloneNode::compose(
            &mut settings,
            &catalogs,
            Arc::new(SystemActivationClock)
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
}
