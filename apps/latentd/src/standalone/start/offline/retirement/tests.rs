use super::Catalogs;
use crate::config::{NodeConfig, NodeSettings};
use latent_audit::{AuditFilter, AuditQueryRequest, AuditScope};
use latent_capabilities::broker::CapabilityPlanSource;
use latent_core::{ContractId, FunctionId, ServiceId, TenantId};
use latent_policy::capability::RecordKind;
use latent_routing::{InvocationTarget, RouteResolver};
use std::time::Duration;
use tempfile::TempDir;

mod fixture;
pub(super) mod inspectors;

type PolicyShutdownObserver = Box<
    dyn FnOnce(
            crate::standalone::policies::PolicyShutdownReport,
        ) -> latent_core::BoxFuture<'static, ()>
        + Send,
>;
thread_local! {
    static POLICY_SHUTDOWN: std::cell::RefCell<Option<PolicyShutdownObserver>> = const {
        std::cell::RefCell::new(None)
    };
}

pub(super) async fn observe_policy_shutdown(
    report: Option<crate::standalone::policies::PolicyShutdownReport>,
) {
    if let Some(report) = report {
        let observer = POLICY_SHUTDOWN.with(|observer| observer.borrow_mut().take());
        if let Some(observer) = observer {
            observer(report).await;
        }
    }
}

fn settings(directory: &TempDir) -> NodeSettings {
    let config: NodeConfig = serde_json::from_value(serde_json::json!({
        "formatVersion":1,"dataDirectory":directory.path().join("node"),
        "nodeId":"catalog-retirement","bind":"127.0.0.1:0",
        "budgetProfile":{"mode":"phase3","maximumOutboundRequests":8,
            "maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536},
        "credentials":[{"token":"LSF-PUBLIC-CATALOG-RETIREMENT-TEST-ONLY",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "audit":{"mode":"durable"},"rollouts":{"mode":"manual"},
        "capabilityPolicies":{"formatVersion":1}
    }))
    .unwrap();
    let mut settings = config.derive().unwrap();
    settings.shutdown_grace = Duration::from_secs(5);
    settings
}

#[tokio::test]
async fn warm_configured_binding_graph_retires_before_policy_reader_observation() {
    let directory = TempDir::new().unwrap();
    let (settings, catalogs) = fixture::warm(&directory).await;
    let policy = catalogs.policies.as_ref().unwrap().handle().store().clone();
    assert_eq!(catalogs.deployments.binding_inventory().2, 1);
    assert!(policy.retained_read_owners() > 0);
    let clean = catalogs.retire_recovery(&settings).await;
    assert_eq!(policy.retained_read_owners(), 0);
    assert!(clean);
}

#[tokio::test]
async fn retained_original_compiled_plan_prevents_clean_retirement_until_actual_drop() {
    let directory = TempDir::new().unwrap();
    let (settings, catalogs) = fixture::warm(&directory).await;
    let policy = catalogs.policies.as_ref().unwrap().handle().store().clone();
    let target = InvocationTarget {
        tenant: TenantId("tests".into()),
        service: ServiceId("tests/packaging".into()),
        contract: ContractId("tests:packaging/api@1.0.0".into()),
        function: FunctionId("inspect".into()),
        route: None,
    };
    let pin = catalogs.deployments.pin().unwrap();
    let revision = pin.resolve(&target, None).unwrap();
    let plan = catalogs.deployments.plan(&revision).unwrap();
    drop(pin);
    assert!(!catalogs.retire_recovery(&settings).await);
    assert!(policy.retained_read_owners() > 0);
    drop(plan);
    assert_eq!(policy.retained_read_owners(), 0);
}

#[tokio::test]
async fn retained_policy_read_prevents_clean_retirement_until_actual_drop() {
    let directory = TempDir::new().unwrap();
    let settings = settings(&directory);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let policy = catalogs.policies.as_ref().unwrap().handle().store().clone();
    let read = policy
        .get(
            "tests",
            RecordKind::Policy,
            "missing",
            65536,
            fixture::deadline(),
        )
        .unwrap();
    assert_eq!(policy.retained_read_owners(), 1);
    assert!(!catalogs.retire_recovery(&settings).await);
    assert_eq!(policy.retained_read_owners(), 1);
    drop(read);
    assert_eq!(policy.retained_read_owners(), 0);
}

#[tokio::test]
async fn retained_audit_page_rejects_successful_join_report_until_actual_release() {
    let directory = TempDir::new().unwrap();
    let settings = settings(&directory);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let audit = catalogs.audit.as_ref().unwrap().handle();
    let page = audit
        .query(
            AuditQueryRequest {
                scope: AuditScope::Node,
                filter: AuditFilter::default(),
                cursor: None,
                limit: 1,
                maximum_bytes: 65536,
            },
            fixture::deadline(),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert_eq!(audit.snapshot().query_owners, 1);
    let report = catalogs
        .audit
        .as_ref()
        .unwrap()
        .shutdown(settings.shutdown_grace())
        .await
        .unwrap();
    assert!(report.worker_joined);
    assert_eq!(report.query_owners, 1);
    assert!(!report.clean());
    assert!(!catalogs.retire_recovery(&settings).await);
    assert_eq!(audit.snapshot().query_owners, 1);
    drop(page);
    assert_eq!(audit.snapshot().query_owners, 0);
    assert_eq!(audit.snapshot().query_bytes, 0);
}

#[tokio::test]
async fn retained_rollout_response_rejects_successful_join_report_until_actual_release() {
    let directory = TempDir::new().unwrap();
    let settings = settings(&directory);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let rollout = catalogs.rollouts.as_ref().unwrap().handle();
    let response = rollout
        .get(
            TenantId("tests".into()),
            latent_control_store::rollouts::RolloutId("missing".into()),
            fixture::deadline(),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(response.value().is_none());
    assert_eq!(rollout.snapshot().response_owners, 1);
    let report = catalogs
        .rollouts
        .as_ref()
        .unwrap()
        .shutdown(settings.shutdown_grace())
        .await
        .unwrap();
    assert!(report.worker_joined);
    assert_eq!(report.response_owners, 1);
    assert!(!report.clean());
    assert!(!catalogs.retire_recovery(&settings).await);
    assert!(!rollout.snapshot().worker_live);
    assert_eq!(rollout.snapshot().response_owners, 1);
    drop(response);
    assert_eq!(rollout.snapshot().response_owners, 0);
    assert_eq!(rollout.snapshot().response_bytes, 0);
}

#[tokio::test]
async fn original_policy_work_deadline_cannot_be_replaced_by_late_retirement() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = None;
    settings.rollouts = None;
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let handle = catalogs.policies.as_ref().unwrap().handle();
    let permit = handle.reserve().unwrap();
    let (started, running) = std::sync::mpsc::sync_channel(1);
    let (release, held) = std::sync::mpsc::sync_channel(1);
    let work = permit.run(move |_| {
        started.send(()).unwrap();
        held.recv_timeout(Duration::from_secs(5)).unwrap();
        Ok(())
    });
    running.recv_timeout(Duration::from_secs(5)).unwrap();
    let observed = handle.clone();
    let reached = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let boundary = reached.clone();
    POLICY_SHUTDOWN.with(|observer| {
        *observer.borrow_mut() = Some(Box::new(move |report| {
            Box::pin(async move {
                assert!(!report.work_completed);
                assert_eq!(report.active_jobs, 1);
                assert_eq!(observed.active_jobs(), 1);
                release.send(()).unwrap();
                work.await.unwrap();
                assert_eq!(observed.active_jobs(), 0);
                boundary.store(true, std::sync::atomic::Ordering::Release);
            })
        }));
    });
    // Expire this original cutoff while its real policy work remains attached.
    // The committed report hook releases it only after shutdown reports failure.
    settings.shutdown_grace = Duration::ZERO;
    assert!(!catalogs.retire_recovery(&settings).await);
    assert!(reached.load(std::sync::atomic::Ordering::Acquire));
    assert_eq!(handle.active_jobs(), 0);
    assert_eq!(handle.store().retained_read_owners(), 0);
}

#[tokio::test]
async fn actual_shutdown_report_errors_refuse_clean_and_preserve_owned_workers() {
    let directory = TempDir::new().unwrap();
    let settings = settings(&directory);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let rollout = catalogs.rollouts.as_ref().unwrap();
    let result = rollout.shutdown(Duration::MAX).await;
    assert_eq!(
        result.as_ref().unwrap_err().code,
        latent_core::PlatformErrorCode::InvalidArgument
    );
    assert!(!result.is_ok_and(crate::standalone::rollouts::RolloutShutdownReport::clean));
    assert!(!rollout.worker_joined().await);
    let audit = catalogs.audit.as_ref().unwrap();
    let result = audit.shutdown(Duration::MAX).await;
    assert_eq!(
        result.as_ref().unwrap_err().code,
        latent_core::PlatformErrorCode::InvalidArgument
    );
    assert!(!result.is_ok_and(crate::standalone::audit::AuditShutdownReport::clean));
    assert!(catalogs.retire_recovery(&settings).await);
}
